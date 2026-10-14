"""US7 - the four input combinations, and views that do not multiply areas."""
from __future__ import annotations

import pytest

from claim_triage.domain.report import TEXT_ONLY_CONFIDENCE_NOTE
from tests.conftest import submit
from tests.contract.conformance import assert_conforms
from tests.fakes import FakeLLM
from tests.fakes.scripts import scenarios

TRIAGE_PATH = "/api/v1/claims/triage"

pytestmark = pytest.mark.integration


def test_image_only_produces_a_complete_report(client, damage_photo):
    """US7 scenario 1."""
    response = submit(client, images=[damage_photo])

    assert response.status_code == 200, response.text
    body = response.json()
    assert_conforms(TRIAGE_PATH, "post", 200, body)
    assert body["triage_assessment"]["damage_description"].strip()


def test_image_plus_text_produces_a_complete_report(client, damage_photo):
    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert response.status_code == 200
    assert response.json()["triage_assessment"]["damage_description"].strip()


def test_text_only_carries_the_exact_limited_confidence_sentence(make_client):
    """US7 scenario 2 / finding A1: checkable, not merely qualitative."""
    client, _ = make_client(llm=FakeLLM(scenarios.text_only()))

    response = submit(
        client, description="A burst supply pipe caused moderate water damage in the kitchen."
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intake_validation"]["is_valid_image"] is None
    assert body["triage_assessment"]["damage_description"].endswith(TEXT_ONLY_CONFIDENCE_NOTE)


def test_a_report_with_a_photo_does_not_carry_the_confidence_note(client, damage_photo):
    response = submit(client, images=[damage_photo], description="Burst pipe")

    assert TEXT_ONLY_CONFIDENCE_NOTE not in response.json()["triage_assessment"]["damage_description"]


def test_image_plus_text_plus_pdf_uses_the_document(make_client, damage_photo, inspection_pdf):
    """US7 scenarios 3 and 5: the inspection widens the scope to the dining room."""
    client, _ = make_client(llm=FakeLLM(scenarios.pdf_widened_scope()))

    response = submit(
        client,
        images=[damage_photo],
        description=(
            "A burst pipe damaged the kitchen. Use the attached same-incident inspection to "
            "determine the full affected scope."
        ),
        document=inspection_pdf,
    )

    assert response.status_code == 200, response.text
    assessment = response.json()["triage_assessment"]
    areas = {a.strip().lower().replace(" ", "_") for a in assessment["affected_areas"]}
    assert {"kitchen", "dining_room"} <= areas
    # water_damage/moderate at 2000-8000 per area, two areas.
    assert assessment["estimated_repair_cost"]["min"] == 4000
    assert assessment["estimated_repair_cost"]["max"] == 16000


def test_the_document_text_reaches_the_agent(make_client, damage_photo, inspection_pdf):
    llm = FakeLLM(scenarios.pdf_widened_scope())
    client, _ = make_client(llm=llm)

    submit(
        client, images=[damage_photo], description="Burst pipe", document=inspection_pdf
    )

    opening = llm.calls_for("triage")[0]["messages"][0]["content"]
    text = " ".join(block.get("text", "") for block in opening)
    assert "inspection" in text.lower()
    assert "does NOT replace" in text, "the quote-vs-table rule must be stated to the agent"


def test_several_views_of_one_room_do_not_multiply_the_areas(make_client, damage_photo):
    """US7 scenario 4: three photographs, one kitchen, one area priced."""
    client, _ = make_client(llm=FakeLLM(scenarios.multi_view_same_room()))

    response = submit(
        client,
        images=[damage_photo, damage_photo, damage_photo],
        description="Burst pipe under the kitchen sink, three views of the same room",
    )

    assert response.status_code == 200, response.text
    assessment = response.json()["triage_assessment"]
    assert assessment["affected_areas"] == ["kitchen"]
    assert assessment["estimated_repair_cost"]["min"] == 2000
    assert assessment["estimated_repair_cost"]["max"] == 8000


def test_multiple_views_are_described_as_one_incident(make_client, damage_photo):
    llm = FakeLLM(scenarios.multi_view_same_room())
    client, _ = make_client(llm=llm)

    submit(client, images=[damage_photo, damage_photo], description="Two views of the kitchen")

    opening = llm.calls_for("triage")[0]["messages"][0]["content"]
    text = " ".join(block.get("text", "") for block in opening)
    assert "SAME incident" in text
    assert len([b for b in opening if b.get("type") == "image"]) == 2


def test_images_are_downscaled_before_upload(client, damage_photo, deps):
    """A budget decision as much as a technical one: input tokens scale with pixels."""
    import base64

    submit(client, images=[damage_photo], description="Burst pipe")

    blocks = deps.llm.calls_for("intake")[0]["messages"][0]["content"]
    image_block = next(b for b in blocks if b.get("type") == "image")
    sent = base64.b64decode(image_block["source"]["data"])
    assert len(sent) < len(damage_photo), "the image should be smaller after downscaling"
    assert image_block["source"]["media_type"] == "image/jpeg"


def test_a_corrupt_image_is_rejected_with_a_reason(client):
    response = submit(client, images=[b"this is not an image"], description="Burst pipe")

    assert response.status_code == 400
    assert "unreadable" in response.json()["message"].lower()
