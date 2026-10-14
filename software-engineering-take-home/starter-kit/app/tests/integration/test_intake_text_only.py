"""US2 scenario 6 / FR-006 - text-only input is not rejected for lacking a photo."""
from __future__ import annotations

import pytest

from tests.conftest import submit
from tests.contract.conformance import assert_conforms
from tests.fakes import FakeLLM
from tests.fakes.scripts.scenarios import text_only

pytestmark = pytest.mark.integration


def test_text_only_submission_is_triaged_with_null_image_check(make_client):
    client, _ = make_client(llm=FakeLLM(text_only()))

    response = submit(
        client,
        description=(
            "A burst supply pipe caused moderate water damage in the kitchen only. "
            "No photo is available."
        ),
        policy_type="standard_homeowner",
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert_conforms("/api/v1/claims/triage", "post", 200, body)

    validation = body["intake_validation"]
    assert validation["is_valid_image"] is None, "absent visual check must be null, not a pass"
    assert validation["is_property_damage"] is True
    assert validation["no_pii_detected"] is True
    assert validation["no_offensive_content"] is True
    assert body["triage_assessment"]["damage_description"].strip()


def test_intake_is_not_asked_about_image_quality_without_an_image(make_client):
    llm = FakeLLM(text_only())
    client, _ = make_client(llm=llm)

    submit(client, description="A burst supply pipe damaged the kitchen.")

    intake_call = llm.calls_for("intake")[0]
    blocks = intake_call["messages"][0]["content"]
    assert all(block.get("type") != "image" for block in blocks)
    text = " ".join(b.get("text", "") for b in blocks)
    assert "No photograph was submitted" in text
