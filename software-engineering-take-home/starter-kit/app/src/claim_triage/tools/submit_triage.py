"""The terminal action.

Its input schema IS the report schema, minus any cost field. A tool call is the SDK's own
structured-output mechanism: schema-validated by the provider, with no JSON-in-prose to parse
and no markdown fences to strip (research D3).

There is deliberately no cost field. The model cannot propose money; the delivered figure is
copied from the last successful `estimate_repair_cost` observation (invariant I3).
"""
from __future__ import annotations

from typing import Any

from claim_triage.api.schemas import DamageType, Severity, Urgency

NAME = "submit_triage"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "damage_type": {"type": "string", "enum": [d.value for d in DamageType]},
        "severity": {"type": "string", "enum": [s.value for s in Severity]},
        "affected_areas": {"type": "array", "items": {"type": "string"}},
        "damage_description": {"type": "string"},
        "urgency": {"type": "string", "enum": [u.value for u in Urgency]},
        "recommendation": {"type": "string"},
        "similar_past_claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "similarity_score": {"type": "number", "minimum": 0, "maximum": 1},
                    "resolution_summary": {"type": "string"},
                },
                "required": ["claim_id", "similarity_score", "resolution_summary"],
            },
        },
    },
    "required": [
        "damage_type",
        "severity",
        "affected_areas",
        "damage_description",
        "urgency",
        "recommendation",
        "similar_past_claims",
    ],
}

DESCRIPTION = (
    "Submit the finished triage assessment. Call this only after estimating repair cost, and "
    "do not include any cost figure: the cost range comes from the company table."
)


def run(arguments: dict[str, Any], *, priced: bool) -> dict[str, Any]:
    if not priced:
        return {
            "error": "not_priced",
            "message": "Call estimate_repair_cost with the final scope before submitting.",
        }
    missing = [field for field in INPUT_SCHEMA["required"] if not arguments.get(field)]
    if missing:
        return {"error": "incomplete_triage", "message": f"Missing fields: {', '.join(missing)}"}
    return {"accepted": True}
