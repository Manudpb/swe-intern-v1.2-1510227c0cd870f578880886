"""Coverage facts from the company table.

Coverage is not a report field (the contract has none), so this shapes the recommendation's
wording and appears in the trace. It is never stated as a promise or a denial to a claimant.
An unlisted policy or category returns an error rather than a guessed deductible (FR-017).
"""
from __future__ import annotations

from typing import Any

from claim_triage.api.schemas import DamageType, PolicyType
from claim_triage.tools.tables import CoverageTable

NAME = "check_coverage"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "policy_type": {"type": "string", "enum": [p.value for p in PolicyType]},
        "incident_category": {"type": "string", "enum": [d.value for d in DamageType]},
    },
    "required": ["policy_type", "incident_category"],
}

DESCRIPTION = (
    "Look up what a policy covers for an incident category. Use it as context for the "
    "recommendation; never promise or deny coverage to the claimant."
)


def run(table: CoverageTable, arguments: dict[str, Any]) -> dict[str, Any]:
    policy_type = str(arguments.get("policy_type", ""))
    category = str(arguments.get("incident_category", ""))

    policy = table.policy(policy_type)
    if policy is None or category not in [d.value for d in DamageType]:
        return {
            "error": "unknown_coverage_key",
            "message": f"No coverage row for {policy_type!r}/{category!r}",
        }
    return {
        "covered": category in policy["covered_categories"],
        "deductible": policy["deductible"],
        "max_payout": policy["max_payout"],
        "notes": policy["notes"],
    }
