"""US4 scenarios 5 to 7 / FR-017, FR-003 - coverage comes from the table, or not at all."""
from __future__ import annotations

import pytest

from claim_triage.tools import check_coverage
from tests.conftest import submit

pytestmark = pytest.mark.unit


def test_basic_homeowner_does_not_cover_water_damage(coverage_table):
    result = check_coverage.run(
        coverage_table, {"policy_type": "basic_homeowner", "incident_category": "water_damage"}
    )

    assert result["covered"] is False
    assert result["deductible"] == 2500
    assert result["max_payout"] == 100000
    assert "water damage" in result["notes"].lower()


def test_standard_homeowner_covers_water_damage(coverage_table):
    result = check_coverage.run(
        coverage_table, {"policy_type": "standard_homeowner", "incident_category": "water_damage"}
    )

    assert result["covered"] is True
    assert result["deductible"] == 1500


@pytest.mark.parametrize(
    "policy_type,category",
    [("platinum_homeowner", "water_damage"), ("standard_homeowner", "flood"), ("", "")],
)
def test_unlisted_key_returns_an_error_not_a_guessed_deductible(
    coverage_table, policy_type, category
):
    result = check_coverage.run(
        coverage_table, {"policy_type": policy_type, "incident_category": category}
    )

    assert result["error"] == "unknown_coverage_key"
    assert "deductible" not in result


def test_absent_policy_type_defaults_to_standard_homeowner(client, damage_photo):
    """FR-003 and US4 scenario 7: the default is used, and the trace records it."""
    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")
    assert response.status_code == 200

    trace = client.get(f"/api/v1/agent/trace/{response.json()['claim_id']}").json()
    coverage_calls = [
        step
        for step in trace["steps"]
        if step["type"] == "act" and step["tool_name"] == "check_coverage"
    ]
    assert coverage_calls, "the loop should have consulted coverage"
    assert coverage_calls[0]["tool_input"]["policy_type"] == "standard_homeowner"


def test_unrecognised_policy_type_falls_back_to_the_default(client, damage_photo):
    response = submit(
        client, images=[damage_photo], description="Burst pipe", policy_type="gold_plated"
    )

    assert response.status_code == 200
