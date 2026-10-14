"""Report assembly: where the model stops being trusted.

Two invariants live here, and they are the reason this module exists rather than letting the
agent's final answer become the report:

**I3 — scope and money come from the trace, not the model.** The delivered `damage_type`,
`severity` and `affected_areas` are copied verbatim (and in order) from the arguments of the
last successful `estimate_repair_cost` call, and the cost range is copied from that call's
output. No successful cost call means the request fails rather than returning a
model-authored number.

**I4 — citations are earned.** A cited claim id survives only if retrieval actually returned
it. Others are dropped, never renamed or invented.

Enforcing both in one place turns three separate spec requirements (FR-015, FR-012, FR-024)
into a unit test instead of a hope about prompt obedience.
"""
from __future__ import annotations

import logging
from typing import Any

from claim_triage.api.schemas import (
    CostRange,
    DamageType,
    Severity,
    SimilarClaimRef,
    TriageAssessment,
    Urgency,
)
from claim_triage.trace.recorder import TraceRecorder

log = logging.getLogger(__name__)

TEXT_ONLY_CONFIDENCE_NOTE = (
    "No photographic evidence was provided; this assessment is based on the written "
    "description alone and carries lower confidence."
)

#: Damage types where an unresolved hazard keeps spreading while the adjuster waits.
_ONGOING_RISK = {DamageType.water_damage, DamageType.fire_damage, DamageType.storm_damage}


class AssessmentUnavailable(RuntimeError):
    """The loop produced no priced assessment. Surfaced as 503, never as a guessed report."""


def assemble(
    *,
    submitted: dict[str, Any],
    recorder: TraceRecorder,
    knowledge_base: dict[str, dict[str, Any]],
    had_image: bool,
) -> TriageAssessment:
    """Build the delivered assessment from the model's answer and the recorded trace."""
    priced = recorder.successful_tool_calls("estimate_repair_cost")
    if not priced:
        raise AssessmentUnavailable(
            "No successful cost estimate was recorded; refusing to report a cost the "
            "company table did not produce."
        )
    cost_args, cost_output = priced[-1]

    # --- I3: scope and money from the trace -------------------------------------------
    damage_type = cost_args["damage_type"]
    severity = cost_args["severity"]
    affected_areas = list(cost_args["affected_areas"])

    for field, trace_value in (
        ("damage_type", damage_type),
        ("severity", severity),
        ("affected_areas", affected_areas),
    ):
        proposed = submitted.get(field)
        if proposed is not None and proposed != trace_value:
            log.warning(
                "Model drift on %s: submitted %r, delivering the priced value %r",
                field,
                proposed,
                trace_value,
            )

    # --- I4: citations earned by retrieval --------------------------------------------
    retrieved = recorder.retrieved_claim_ids()
    citations: list[SimilarClaimRef] = []
    for raw in submitted.get("similar_past_claims") or []:
        if not isinstance(raw, dict):
            continue
        claim_id = raw.get("claim_id")
        if claim_id not in retrieved or claim_id not in knowledge_base:
            log.warning("Dropping citation %r: absent from successful retrievals", claim_id)
            continue
        citations.append(
            SimilarClaimRef(
                claim_id=str(claim_id),
                similarity_score=_clamp(raw.get("similarity_score")),
                resolution_summary=str(raw.get("resolution_summary") or "").strip()
                or "Resolution details unavailable.",
            )
        )

    description = str(submitted.get("damage_description") or "").strip()
    if not had_image and TEXT_ONLY_CONFIDENCE_NOTE not in description:
        description = f"{description} {TEXT_ONLY_CONFIDENCE_NOTE}".strip()

    return TriageAssessment(
        damage_type=DamageType(damage_type),
        severity=Severity(severity),
        affected_areas=affected_areas,
        damage_description=description or "Damage assessed from the submitted evidence.",
        estimated_repair_cost=CostRange(
            min=float(cost_output["min"]),
            max=float(cost_output["max"]),
            currency=str(cost_output.get("currency", "USD")),
        ),
        urgency=_urgency(
            submitted.get("urgency"), DamageType(damage_type), Severity(severity), description
        ),
        recommendation=str(submitted.get("recommendation") or "").strip()
        or "Assign an adjuster to inspect the property and confirm the assessed scope.",
        similar_past_claims=citations,
    )


def _clamp(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _urgency(proposed: Any, damage_type: DamageType, severity: Severity, text: str) -> Urgency:
    """Urgency is a judgement field: no table is supplied for it (spec.md Assumptions).

    The model's value is accepted when it is valid, and otherwise derived from severity,
    damage type and ongoing-risk cues in the evidence.
    """
    if isinstance(proposed, str):
        try:
            return Urgency(proposed)
        except ValueError:
            log.warning("Model proposed an out-of-enum urgency %r; deriving instead", proposed)

    base = {
        Severity.minor: Urgency.low,
        Severity.moderate: Urgency.medium,
        Severity.severe: Urgency.high,
        Severity.catastrophic: Urgency.critical,
    }[severity]

    lowered = text.lower()
    ongoing = damage_type in _ONGOING_RISK and any(
        cue in lowered
        for cue in ("active", "ongoing", "still", "spreading", "standing water", "structural", "unsafe")
    )
    if ongoing:
        escalated = {
            Urgency.low: Urgency.medium,
            Urgency.medium: Urgency.high,
            Urgency.high: Urgency.critical,
            Urgency.critical: Urgency.critical,
        }
        return escalated[base]
    return base
