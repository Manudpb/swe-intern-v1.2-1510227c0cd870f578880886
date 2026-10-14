"""`safetyChecker` — two detectors, then rewrite, sanitize, refuse.

Operator decision (research D9): both detectors run on **every** report and a limit is
satisfied only if both agree. The rule pass is exhaustively unit-testable with no model call;
the low-effort LLM review catches the paraphrased violation no word list will ever match
("you can rest assured this will be taken care of" is a coverage promise with none of the
trigger words). A disagreement resolves against the report.

The ladder is bounded by construction — one review, one rewrite, one re-review, one
sanitization, then 422. No stage repeats (invariant I12, FR-028).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from claim_triage.api.schemas import SafetyChecks
from claim_triage.deps import Deps
from claim_triage.llm.ports import LLMUnavailable

log = logging.getLogger(__name__)

REVIEW_PROMPT = (Path(__file__).parent / "prompts" / "safety_review.md").read_text(encoding="utf-8")
REWRITE_PROMPT = (Path(__file__).parent / "prompts" / "safety_rewrite.md").read_text(encoding="utf-8")

LIMITS = (
    "no_coverage_promises",
    "no_legal_advice",
    "no_settlement_amounts",
    "no_liability_determination",
    "no_emotional_language",
)

VERDICT_TOOL = {
    "name": "report_safety_verdict",
    "description": "Report the five limits and quote the offending sentence for each violation.",
    "input_schema": {
        "type": "object",
        "properties": {
            **{limit: {"type": "boolean"} for limit in LIMITS},
            "violations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "string", "enum": list(LIMITS)},
                        "sentence": {
                            "type": "string",
                            "description": "The offending sentence copied verbatim from the text.",
                        },
                    },
                    "required": ["limit", "sentence"],
                },
            },
        },
        "required": list(LIMITS),
    },
}

REWRITE_TOOL = {
    "name": "submit_rewritten_text",
    "description": "Submit corrected text that preserves every factual statement.",
    "input_schema": {
        "type": "object",
        "properties": {
            "damage_description": {"type": "string"},
            "recommendation": {"type": "string"},
        },
        "required": ["damage_description", "recommendation"],
    },
}

#: Lexical patterns per limit. Deliberately conservative: the LLM reviewer is the net for
#: paraphrase, so a pattern here should be something a reviewer would call a violation too.
RULES: dict[str, tuple[re.Pattern[str], ...]] = {
    "no_coverage_promises": (
        re.compile(r"\b(is|are|will be)\s+(fully\s+)?covered\b", re.I),
        re.compile(r"\bwill\s+(be\s+)?(paid|reimbursed|compensated)\b", re.I),
        re.compile(r"\b(we\s+)?guarantee\b", re.I),
        re.compile(r"\brest assured\b", re.I),
        re.compile(r"\bcoverage is (confirmed|approved|assured)\b", re.I),
        re.compile(r"\bclaim (is|has been) approved\b", re.I),
    ),
    "no_legal_advice": (
        re.compile(r"\b(should|must|ought to)\s+(sue|litigate|take legal action)\b", re.I),
        # Passive and bare forms too: "should be sued" is advice just as much as "should sue".
        re.compile(r"\b(sue|sued|suing|litigat(e|ed|ing|ion))\b", re.I),
        re.compile(r"\b(legal action|legal counsel|consult (a|your) (lawyer|attorney))\b", re.I),
        re.compile(r"\b(legally (liable|responsible|obligated))\b", re.I),
        re.compile(r"\bpursue (a )?(claim against|damages from)\b", re.I),
    ),
    "no_settlement_amounts": (
        re.compile(r"\b(settlement|payout|compensation|award)\s+(of|amount|figure|at)\b", re.I),
        re.compile(r"\b(settle|pay out|payout)\w*\s+(for|at)\s*\$", re.I),
        re.compile(r"\bexpect (a|an)?\s*(settlement|payout|payment)\b", re.I),
        re.compile(r"\bwe will pay\b", re.I),
    ),
    "no_liability_determination": (
        re.compile(r"\b(at fault|to blame|is liable|are liable|liability (lies|rests))\b", re.I),
        re.compile(r"\b(negligen(t|ce))\b", re.I),
        re.compile(r"\bcaused by the (neighbou?r|tenant|landlord|contractor|claimant)\b", re.I),
        re.compile(r"\b(fault|blame) (lies|rests) with\b", re.I),
    ),
    "no_emotional_language": (
        re.compile(r"\b(devastat(ed|ing)|tragic|tragedy|heart-?break(ing)?|horrific|catastrophe)\b", re.I),
        re.compile(r"\b(we are (so )?sorry|our deepest sympath(y|ies)|unimaginable)\b", re.I),
        re.compile(r"\b(terrible|awful|shocking)\s+(loss|ordeal|experience)\b", re.I),
    ),
}

#: A bare currency figure outside the structured cost object reads as a settlement amount.
_MONEY = re.compile(r"\$\s?\d[\d,]*(\.\d+)?(\s?(k|m|million))?", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Violation:
    limit: str
    sentence: str
    source: str  # "rules" | "review"


@dataclass
class Verdict:
    checks: SafetyChecks
    violations: list[Violation] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return self.checks.all_clear()


@dataclass
class SafetyOutcome:
    checks: SafetyChecks
    damage_description: str
    recommendation: str
    delivered: bool
    stages: list[str] = field(default_factory=list)
    message: str = ""


# --- detector 1: deterministic rules -------------------------------------------------


def rule_scan(damage_description: str, recommendation: str, *, cost_text: str = "") -> Verdict:
    """The free detector. Records the limit AND the sentence that triggered it."""
    violations: list[Violation] = []
    failed: set[str] = set()

    for text in (damage_description, recommendation):
        for sentence in _sentences(text):
            for limit, patterns in RULES.items():
                if any(pattern.search(sentence) for pattern in patterns):
                    failed.add(limit)
                    violations.append(Violation(limit, sentence, "rules"))
            # A currency figure in prose is a settlement amount unless it is the table range.
            for match in _MONEY.finditer(sentence):
                if match.group(0).replace(" ", "") not in cost_text.replace(" ", ""):
                    failed.add("no_settlement_amounts")
                    violations.append(Violation("no_settlement_amounts", sentence, "rules"))
                    break

    return Verdict(checks=_checks(failed), violations=violations)


# --- detector 2: the low-effort LLM review -------------------------------------------


def llm_review(deps: Deps, damage_description: str, recommendation: str) -> Verdict:
    """One small call: no thinking, temperature 0, 300 tokens, text only (research D9)."""
    payload = (
        f"damage_description:\n{damage_description}\n\nrecommendation:\n{recommendation}"
    )
    response = deps.llm.create_message(
        system=REVIEW_PROMPT,
        messages=[{"role": "user", "content": [{"type": "text", "text": payload}]}],
        tools=[VERDICT_TOOL],
        max_tokens=deps.settings.safety_max_tokens,
        temperature=0.0,
    )
    call = next((c for c in response.tool_calls if c.name == VERDICT_TOOL["name"]), None)
    if call is None:
        # No verdict means the gate did not run. We cannot certify the five limits, and
        # claiming them would violate FR-030, so this surfaces as 503 rather than being
        # quietly treated as a pass or as five fabricated failures.
        raise LLMUnavailable("The safety review returned no usable verdict")

    args = call.input
    failed = {limit for limit in LIMITS if not bool(args.get(limit, True))}
    violations: list[Violation] = []
    haystack = f"{damage_description}\n{recommendation}"
    for raw in args.get("violations") or []:
        if not isinstance(raw, dict):
            continue
        limit, sentence = raw.get("limit"), str(raw.get("sentence") or "").strip()
        if limit not in LIMITS or not sentence:
            continue
        if sentence not in haystack:
            # A quote we cannot locate cannot be removed, so it is a non-finding.
            log.warning("Safety reviewer quoted a sentence not present in the text; ignoring")
            continue
        failed.add(limit)
        violations.append(Violation(limit, sentence, "review"))
    return Verdict(checks=_checks(failed), violations=violations)


# --- composition and the ladder ------------------------------------------------------


def compose(rules: Verdict, review: Verdict) -> Verdict:
    """A limit is satisfied only if BOTH detectors say so."""
    failed = set(rules.checks.failing()) | set(review.checks.failing())
    return Verdict(checks=_checks(failed), violations=[*rules.violations, *review.violations])


def gate(
    deps: Deps, *, damage_description: str, recommendation: str, cost_text: str = ""
) -> SafetyOutcome:
    """Run the full ladder. At most three safety-route model calls (invariant I12)."""
    stages: list[str] = []

    verdict = _both(deps, damage_description, recommendation, cost_text)
    stages.append("review")
    if verdict.clean:
        return SafetyOutcome(verdict.checks, damage_description, recommendation, True, stages)

    # Stage 2: one rewrite, naming the broken rules and quoting the offending sentences.
    rewritten = _rewrite(deps, damage_description, recommendation, verdict)
    stages.append("rewrite")
    if rewritten is not None:
        new_description, new_recommendation = rewritten
        verdict = _both(deps, new_description, new_recommendation, cost_text)
        stages.append("re-review")
        if verdict.clean:
            return SafetyOutcome(verdict.checks, new_description, new_recommendation, True, stages)
        damage_description, recommendation = new_description, new_recommendation

    # Stage 4: sanitize by dropping the sentences the detectors named, then re-run the
    # deterministic pass. No further model call: the named spans are removed by
    # construction, and dropping a sentence cannot introduce a new violation.
    sanitized_description = _drop(damage_description, verdict.violations)
    sanitized_recommendation = _drop(recommendation, verdict.violations)
    stages.append("sanitize")

    if not sanitized_description.strip() or not sanitized_recommendation.strip():
        return SafetyOutcome(
            verdict.checks,
            damage_description,
            recommendation,
            False,
            stages,
            "A required field would be empty once the unsafe statements were removed.",
        )

    final = rule_scan(sanitized_description, sanitized_recommendation, cost_text=cost_text)
    remaining = [v for v in verdict.violations if v.sentence in f"{sanitized_description}\n{sanitized_recommendation}"]
    if final.clean and not remaining:
        return SafetyOutcome(
            final.checks, sanitized_description, sanitized_recommendation, True, stages
        )

    # Refusing: report the limits the composed verdict actually failed, so the 422 body
    # names what went wrong rather than a post-sanitization approximation of it.
    return SafetyOutcome(
        verdict.checks,
        sanitized_description,
        sanitized_recommendation,
        False,
        stages,
        "The report text could not be brought within the professional limits.",
    )


def _both(deps: Deps, description: str, recommendation: str, cost_text: str) -> Verdict:
    rules = rule_scan(description, recommendation, cost_text=cost_text)
    review = llm_review(deps, description, recommendation)
    return compose(rules, review)


def _rewrite(
    deps: Deps, description: str, recommendation: str, verdict: Verdict
) -> tuple[str, str] | None:
    broken = ", ".join(sorted(set(verdict.checks.failing())))
    quoted = "\n".join(f"- [{v.limit}] {v.sentence}" for v in verdict.violations) or "- (not quoted)"
    payload = (
        f"Broken limits: {broken}\n\nOffending sentences:\n{quoted}\n\n"
        f"damage_description:\n{description}\n\nrecommendation:\n{recommendation}"
    )
    try:
        response = deps.llm.create_message(
            system=REWRITE_PROMPT,
            messages=[{"role": "user", "content": [{"type": "text", "text": payload}]}],
            tools=[REWRITE_TOOL],
            max_tokens=deps.settings.llm_max_tokens,
            temperature=0.0,
        )
    except Exception:  # noqa: BLE001 - a failed rewrite falls through to sanitization
        log.warning("Safety rewrite call failed; falling through to sanitization")
        return None

    call = next((c for c in response.tool_calls if c.name == REWRITE_TOOL["name"]), None)
    if call is None:
        return None
    new_description = str(call.input.get("damage_description") or "").strip()
    new_recommendation = str(call.input.get("recommendation") or "").strip()
    if not new_description or not new_recommendation:
        return None
    return new_description, new_recommendation


def _drop(text: str, violations: list[Violation]) -> str:
    """Remove the exact sentences the detectors named."""
    offending = {v.sentence.strip() for v in violations if v.sentence.strip()}
    kept = [s for s in _sentences(text) if s.strip() not in offending]
    # Also remove any offending span that survived sentence splitting.
    result = " ".join(kept).strip()
    for sentence in offending:
        result = result.replace(sentence, "").strip()
    return " ".join(result.split())


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


def _checks(failed: set[str]) -> SafetyChecks:
    return SafetyChecks(**{limit: limit not in failed for limit in LIMITS})
