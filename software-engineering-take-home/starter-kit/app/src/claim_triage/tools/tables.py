"""The company lookup tables.

These are the only sources of money and coverage in the system (FR-015, FR-017). They are
loaded once at startup and never mutated: a model-proposed adjustment has nowhere to land.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class CostTable:
    """cost_matrix[damage_type][severity] -> {min_per_area, max_per_area}"""

    def __init__(self, matrix: dict[str, Any]) -> None:
        self._matrix = matrix

    @classmethod
    def load(cls, tools_dir: Path) -> "CostTable":
        return cls(_read_json(tools_dir / "cost-estimator.json")["cost_matrix"])

    def row(self, damage_type: str, severity: str) -> dict[str, float] | None:
        return self._matrix.get(damage_type, {}).get(severity)


class CoverageTable:
    """policies[policy_type] -> {covered_categories, deductible, max_payout, notes}"""

    def __init__(self, data: dict[str, Any]) -> None:
        self._policies = data["policies"]
        self._excluded = data.get("excluded_everywhere", [])

    @classmethod
    def load(cls, tools_dir: Path) -> "CoverageTable":
        return cls(_read_json(tools_dir / "coverage-table.json"))

    def policy(self, policy_type: str) -> dict[str, Any] | None:
        return self._policies.get(policy_type)

    @property
    def excluded_everywhere(self) -> list[str]:
        return list(self._excluded)
