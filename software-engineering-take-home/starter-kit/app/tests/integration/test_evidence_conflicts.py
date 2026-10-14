"""US7 scenarios 6 and 7 - conflicts are stated, and a bad attachment never fails silently."""
from __future__ import annotations

import pytest

from claim_triage.evidence import pdf
from tests.conftest import submit
from tests.fakes import FakeLLM, build_script, cost_turn, search_turn, submit_turn

pytestmark = pytest.mark.integration


def test_an_unresolved_conflict_is_stated_in_the_narrative(make_client, damage_photo, inspection_pdf):
    """The agent is told to say so; this asserts the narrative survives to the report."""
    conflict = (
        "The attached inspection rates the damage as severe while the photograph supports "
        "moderate; this conflict is unresolved and needs an on-site check."
    )
    llm = FakeLLM(
        build_script(
            triage=[search_turn(), cost_turn(), submit_turn(description=conflict)]
        )
    )
    client, _ = make_client(llm=llm)

    response = submit(
        client, images=[damage_photo], description="Burst pipe", document=inspection_pdf
    )

    assert response.status_code == 200
    assert "unresolved" in response.json()["triage_assessment"]["damage_description"]


def test_the_agent_is_instructed_to_explain_conflicts(make_client, damage_photo, inspection_pdf):
    llm = FakeLLM(build_script())
    client, _ = make_client(llm=llm)

    submit(client, images=[damage_photo], description="Burst pipe", document=inspection_pdf)

    system = llm.calls_for("triage")[0]["system"]
    assert "cannot resolve it" in system


def test_an_unreadable_pdf_is_noted_and_the_report_still_produced(client, damage_photo):
    """US7 scenario 7: based on the remaining evidence, with the attachment flagged."""
    response = submit(
        client, images=[damage_photo], description="Burst pipe", document=b"not a pdf at all"
    )

    assert response.status_code == 200, response.text
    assert response.json()["triage_assessment"]["damage_description"].strip()


def test_the_unreadable_attachment_is_reported_to_the_agent(make_client, damage_photo):
    llm = FakeLLM(build_script())
    client, _ = make_client(llm=llm)

    submit(client, images=[damage_photo], description="Burst pipe", document=b"not a pdf")

    opening = llm.calls_for("triage")[0]["messages"][0]["content"]
    text = " ".join(block.get("text", "") for block in opening)
    assert "could not be read" in text


def test_pdf_extraction_distinguishes_its_failure_modes(inspection_pdf):
    assert pdf.extract(inspection_pdf).status == "ok"
    assert pdf.extract(b"not a pdf").status == "unreadable"
    assert pdf.extract(b"").status == "unreadable"


def test_pdf_text_is_truncated_to_the_configured_limit(inspection_pdf):
    extracted = pdf.extract(inspection_pdf, limit=50)

    assert len(extracted.text) <= 50
    assert extracted.status == "ok"
