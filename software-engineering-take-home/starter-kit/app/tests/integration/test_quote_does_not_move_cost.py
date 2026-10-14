"""US4 scenario 3 / FR-015 - a contractor's quote never becomes the reported figure.

The quote PDF in the fixtures carries real numbers. The report must still show the table's
range, because the model has no path to a dollar amount at all: the cost comes from the
recorded tool observation (invariant I3).
"""
from __future__ import annotations

import pytest

from claim_triage.evidence import pdf
from tests.conftest import submit
from tests.fakes import FakeLLM, build_script, cost_turn, search_turn, submit_turn

pytestmark = pytest.mark.integration


def test_the_reported_range_is_the_table_figure_not_the_quote(
    make_client, damage_photo, quote_pdf
):
    client, _ = make_client(llm=FakeLLM(build_script()))

    response = submit(
        client,
        images=[damage_photo],
        description="Burst pipe in the kitchen; contractor estimate attached",
        document=quote_pdf,
    )

    assert response.status_code == 200, response.text
    cost = response.json()["triage_assessment"]["estimated_repair_cost"]
    # water_damage/moderate, one area.
    assert (cost["min"], cost["max"]) == (2000, 8000)


def test_a_model_proposed_cost_field_is_ignored_entirely(make_client, damage_photo):
    """`submit_triage` has no cost field, so a smuggled one cannot reach the report."""
    smuggled = submit_turn()
    smuggled.tool_input["estimated_repair_cost"] = {"min": 99999, "max": 123456, "currency": "USD"}
    client, _ = make_client(
        llm=FakeLLM(build_script(triage=[search_turn(), cost_turn(), smuggled]))
    )

    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert response.status_code == 200
    cost = response.json()["triage_assessment"]["estimated_repair_cost"]
    assert (cost["min"], cost["max"]) == (2000, 8000)


def test_the_quote_numbers_appear_nowhere_in_the_cost_range(make_client, damage_photo, quote_pdf):
    extracted = pdf.extract(quote_pdf)
    assert extracted.usable, "the fixture quote should contain extractable text"

    client, _ = make_client(llm=FakeLLM(build_script()))
    response = submit(
        client, images=[damage_photo], description="Burst pipe", document=quote_pdf
    )

    cost = response.json()["triage_assessment"]["estimated_repair_cost"]
    assert cost["min"] == 2000 and cost["max"] == 8000


def test_the_agent_is_told_the_table_is_the_only_source_of_money(make_client, damage_photo):
    llm = FakeLLM(build_script())
    client, _ = make_client(llm=llm)

    submit(client, images=[damage_photo], description="Burst pipe")

    system = llm.calls_for("triage")[0]["system"]
    assert "only source of a cost figure" in system
    assert "never take one from a contractor" in system
