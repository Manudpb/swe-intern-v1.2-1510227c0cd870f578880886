"""US2 - unsuitable submissions are refused with the failing check named."""
from __future__ import annotations

import pytest

from tests.conftest import submit
from tests.contract.conformance import assert_conforms
from tests.fakes import FakeLLM
from tests.fakes.scripts.scenarios import rejected_intake

TRIAGE_PATH = "/api/v1/claims/triage"

pytestmark = pytest.mark.integration

CASES = [
    ("not property damage", {"is_property_damage": False}, "is_property_damage"),
    ("unusable image", {"is_valid_image": False}, "is_valid_image"),
    ("payment card", {"no_pii_detected": False}, "no_pii_detected"),
    ("offensive content", {"no_offensive_content": False}, "no_offensive_content"),
]


@pytest.mark.parametrize("label,flags,decisive", CASES, ids=[c[0] for c in CASES])
def test_unsuitable_submission_is_rejected(make_client, damage_photo, label, flags, decisive):
    client, _ = make_client(llm=FakeLLM(rejected_intake(**flags)))

    response = submit(client, images=[damage_photo])

    assert response.status_code == 400, response.text
    body = response.json()
    assert_conforms(TRIAGE_PATH, "post", 400, body)
    assert body["intake_validation"][decisive] is False
    assert isinstance(body["message"], str) and body["message"].strip()
    assert not body.get("triage_assessment"), "a rejected input must not proceed to triage"


def test_rejection_costs_exactly_one_model_call(make_client, damage_photo):
    """Intake runs before the loop, so a rejection never pays for tool rounds."""
    llm = FakeLLM(rejected_intake(is_property_damage=False))
    client, _ = make_client(llm=llm)

    response = submit(client, images=[damage_photo])

    assert response.status_code == 400
    assert llm.call_count == 1
    assert llm.calls[0]["route"] == "intake"


def test_rejected_submission_leaves_no_trace_of_tool_activity(make_client, damage_photo):
    llm = FakeLLM(rejected_intake(is_property_damage=False))
    client, deps = make_client(llm=llm)

    submit(client, images=[damage_photo])

    assert deps.reports.get_trace("claim-0001") is None
    assert llm.calls_for("triage") == []
    assert llm.calls_for("safety") == []


def test_rejection_message_names_the_problem(make_client, damage_photo):
    client, _ = make_client(llm=FakeLLM(rejected_intake(no_pii_detected=False)))

    response = submit(client, images=[damage_photo])

    assert "personal information" in response.json()["message"].lower()
