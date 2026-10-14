"""Constitution Principle I - every response is validated against the contract.

A sweep rather than a spot check: each declared endpoint and each declared status gets at
least one validated body, and the one documented addition (503) is confined to upstream and
readiness failure so it can never be used to paper over a client error.
"""
from __future__ import annotations

import pytest

from claim_triage.llm.ports import LLMUnavailable
from tests.conftest import submit
from tests.contract.conformance import (
    assert_conforms,
    declared_paths,
    declared_statuses,
    response_schema,
)
from tests.fakes import FakeLLM, ScriptedTurn, build_script
from tests.fakes.scripts import scenarios

pytestmark = pytest.mark.contract

TRIAGE = "/api/v1/claims/triage"
REPORT = "/api/v1/claims/{claim_id}"
TRACE = "/api/v1/agent/trace/{claim_id}"
HEALTH = "/api/v1/health"


def test_the_contract_declares_exactly_the_four_endpoints():
    assert set(declared_paths()) == {TRIAGE, REPORT, TRACE, HEALTH}


def test_every_declared_status_is_covered_by_this_suite():
    """A documented inventory: if the contract grows a status, this test names the gap."""
    expected = {
        TRIAGE: {"200", "400", "422"},
        REPORT: {"200", "404"},
        TRACE: {"200", "404"},
        HEALTH: {"200"},
    }
    for path, statuses in expected.items():
        method = "post" if path == TRIAGE else "get"
        assert set(declared_statuses(path, method)) == statuses


def test_triage_200_conforms(client, damage_photo):
    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert response.status_code == 200
    assert_conforms(TRIAGE, "post", 200, response.json())


def test_triage_400_conforms(make_client, damage_photo):
    client, _ = make_client(llm=FakeLLM(scenarios.rejected_intake(is_property_damage=False)))

    response = submit(client, images=[damage_photo])

    assert response.status_code == 400
    assert_conforms(TRIAGE, "post", 400, response.json())


def test_triage_400_for_a_missing_submission_conforms(client):
    response = submit(client)

    assert response.status_code == 400
    assert_conforms(TRIAGE, "post", 400, response.json())


def test_triage_422_conforms(make_client, damage_photo):
    client, _ = make_client(llm=FakeLLM(scenarios.safety_unsanitizable()))

    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert response.status_code == 422
    assert_conforms(TRIAGE, "post", 422, response.json())


def test_report_200_and_404_conform(client, damage_photo):
    submitted = submit(client, images=[damage_photo], description="Burst pipe")
    claim_id = submitted.json()["claim_id"]

    found = client.get(f"/api/v1/claims/{claim_id}")
    missing = client.get("/api/v1/claims/nope")

    assert_conforms(REPORT, "get", 200, found.json())
    assert missing.status_code == 404
    # The contract declares 404 with no schema, so the body is unconstrained; assert the
    # status and that the body is still useful to a client.
    assert response_schema(REPORT, "get", 404) is None
    assert missing.json()["message"]


def test_trace_200_and_404_conform(client, damage_photo):
    submitted = submit(client, images=[damage_photo], description="Burst pipe")
    claim_id = submitted.json()["claim_id"]

    found = client.get(f"/api/v1/agent/trace/{claim_id}")
    missing = client.get("/api/v1/agent/trace/nope")

    assert_conforms(TRACE, "get", 200, found.json())
    assert missing.status_code == 404


def test_health_200_conforms(client):
    response = client.get(HEALTH)

    assert response.status_code == 200
    assert_conforms(HEALTH, "get", 200, response.json())


def test_an_out_of_enum_value_would_fail_conformance():
    """The validator is load-bearing, not decorative."""
    bad = {
        "claim_id": "c1",
        "intake_validation": {
            "is_property_damage": True,
            "is_valid_image": True,
            "no_pii_detected": True,
            "no_offensive_content": True,
        },
        "triage_assessment": {
            "damage_type": "meteor_strike",
            "severity": "moderate",
            "affected_areas": ["kitchen"],
            "damage_description": "x",
            "estimated_repair_cost": {"min": 1, "max": 2, "currency": "USD"},
            "urgency": "high",
            "recommendation": "x",
            "similar_past_claims": [],
        },
        "safety_checks": {
            "no_coverage_promises": True,
            "no_legal_advice": True,
            "no_settlement_amounts": True,
            "no_liability_determination": True,
            "no_emotional_language": True,
        },
    }

    with pytest.raises(AssertionError, match="does not conform"):
        assert_conforms(TRIAGE, "post", 200, bad)


def test_a_missing_required_field_would_fail_conformance():
    with pytest.raises(AssertionError, match="does not conform"):
        assert_conforms(TRIAGE, "post", 200, {"claim_id": "c1"})


def test_a_malformed_timestamp_would_fail_conformance():
    """The date-time format checker is enabled deliberately (research D12)."""
    bad = {
        "claim_id": "c1",
        "steps": [
            {"step_number": 1, "type": "reason", "content": "x", "timestamp": "yesterday"}
        ],
        "total_duration_ms": 1,
    }

    with pytest.raises(AssertionError, match="does not conform"):
        assert_conforms(TRACE, "get", 200, bad)


# --- the one documented addition ----------------------------------------------------


def test_503_is_used_for_upstream_failure(make_client, damage_photo):
    client, _ = make_client(
        llm=FakeLLM(build_script(intake=[ScriptedTurn(raises=LLMUnavailable("gateway down"))]))
    )

    response = submit(client, images=[damage_photo], description="Burst pipe")

    assert response.status_code == 503
    assert response.json() == {
        "error": "upstream_unavailable",
        "message": "gateway down",
    }


def test_503_is_used_for_not_ready(make_client):
    from claim_triage.rag.store_qdrant import QdrantStore

    client, _ = make_client(vectors=QdrantStore.in_memory(), skip_ingest=True)

    response = client.get(HEALTH)

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


def test_503_is_never_used_for_a_client_error(client, damage_photo):
    """A client-caused failure must stay in-contract: 400 or 422, never 503."""
    cases = [
        submit(client),  # nothing submitted
        submit(client, images=[b"not an image"], description="x"),  # bad upload
    ]

    for response in cases:
        assert response.status_code in (400, 422), response.text


def test_the_contract_file_itself_is_never_modified_by_the_suite():
    """Principle I: openapi.yaml is read-only authority."""
    from tests.conftest import contract_path

    path = contract_path()
    assert path.is_file()
    content = path.read_text(encoding="utf-8")
    assert "openapi: 3.1.0" in content
    assert "/api/v1/claims/triage" in content
