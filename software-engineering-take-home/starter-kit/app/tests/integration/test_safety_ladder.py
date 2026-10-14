"""US6 scenarios 5 to 7 - rewrite, then sanitize, then refuse.

The ladder is bounded by construction: at most three safety-route calls (review, rewrite,
re-review), then free stages, then 422 (invariant I12).
"""
from __future__ import annotations

import pytest

from tests.conftest import submit
from tests.contract.conformance import assert_conforms
from tests.fakes import FakeLLM
from tests.fakes.scripts import scenarios

TRIAGE_PATH = "/api/v1/claims/triage"

pytestmark = pytest.mark.integration


def test_clean_text_is_delivered_untouched(make_client, damage_photo):
    """US6 scenario 7."""
    llm = FakeLLM(scenarios.clean_triage())
    client, _ = make_client(llm=llm)

    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert response.status_code == 200
    body = response.json()
    assert body["safety_checks"] == {
        "no_coverage_promises": True,
        "no_legal_advice": True,
        "no_settlement_amounts": True,
        "no_liability_determination": True,
        "no_emotional_language": True,
    }
    assert "Assign an adjuster" in body["triage_assessment"]["recommendation"]
    # One safety call on the clean path.
    assert len(llm.calls_for("safety")) == 1


def test_the_rewrite_path_delivers_corrected_text(make_client, damage_photo):
    """US6 scenario 5: the violating sentence is gone and all five flags are true."""
    llm = FakeLLM(scenarios.safety_rewrite_succeeds())
    client, _ = make_client(llm=llm)

    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert response.status_code == 200, response.text
    body = response.json()
    recommendation = body["triage_assessment"]["recommendation"]
    assert "fully covered and will be paid" not in recommendation
    assert "settlement of $12,000" not in recommendation
    assert all(body["safety_checks"].values())
    # review, rewrite, re-review
    assert len(llm.calls_for("safety")) == 3


def test_the_sanitize_path_drops_the_named_sentence(make_client, damage_photo):
    """The rewrite came back still violating, so the quoted span is removed instead."""
    llm = FakeLLM(scenarios.safety_sanitize_path())
    client, _ = make_client(llm=llm)

    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert response.status_code == 200, response.text
    body = response.json()
    recommendation = body["triage_assessment"]["recommendation"]
    assert "fully covered and will be paid" not in recommendation
    assert "Assign an adjuster" in recommendation
    assert all(body["safety_checks"].values())


def test_unsanitizable_text_is_refused_with_422(make_client, damage_photo):
    """US6 scenario 6: removal would empty a required field, so the report is withheld."""
    llm = FakeLLM(scenarios.safety_unsanitizable())
    client, _ = make_client(llm=llm)

    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert response.status_code == 422, response.text
    body = response.json()
    assert_conforms(TRIAGE_PATH, "post", 422, body)
    assert body["error"] == "safety_check_failed"
    assert body["safety_checks"]["no_coverage_promises"] is False
    assert body["message"].strip()


def test_the_ladder_never_exceeds_three_safety_calls(make_client, damage_photo):
    """Invariant I12: bounded attempts, even on the worst path."""
    llm = FakeLLM(scenarios.safety_unsanitizable())
    client, _ = make_client(llm=llm)

    submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert len(llm.calls_for("safety")) <= 3
    assert llm.remaining() == {}, "the worst path should consume exactly the scripted turns"


def test_a_refused_report_is_not_stored(make_client, damage_photo):
    llm = FakeLLM(scenarios.safety_unsanitizable())
    client, deps = make_client(llm=llm)

    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert response.status_code == 422
    assert deps.reports.get("claim-0001") is None
    assert deps.reports.get_trace("claim-0001") is None


def test_the_rewrite_prompt_names_the_broken_limits(make_client, damage_photo):
    llm = FakeLLM(scenarios.safety_rewrite_succeeds())
    client, _ = make_client(llm=llm)

    submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    rewrite_call = llm.calls_for("safety")[1]
    payload = rewrite_call["messages"][0]["content"][0]["text"]
    assert "no_coverage_promises" in payload
    assert "This damage is fully covered and will be paid." in payload
