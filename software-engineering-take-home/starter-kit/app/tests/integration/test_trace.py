"""US5 - every report has an auditable trace.

These assertions mirror what a reviewer (and the published trace check) actually verifies:
structure, pairing, and agreement between what the tools observed and what the report says.
"""
from __future__ import annotations

import pytest

from tests.conftest import submit
from tests.contract.conformance import assert_conforms

TRACE_PATH = "/api/v1/agent/trace/{claim_id}"

pytestmark = pytest.mark.integration


@pytest.fixture
def report_and_trace(client, damage_photo):
    response = submit(
        client,
        images=[damage_photo],
        description="Burst pipe under kitchen sink, water pooling on floor",
        policy_type="standard_homeowner",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    trace = client.get(f"/api/v1/agent/trace/{body['claim_id']}")
    assert trace.status_code == 200
    return body, trace.json()


def test_trace_is_returned_for_the_claim(report_and_trace):
    report, trace = report_and_trace

    assert_conforms(TRACE_PATH, "get", 200, trace)
    assert trace["claim_id"] == report["claim_id"]
    assert isinstance(trace["steps"], list) and trace["steps"]
    assert isinstance(trace["total_duration_ms"], int)
    assert trace["total_duration_ms"] >= 0


def test_step_numbers_increase_by_exactly_one(report_and_trace):
    _, trace = report_and_trace

    numbers = [step["step_number"] for step in trace["steps"]]
    assert numbers == list(range(1, len(numbers) + 1))


def test_every_step_is_a_known_kind_with_content(report_and_trace):
    _, trace = report_and_trace

    for step in trace["steps"]:
        assert step["type"] in {"reason", "act", "observe"}
        assert isinstance(step["content"], str) and step["content"].strip()


def test_each_action_is_followed_by_its_observation(report_and_trace):
    """Invariant I7: no unobserved action and no orphaned observation."""
    _, trace = report_and_trace
    steps = trace["steps"]

    pending = None
    for index, step in enumerate(steps):
        if step["type"] == "act":
            assert pending is None, f"action at {index} began before the previous was observed"
            pending = step
            assert steps[index + 1]["type"] == "observe", "an act must be followed by its observe"
        elif step["type"] == "observe":
            assert pending is not None, f"observation at {index} has no action"
            pending = None
    assert pending is None, "the last action has no observation"


def test_two_of_each_kind_and_a_reason_act_observe_triple(report_and_trace):
    """Invariants I8: the structure a reviewer looks for to see a loop, not a single shot."""
    _, trace = report_and_trace
    kinds = [step["type"] for step in trace["steps"]]

    for kind in ("reason", "act", "observe"):
        assert kinds.count(kind) >= 2, f"expected at least two {kind} events, got {kinds.count(kind)}"
    assert any(
        kinds[i : i + 3] == ["reason", "act", "observe"] for i in range(len(kinds) - 2)
    ), "no consecutive reason-act-observe cycle found"


def test_act_steps_carry_a_tool_name_and_substantive_inputs(report_and_trace):
    _, trace = report_and_trace
    acts = [step for step in trace["steps"] if step["type"] == "act"]

    assert len({step["tool_name"] for step in acts}) >= 2, "expected at least two distinct tools"
    for step in acts:
        assert isinstance(step["tool_name"], str) and step["tool_name"].strip()
        assert isinstance(step["tool_input"], dict) and step["tool_input"]
        assert "tool_output" not in step or step["tool_output"] is None


def test_observe_steps_carry_the_real_returned_value(report_and_trace):
    _, trace = report_and_trace
    observes = [step for step in trace["steps"] if step["type"] == "observe"]

    for step in observes:
        assert isinstance(step["tool_output"], (dict, list)) and step["tool_output"]
        assert "tool_name" not in step or step["tool_name"] is None


def test_successful_cost_and_retrieval_evidence_both_exist(report_and_trace):
    """Invariant I9."""
    _, trace = report_and_trace
    tools = {step["tool_name"] for step in trace["steps"] if step["type"] == "act"}

    assert "estimate_repair_cost" in tools
    assert "search_past_claims" in tools


def test_the_cost_observation_matches_the_report(report_and_trace):
    """US5 scenario 4 / invariant I3 seen from the outside."""
    report, trace = report_and_trace
    reported = report["triage_assessment"]["estimated_repair_cost"]

    observed = None
    pending = None
    for step in trace["steps"]:
        if step["type"] == "act":
            pending = step["tool_name"]
        elif step["type"] == "observe" and pending == "estimate_repair_cost":
            if not step["tool_output"].get("error"):
                observed = step["tool_output"]
            pending = None

    assert observed is not None
    assert reported["min"] == observed["min"]
    assert reported["max"] == observed["max"]


def test_the_priced_scope_equals_the_reported_scope(report_and_trace):
    """What the published trace check compares field by field, including list order."""
    report, trace = report_and_trace
    assessment = report["triage_assessment"]

    cost_args = None
    for step in trace["steps"]:
        if step["type"] == "act" and step["tool_name"] == "estimate_repair_cost":
            cost_args = step["tool_input"]

    assert cost_args is not None
    assert cost_args["damage_type"] == assessment["damage_type"]
    assert cost_args["severity"] == assessment["severity"]
    assert cost_args["affected_areas"] == assessment["affected_areas"]


def test_cited_claims_were_actually_retrieved(report_and_trace):
    """Invariant I4 seen from the outside."""
    report, trace = report_and_trace

    retrieved: set[str] = set()
    pending = None
    for step in trace["steps"]:
        if step["type"] == "act":
            pending = step["tool_name"]
        elif step["type"] == "observe" and pending == "search_past_claims":
            for record in step["tool_output"].get("claims", []):
                retrieved.add(record["claim_id"])
            pending = None

    cited = {c["claim_id"] for c in report["triage_assessment"]["similar_past_claims"]}
    assert cited
    assert cited <= retrieved


def test_unknown_trace_id_is_not_found(client):
    response = client.get("/api/v1/agent/trace/claim-never-issued")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_timestamps_are_rfc3339_and_non_decreasing(report_and_trace):
    from datetime import datetime

    _, trace = report_and_trace
    stamps = [datetime.fromisoformat(s["timestamp"].replace("Z", "+00:00")) for s in trace["steps"]]

    assert stamps == sorted(stamps)
