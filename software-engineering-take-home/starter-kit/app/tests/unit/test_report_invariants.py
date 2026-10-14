"""Invariants I3 and I4, asserted directly.

These are the reason `domain/report.py` exists: the model's final answer is not the report.
Scope and money are copied out of the recorded trace, and a citation survives only if
retrieval actually returned it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from claim_triage.domain.report import AssessmentUnavailable, TEXT_ONLY_CONFIDENCE_NOTE, assemble
from claim_triage.trace.recorder import TraceRecorder

pytestmark = pytest.mark.unit

SUBMITTED = {
    "damage_type": "water_damage",
    "severity": "moderate",
    "affected_areas": ["kitchen"],
    "damage_description": "Water pooling across the kitchen floor.",
    "urgency": "high",
    "recommendation": "Assign an adjuster to confirm the moisture readings.",
    "similar_past_claims": [
        {
            "claim_id": "CLM-2023-001",
            "similarity_score": 0.89,
            "resolution_summary": "Covered in full.",
        }
    ],
}


@pytest.fixture
def recorder():
    state = {"now": datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)}

    def clock():
        state["now"] += timedelta(milliseconds=10)
        return state["now"]

    rec = TraceRecorder(clock=clock)
    rec.start()
    return rec


def _record_search(recorder, claim_ids=("CLM-2023-001",)):
    recorder.reason("Looking for comparable claims.")
    recorder.act("search_past_claims", {"query": "burst pipe kitchen"})
    recorder.observe(
        {
            "claims": [
                {"claim_id": cid, "similarity_score": 0.9, "resolution_summary": "Covered."}
                for cid in claim_ids
            ]
        }
    )


def _record_cost(recorder, *, damage_type, severity, areas, minimum, maximum):
    recorder.reason("Pricing the assessed scope.")
    recorder.act(
        "estimate_repair_cost",
        {"damage_type": damage_type, "severity": severity, "affected_areas": list(areas)},
    )
    recorder.observe({"min": minimum, "max": maximum, "currency": "USD", "areas_counted": len(areas)})


def test_scope_and_cost_are_copied_from_the_last_cost_call(recorder, knowledge_base):
    _record_search(recorder)
    _record_cost(
        recorder,
        damage_type="water_damage",
        severity="severe",
        areas=["kitchen", "basement"],
        minimum=16000,
        maximum=50000,
    )

    assessment = assemble(
        submitted=SUBMITTED, recorder=recorder, knowledge_base=knowledge_base, had_image=True
    )

    # The model said water_damage/moderate/["kitchen"]; the priced call said otherwise.
    assert assessment.damage_type.value == "water_damage"
    assert assessment.severity.value == "severe"
    assert assessment.affected_areas == ["kitchen", "basement"]
    assert assessment.estimated_repair_cost.min == 16000
    assert assessment.estimated_repair_cost.max == 50000


def test_affected_areas_order_is_preserved_exactly(recorder, knowledge_base):
    """The published checker compares lists, so order is part of the invariant."""
    _record_search(recorder)
    _record_cost(
        recorder,
        damage_type="storm_damage",
        severity="minor",
        areas=["roof", "attic", "hallway"],
        minimum=900,
        maximum=4500,
    )

    assessment = assemble(
        submitted=SUBMITTED, recorder=recorder, knowledge_base=knowledge_base, had_image=True
    )

    assert assessment.affected_areas == ["roof", "attic", "hallway"]


def test_the_last_cost_call_wins_when_the_agent_reprices(recorder, knowledge_base):
    _record_search(recorder)
    _record_cost(
        recorder, damage_type="water_damage", severity="minor", areas=["kitchen"], minimum=500, maximum=2000
    )
    _record_cost(
        recorder,
        damage_type="water_damage",
        severity="moderate",
        areas=["kitchen", "dining_room"],
        minimum=4000,
        maximum=16000,
    )

    assessment = assemble(
        submitted=SUBMITTED, recorder=recorder, knowledge_base=knowledge_base, had_image=True
    )

    assert assessment.severity.value == "moderate"
    assert assessment.affected_areas == ["kitchen", "dining_room"]
    assert assessment.estimated_repair_cost.min == 4000


def test_a_failed_cost_call_is_not_treated_as_pricing(recorder, knowledge_base):
    _record_search(recorder)
    recorder.reason("Pricing with an invalid key.")
    recorder.act("estimate_repair_cost", {"damage_type": "flood", "severity": "moderate", "affected_areas": ["kitchen"]})
    recorder.observe({"error": "unknown_cost_key", "message": "no row"})

    with pytest.raises(AssessmentUnavailable):
        assemble(
            submitted=SUBMITTED, recorder=recorder, knowledge_base=knowledge_base, had_image=True
        )


def test_no_cost_call_at_all_refuses_rather_than_inventing(recorder, knowledge_base):
    _record_search(recorder)

    with pytest.raises(AssessmentUnavailable):
        assemble(
            submitted=SUBMITTED, recorder=recorder, knowledge_base=knowledge_base, had_image=True
        )


def test_uncited_claims_are_dropped(recorder, knowledge_base):
    """Invariant I4: a citation must have been returned by retrieval."""
    _record_search(recorder, claim_ids=("CLM-2023-001",))
    _record_cost(
        recorder, damage_type="water_damage", severity="moderate", areas=["kitchen"], minimum=2000, maximum=8000
    )
    submitted = {
        **SUBMITTED,
        "similar_past_claims": [
            {"claim_id": "CLM-2023-001", "similarity_score": 0.9, "resolution_summary": "Covered."},
            {"claim_id": "CLM-2023-999", "similarity_score": 0.8, "resolution_summary": "Invented."},
            {"claim_id": "CLM-2023-002", "similarity_score": 0.7, "resolution_summary": "Real but not retrieved."},
        ],
    }

    assessment = assemble(
        submitted=submitted, recorder=recorder, knowledge_base=knowledge_base, had_image=True
    )

    assert [c.claim_id for c in assessment.similar_past_claims] == ["CLM-2023-001"]


def test_similarity_scores_are_clamped(recorder, knowledge_base):
    _record_search(recorder)
    _record_cost(
        recorder, damage_type="water_damage", severity="moderate", areas=["kitchen"], minimum=2000, maximum=8000
    )
    submitted = {
        **SUBMITTED,
        "similar_past_claims": [
            {"claim_id": "CLM-2023-001", "similarity_score": 42, "resolution_summary": "Covered."}
        ],
    }

    assessment = assemble(
        submitted=submitted, recorder=recorder, knowledge_base=knowledge_base, had_image=True
    )

    assert assessment.similar_past_claims[0].similarity_score == 1.0


def test_text_only_submission_gains_the_confidence_note(recorder, knowledge_base):
    _record_search(recorder)
    _record_cost(
        recorder, damage_type="water_damage", severity="moderate", areas=["kitchen"], minimum=2000, maximum=8000
    )

    assessment = assemble(
        submitted=SUBMITTED, recorder=recorder, knowledge_base=knowledge_base, had_image=False
    )

    assert assessment.damage_description.endswith(TEXT_ONLY_CONFIDENCE_NOTE)


def test_out_of_enum_urgency_is_derived_instead(recorder, knowledge_base):
    _record_search(recorder)
    _record_cost(
        recorder, damage_type="water_damage", severity="severe", areas=["kitchen"], minimum=8000, maximum=25000
    )

    assessment = assemble(
        submitted={**SUBMITTED, "urgency": "extremely urgent"},
        recorder=recorder,
        knowledge_base=knowledge_base,
        had_image=True,
    )

    assert assessment.urgency.value in {"low", "medium", "high", "critical"}
    assert assessment.urgency.value == "high"
