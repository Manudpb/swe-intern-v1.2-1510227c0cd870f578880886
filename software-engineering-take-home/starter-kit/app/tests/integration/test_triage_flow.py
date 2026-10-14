"""US1 - a submission becomes a decision-ready report."""
from __future__ import annotations

import pytest

from tests.conftest import submit
from tests.contract.conformance import assert_conforms

TRIAGE_PATH = "/api/v1/claims/triage"
REPORT_PATH = "/api/v1/claims/{claim_id}"

pytestmark = pytest.mark.integration


def test_photo_and_description_produce_a_complete_report(client, damage_photo):
    response = submit(
        client,
        images=[damage_photo],
        description="Burst pipe under kitchen sink, water pooling on floor",
        policy_type="standard_homeowner",
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert_conforms(TRIAGE_PATH, "post", 200, body)

    assert set(body) == {"claim_id", "intake_validation", "triage_assessment", "safety_checks"}
    assessment = body["triage_assessment"]
    assert assessment["damage_type"] == "water_damage"
    assert assessment["severity"] in {"minor", "moderate", "severe", "catastrophic"}
    assert assessment["affected_areas"]
    assert assessment["urgency"] in {"low", "medium", "high", "critical"}
    assert assessment["recommendation"].strip()
    cost = assessment["estimated_repair_cost"]
    assert cost["min"] <= cost["max"]
    assert cost["currency"] == "USD"


def test_all_four_intake_checks_pass_for_a_valid_submission(client, damage_photo):
    """US2 scenario 7: a valid photo plus description is not rejected."""
    response = submit(client, images=[damage_photo], description="Kitchen flooded by a burst pipe")

    assert response.status_code == 200
    validation = response.json()["intake_validation"]
    assert validation == {
        "is_property_damage": True,
        "is_valid_image": True,
        "no_pii_detected": True,
        "no_offensive_content": True,
    }


def test_report_is_retrievable_and_unchanged(client, damage_photo):
    submitted = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")
    assert submitted.status_code == 200
    body = submitted.json()

    fetched = client.get(f"/api/v1/claims/{body['claim_id']}")

    assert fetched.status_code == 200
    assert fetched.json() == body
    assert_conforms(REPORT_PATH, "get", 200, fetched.json())


def test_unknown_report_id_is_not_found(client):
    response = client.get("/api/v1/claims/claim-does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"
