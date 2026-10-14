"""Test doubles, and the script builder every integration test uses.

`build_script` exists so that adding a mandatory model call to the pipeline is a one-line
change here instead of an edit to every test (finding G2). The safety review runs on every
triage, so a clean safety verdict is appended by default (research D9).
"""
from __future__ import annotations

from typing import Any

from tests.fakes.fake_embedder import FakeEmbedder
from tests.fakes.fake_llm import FakeLLM, FakeLLMContractError, ScriptedTurn

CLEAN_INTAKE = {
    "is_property_damage": True,
    "is_valid_image": True,
    "no_pii_detected": True,
    "no_offensive_content": True,
    "reason": "Clear photograph of interior water damage; no personal information visible.",
}

CLEAN_VERDICT = {
    "no_coverage_promises": True,
    "no_legal_advice": True,
    "no_settlement_amounts": True,
    "no_liability_determination": True,
    "no_emotional_language": True,
    "violations": [],
}


def intake_turn(**overrides: Any) -> ScriptedTurn:
    payload = {**CLEAN_INTAKE, **overrides}
    return ScriptedTurn(
        text="", tool="report_intake_validation", tool_input=payload, stop_reason="tool_use"
    )


def safety_turn(**overrides: Any) -> ScriptedTurn:
    payload = {**CLEAN_VERDICT, **overrides}
    return ScriptedTurn(tool="report_safety_verdict", tool_input=payload)


def rewrite_turn(damage_description: str, recommendation: str) -> ScriptedTurn:
    return ScriptedTurn(
        tool="submit_rewritten_text",
        tool_input={
            "damage_description": damage_description,
            "recommendation": recommendation,
        },
    )


def search_turn(query: str = "burst pipe flooded kitchen floor water damage") -> ScriptedTurn:
    return ScriptedTurn(
        text="Searching the archive for comparable burst-pipe claims to anchor severity.",
        tool="search_past_claims",
        tool_input={"query": query, "top_k": 5},
    )


def cost_turn(
    damage_type: str = "water_damage",
    severity: str = "moderate",
    areas: list[str] | None = None,
) -> ScriptedTurn:
    return ScriptedTurn(
        text="Pricing the assessed scope against the company cost table.",
        tool="estimate_repair_cost",
        tool_input={
            "damage_type": damage_type,
            "severity": severity,
            "affected_areas": areas if areas is not None else ["kitchen"],
        },
    )


def coverage_turn(policy_type: str = "standard_homeowner", category: str = "water_damage") -> ScriptedTurn:
    return ScriptedTurn(
        text="Checking policy coverage to frame the recommendation.",
        tool="check_coverage",
        tool_input={"policy_type": policy_type, "incident_category": category},
    )


def submit_turn(
    damage_type: str = "water_damage",
    severity: str = "moderate",
    areas: list[str] | None = None,
    description: str = "Water pooling across the kitchen floor from a failed supply line under the sink.",
    recommendation: str = "Assign an adjuster to verify the moisture readings and confirm the assessed scope.",
    urgency: str = "high",
    claims: list[dict[str, Any]] | None = None,
) -> ScriptedTurn:
    return ScriptedTurn(
        text="Submitting the completed assessment for the adjuster.",
        tool="submit_triage",
        tool_input={
            "damage_type": damage_type,
            "severity": severity,
            "affected_areas": areas if areas is not None else ["kitchen"],
            "damage_description": description,
            "urgency": urgency,
            "recommendation": recommendation,
            "similar_past_claims": claims
            if claims is not None
            else [
                {
                    "claim_id": "CLM-2023-001",
                    "similarity_score": 0.89,
                    "resolution_summary": "Resolved as covered full after a burst supply line.",
                }
            ],
        },
    )


def build_script(
    *,
    intake: list[ScriptedTurn] | None = None,
    triage: list[ScriptedTurn] | None = None,
    safety: list[ScriptedTurn] | None = None,
) -> dict[str, list[ScriptedTurn]]:
    """A complete, valid script. Each route can be overridden independently.

    The default `safety` is one clean verdict, because the gate runs on every triage.
    """
    return {
        "intake": intake if intake is not None else [intake_turn()],
        "triage": triage
        if triage is not None
        else [search_turn(), cost_turn(), coverage_turn(), submit_turn()],
        "safety": safety if safety is not None else [safety_turn()],
    }


def fake_llm(**overrides: Any) -> FakeLLM:
    return FakeLLM(build_script(**overrides))


__all__ = [
    "CLEAN_INTAKE",
    "CLEAN_VERDICT",
    "FakeEmbedder",
    "FakeLLM",
    "FakeLLMContractError",
    "ScriptedTurn",
    "build_script",
    "cost_turn",
    "coverage_turn",
    "fake_llm",
    "intake_turn",
    "rewrite_turn",
    "safety_turn",
    "search_turn",
    "submit_turn",
]
