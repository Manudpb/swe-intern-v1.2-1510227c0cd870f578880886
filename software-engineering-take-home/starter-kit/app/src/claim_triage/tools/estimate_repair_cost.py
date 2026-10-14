"""The only source of money in the system.

`min = min_per_area x n`, `max = max_per_area x n`, with `n = max(1, distinct(areas))` and the
per-area figures read from `tools/cost-estimator.json`. The model cannot set, adjust or
override the figure, and neither can a contractor's quote (FR-015, FR-016).

An unknown key returns an error object rather than a fallback number: a recorded tool failure
is honest, an invented range is not.
"""
from __future__ import annotations

from typing import Any

from claim_triage.api.schemas import DamageType, Severity
from claim_triage.domain.areas import distinct_count
from claim_triage.tools.tables import CostTable

NAME = "estimate_repair_cost"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "damage_type": {"type": "string", "enum": [d.value for d in DamageType]},
        "severity": {"type": "string", "enum": [s.value for s in Severity]},
        "affected_areas": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Distinct rooms or exterior components, each counted once.",
        },
    },
    "required": ["damage_type", "severity", "affected_areas"],
}

DESCRIPTION = (
    "Estimate repair cost from the company cost table. Pass the distinct affected areas: "
    "a room and its own floor or wall are one area, not two."
)


def run(table: CostTable, arguments: dict[str, Any]) -> dict[str, Any]:
    damage_type = arguments.get("damage_type")
    severity = arguments.get("severity")
    areas = arguments.get("affected_areas") or []

    row = table.row(str(damage_type), str(severity))
    if not row:
        return {
            "error": "unknown_cost_key",
            "message": f"No cost table row for {damage_type!r}/{severity!r}",
        }
    if not isinstance(areas, list) or any(not str(a).strip() for a in areas):
        return {"error": "invalid_areas", "message": "affected_areas must be non-empty strings"}

    count = distinct_count([str(a) for a in areas])
    return {
        "min": row["min_per_area"] * count,
        "max": row["max_per_area"] * count,
        "currency": "USD",
        "areas_counted": count,
    }
