"""US1 failure paths: a missing submission, and model access that dies."""
from __future__ import annotations

import pytest

from claim_triage.llm.ports import LLMUnavailable
from tests.conftest import submit
from tests.contract.conformance import assert_conforms
from tests.fakes import FakeLLM, ScriptedTurn, build_script

TRIAGE_PATH = "/api/v1/claims/triage"

pytestmark = pytest.mark.integration


def test_submission_without_image_or_description_is_refused(client):
    response = submit(client)

    assert response.status_code == 400
    body = response.json()
    assert_conforms(TRIAGE_PATH, "post", 400, body)
    assert "triage_assessment" not in body
    assert body["message"].strip()


def test_blank_description_counts_as_absent(client):
    response = submit(client, description="   ")

    assert response.status_code == 400
    assert "triage_assessment" not in response.json()


def test_empty_post_is_rejected(client):
    """The published infrastructure check posts no body at all; 400 or 422 is acceptable."""
    response = client.post("/api/v1/claims/triage")

    assert response.status_code in (400, 422)


def test_model_failure_returns_503_with_no_guessed_report(make_client, damage_photo):
    failing = FakeLLM(
        build_script(intake=[ScriptedTurn(raises=LLMUnavailable("gateway unreachable"))])
    )
    client, _ = make_client(llm=failing)

    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert response.status_code == 503
    body = response.json()
    assert body["error"] == "upstream_unavailable"
    assert "triage_assessment" not in body


def test_rate_limit_is_not_retried_and_surfaces_as_503(make_client, damage_photo):
    failing = FakeLLM(
        build_script(
            intake=[ScriptedTurn(raises=LLMUnavailable("allowance exhausted", status=429))]
        )
    )
    client, _ = make_client(llm=failing)

    response = submit(client, images=[damage_photo], description="Burst pipe")

    assert response.status_code == 503
    # One call, no retry: looping on an exhausted allowance is forbidden.
    assert failing.call_count == 1


def test_loop_that_never_prices_does_not_invent_a_cost(make_client, damage_photo):
    """No successful cost call means 503, never a model-authored figure (invariant I3)."""
    from tests.fakes import search_turn, submit_turn

    never_prices = FakeLLM(build_script(triage=[search_turn(), submit_turn()] * 3))
    client, _ = make_client(llm=never_prices)

    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert response.status_code == 503
    assert "estimated_repair_cost" not in response.text
