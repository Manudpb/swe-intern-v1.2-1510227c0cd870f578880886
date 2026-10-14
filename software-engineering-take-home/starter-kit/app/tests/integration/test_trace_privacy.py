"""US5 scenarios 5 and 8 - the trace exposes evidence, not reasoning, and never a credential."""
from __future__ import annotations

import json
import logging

import pytest

from claim_triage.settings import install_credential_scrubber
from claim_triage.trace.recorder import REASON_CONTENT_LIMIT
from tests.conftest import TEST_CREDENTIAL, submit
from tests.fakes import FakeLLM, build_script, cost_turn, search_turn, submit_turn, ScriptedTurn

pytestmark = pytest.mark.integration

#: Phrasing that would indicate chain-of-thought rather than an action-purpose summary.
DELIBERATION_MARKERS = (
    "let me think",
    "first i will",
    "step 1:",
    "on the other hand",
    "alternatively, i could",
    "my reasoning is",
    "wait,",
)


@pytest.fixture
def trace(client, damage_photo):
    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")
    assert response.status_code == 200
    return client.get(f"/api/v1/agent/trace/{response.json()['claim_id']}").json()


def test_reason_content_is_capped(trace):
    for step in trace["steps"]:
        if step["type"] == "reason":
            assert len(step["content"]) <= REASON_CONTENT_LIMIT


def test_a_long_model_monologue_is_truncated_not_published(make_client, damage_photo):
    monologue = "Let me think about this carefully. " * 40
    llm = FakeLLM(
        build_script(
            triage=[
                ScriptedTurn(
                    text=monologue,
                    tool="search_past_claims",
                    tool_input={"query": "burst pipe kitchen"},
                ),
                cost_turn(),
                submit_turn(),
            ]
        )
    )
    client, _ = make_client(llm=llm)

    response = submit(client, images=[damage_photo], description="Burst pipe")
    assert response.status_code == 200
    trace = client.get(f"/api/v1/agent/trace/{response.json()['claim_id']}").json()

    reasons = [s["content"] for s in trace["steps"] if s["type"] == "reason"]
    assert all(len(r) <= REASON_CONTENT_LIMIT for r in reasons)
    assert any(r.endswith("…") for r in reasons), "an over-long purpose line should be truncated"


def test_no_step_reads_as_private_deliberation(trace):
    for step in trace["steps"]:
        lowered = step["content"].lower()
        for marker in DELIBERATION_MARKERS:
            assert marker not in lowered, f"step {step['step_number']} exposes reasoning: {marker!r}"


def test_a_synthesized_purpose_is_used_when_the_model_offers_no_text(make_client, damage_photo):
    """The triple must exist without depending on the model complying (research D4)."""
    llm = FakeLLM(
        build_script(
            triage=[
                ScriptedTurn(text="", tool="search_past_claims", tool_input={"query": "burst pipe"}),
                ScriptedTurn(
                    text="",
                    tool="estimate_repair_cost",
                    tool_input={
                        "damage_type": "water_damage",
                        "severity": "moderate",
                        "affected_areas": ["kitchen"],
                    },
                ),
                submit_turn(),
            ]
        )
    )
    client, _ = make_client(llm=llm)

    response = submit(client, images=[damage_photo], description="Burst pipe")
    assert response.status_code == 200
    trace = client.get(f"/api/v1/agent/trace/{response.json()['claim_id']}").json()

    kinds = [s["type"] for s in trace["steps"]]
    assert any(kinds[i : i + 3] == ["reason", "act", "observe"] for i in range(len(kinds) - 2))
    assert all(s["content"].strip() for s in trace["steps"])


def test_the_credential_appears_in_neither_report_nor_trace(client, damage_photo):
    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")
    report = response.json()
    trace = client.get(f"/api/v1/agent/trace/{report['claim_id']}").json()

    assert TEST_CREDENTIAL not in json.dumps(report)
    assert TEST_CREDENTIAL not in json.dumps(trace)


def test_the_credential_never_reaches_the_model_prompt(client, damage_photo, deps):
    submit(client, images=[damage_photo], description="Burst pipe")

    for call in deps.llm.calls:
        assert TEST_CREDENTIAL not in call["system"]
        assert TEST_CREDENTIAL not in json.dumps(call["messages"])


def test_a_log_record_carrying_the_credential_is_scrubbed(settings, caplog):
    logger = logging.getLogger("claim_triage.test.scrub")
    scrubber = install_credential_scrubber(settings)
    logger.addFilter(scrubber)

    with caplog.at_level(logging.INFO):
        logger.info("configured with key %s", TEST_CREDENTIAL)
        logger.info("inline key " + TEST_CREDENTIAL)

    for record in caplog.records:
        assert TEST_CREDENTIAL not in record.getMessage()
        assert "***" in record.getMessage()
