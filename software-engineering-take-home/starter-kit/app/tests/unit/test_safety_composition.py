"""US6 / research D9 - a limit is satisfied only when BOTH detectors agree.

This is the point of running two detectors: the cheap one cannot be fooled by paraphrase, and
the expensive one cannot be fooled by a pattern it happens to tolerate. A disagreement
resolves against the report.
"""
from __future__ import annotations

import pytest

from claim_triage.agents.safety import compose, llm_review, rule_scan
from claim_triage.llm.ports import LLMUnavailable
from tests.fakes import FakeLLM, ScriptedTurn, safety_turn

pytestmark = pytest.mark.unit

NEUTRAL = "Water pooling across the kitchen floor."
SAFE = "Assign an adjuster to verify the moisture readings."


def _review_llm(**overrides):
    return FakeLLM({"safety": [safety_turn(**overrides)]})


def test_both_clean_is_clean(deps):
    rules = rule_scan(NEUTRAL, SAFE)
    review = llm_review(deps, NEUTRAL, SAFE)

    assert compose(rules, review).clean


def test_the_reviewer_catches_what_the_word_list_misses(make_deps):
    """A paraphrased promise with none of the trigger words."""
    paraphrased = "Nothing here will come out of your pocket once this is processed."
    deps = make_deps(
        llm=_review_llm(
            no_coverage_promises=False,
            violations=[{"limit": "no_coverage_promises", "sentence": paraphrased}],
        )
    )

    rules = rule_scan(NEUTRAL, paraphrased)
    review = llm_review(deps, NEUTRAL, paraphrased)
    composed = compose(rules, review)

    assert rules.clean, "the word list is not expected to catch this"
    assert composed.checks.no_coverage_promises is False
    assert not composed.clean


def test_the_word_list_catches_what_the_reviewer_waves_through(make_deps):
    offending = "This damage is fully covered and will be paid."
    deps = make_deps(llm=_review_llm())  # reviewer says everything is fine

    rules = rule_scan(NEUTRAL, offending)
    review = llm_review(deps, NEUTRAL, offending)
    composed = compose(rules, review)

    assert review.clean, "the reviewer waved it through in this fixture"
    assert composed.checks.no_coverage_promises is False


def test_a_quote_that_is_not_in_the_text_is_a_non_finding(make_deps):
    """A span we cannot locate cannot be removed, so it is ignored and logged as drift."""
    deps = make_deps(
        llm=_review_llm(
            no_emotional_language=False,
            violations=[{"limit": "no_emotional_language", "sentence": "Never written anywhere."}],
        )
    )

    review = llm_review(deps, NEUTRAL, SAFE)

    # The flag still fails (the reviewer said so) but no violation span is recorded.
    assert review.checks.no_emotional_language is False
    assert review.violations == []


def test_a_missing_verdict_is_not_a_pass(make_deps):
    """No judgement means the gate did not run, which is a 503, not a silent approval."""
    deps = make_deps(llm=FakeLLM({"safety": [ScriptedTurn(text="I cannot help with that.")]}))

    with pytest.raises(LLMUnavailable):
        llm_review(deps, NEUTRAL, SAFE)


def test_the_review_call_is_low_effort(make_deps):
    """Research D9 pins the shape: temperature 0, small token ceiling, no images."""
    llm = _review_llm()
    deps = make_deps(llm=llm)

    llm_review(deps, NEUTRAL, SAFE)

    call = llm.calls_for("safety")[0]
    assert call["temperature"] == 0.0
    assert call["max_tokens"] <= 300
    blocks = call["messages"][0]["content"]
    assert all(block.get("type") == "text" for block in blocks)
