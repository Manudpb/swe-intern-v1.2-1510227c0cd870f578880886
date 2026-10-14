"""US4 / FR-015 to FR-018 - every dollar figure is table arithmetic."""
from __future__ import annotations

import pytest

from claim_triage.domain.areas import normalize_areas
from claim_triage.tools import estimate_repair_cost as cost

pytestmark = pytest.mark.unit


def test_two_areas_multiply_the_per_area_range(cost_table):
    result = cost.run(
        cost_table,
        {
            "damage_type": "water_damage",
            "severity": "moderate",
            "affected_areas": ["kitchen", "dining_room"],
        },
    )

    # water_damage/moderate is 2000-8000 per area; two distinct areas doubles it.
    assert result["min"] == 4000
    assert result["max"] == 16000
    assert result["currency"] == "USD"
    assert result["areas_counted"] == 2


def test_one_area_is_the_per_area_range(cost_table):
    result = cost.run(
        cost_table,
        {"damage_type": "water_damage", "severity": "moderate", "affected_areas": ["kitchen"]},
    )

    assert (result["min"], result["max"]) == (2000, 8000)


def test_empty_area_list_uses_a_multiplier_of_one(cost_table):
    """FR-016: never a zero-width range at zero."""
    result = cost.run(
        cost_table, {"damage_type": "fire_damage", "severity": "severe", "affected_areas": []}
    )

    assert result["areas_counted"] == 1
    assert (result["min"], result["max"]) == (20000, 75000)


@pytest.mark.parametrize(
    "damage_type,severity",
    [("water_damage", "apocalyptic"), ("flood", "moderate"), ("", ""), ("other", None)],
)
def test_unknown_key_returns_an_error_not_a_guess(cost_table, damage_type, severity):
    result = cost.run(
        cost_table,
        {"damage_type": damage_type, "severity": severity, "affected_areas": ["kitchen"]},
    )

    assert result["error"] == "unknown_cost_key"
    assert "min" not in result


def test_every_table_row_is_internally_consistent(cost_table):
    from claim_triage.api.schemas import DamageType, Severity

    for damage in DamageType:
        for severity in Severity:
            row = cost_table.row(damage.value, severity.value)
            assert row, f"missing cost row for {damage.value}/{severity.value}"
            assert 0 < row["min_per_area"] <= row["max_per_area"]


def test_normalized_areas_price_once(cost_table):
    """The end-to-end guarantee: collapse first, then price."""
    areas = normalize_areas(["kitchen", "kitchen floor", "interior"])
    result = cost.run(
        cost_table,
        {"damage_type": "water_damage", "severity": "moderate", "affected_areas": areas},
    )

    assert result["areas_counted"] == 1
    assert (result["min"], result["max"]) == (2000, 8000)
