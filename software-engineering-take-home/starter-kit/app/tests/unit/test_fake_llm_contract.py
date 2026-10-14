"""The suite's own safety net, verified.

`FakeLLM` is what stands in for a paid integration test: it rejects request shapes the real
Messages API refuses. If these rules silently stopped firing, the free suite would go on
passing while the real request was malformed — the exact failure this design exists to catch.
"""
from __future__ import annotations

import pytest

from tests.fakes import FakeLLM, ScriptedTurn, build_script
from tests.fakes.fake_llm import FakeLLMContractError

pytestmark = pytest.mark.unit

SYSTEM = "[route:triage]\nYou are the triage agent."
TOOLS = [{"name": "t", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
MESSAGES = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]


def _llm() -> FakeLLM:
    return FakeLLM({"triage": [ScriptedTurn(text="ok")] * 5})


def _call(llm: FakeLLM, **overrides):
    kwargs = {"system": SYSTEM, "messages": MESSAGES, "tools": TOOLS, "max_tokens": 100}
    kwargs.update(overrides)
    return llm.create_message(**kwargs)


def test_a_valid_request_is_served():
    assert _call(_llm()).text_blocks == ["ok"]


# --- rule 1 -------------------------------------------------------------------------


@pytest.mark.parametrize("max_tokens", [0, -1, None, "100"])
def test_missing_or_invalid_max_tokens_is_rejected(max_tokens):
    with pytest.raises(FakeLLMContractError, match="max_tokens"):
        _call(_llm(), max_tokens=max_tokens)


# --- rule 2 -------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["@anthropic---tak-aa853e/claude-opus-5", "provider/model"])
def test_a_prefixed_model_route_is_rejected(model):
    """The classic way to waste a paid call on this interface (research D1)."""
    llm = _llm()
    llm.model = model  # type: ignore[attr-defined]

    with pytest.raises(FakeLLMContractError, match="prefixed route"):
        _call(llm)


# --- rule 3 -------------------------------------------------------------------------


def test_a_tool_result_for_an_unknown_tool_use_id_is_rejected():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_nope", "content": "{}"}],
        },
    ]

    with pytest.raises(FakeLLMContractError, match="unknown tool_use_id"):
        _call(_llm(), messages=messages)


# --- rule 4 -------------------------------------------------------------------------


def test_an_unanswered_tool_use_is_rejected():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "toolu_1", "name": "t", "input": {"a": 1}}],
        },
    ]

    with pytest.raises(FakeLLMContractError, match="no following tool_result"):
        _call(_llm(), messages=messages)


def test_a_properly_paired_tool_exchange_is_accepted():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "toolu_1", "name": "t", "input": {"a": 1}}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "{}"}],
        },
    ]

    assert _call(_llm(), messages=messages).text_blocks == ["ok"]


# --- rule 5 -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "messages,match",
    [
        ([{"role": "user", "content": []}], "empty content"),
        ([{"role": "user", "content": ""}], "empty content"),
        ([{"role": "system", "content": [{"type": "text", "text": "x"}]}], "unknown message role"),
        ([{"role": "user", "content": [{"type": "text", "text": "   "}]}], "empty text block"),
    ],
)
def test_malformed_turns_are_rejected(messages, match):
    with pytest.raises(FakeLLMContractError, match=match):
        _call(_llm(), messages=messages)


# --- rule 6 -------------------------------------------------------------------------


def test_an_unsupported_image_media_type_is_rejected():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/tiff", "data": "aGk="}}
            ],
        }
    ]

    with pytest.raises(FakeLLMContractError, match="media_type"):
        _call(_llm(), messages=messages)


def test_raw_bytes_instead_of_base64_is_rejected():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b"raw"}}
            ],
        }
    ]

    with pytest.raises(FakeLLMContractError, match="instead of a base64 string"):
        _call(_llm(), messages=messages)


# --- rule 7 -------------------------------------------------------------------------


def test_duplicate_tool_names_are_rejected():
    tools = [
        {"name": "dup", "description": "a", "input_schema": {"type": "object"}},
        {"name": "dup", "description": "b", "input_schema": {"type": "object"}},
    ]

    with pytest.raises(FakeLLMContractError, match="duplicate tool names"):
        _call(_llm(), tools=tools)


def test_a_non_object_input_schema_is_rejected():
    tools = [{"name": "t", "description": "d", "input_schema": {"type": "string"}}]

    with pytest.raises(FakeLLMContractError, match="must be an object schema"):
        _call(_llm(), tools=tools)


# --- rule 8 -------------------------------------------------------------------------


def test_an_exhausted_script_is_rejected():
    """An unscripted extra model call is a bug, not a pass."""
    llm = FakeLLM({"triage": [ScriptedTurn(text="only one")]})
    _call(llm)

    with pytest.raises(FakeLLMContractError, match="script exhausted"):
        _call(llm)


def test_a_system_prompt_without_a_route_marker_is_rejected():
    with pytest.raises(FakeLLMContractError, match="route"):
        _call(_llm(), system="You are a helpful assistant.")


# --- recording ----------------------------------------------------------------------


def test_requests_are_recorded_for_assertions():
    llm = _llm()

    _call(llm, max_tokens=321)

    assert llm.call_count == 1
    call = llm.calls[0]
    assert call["route"] == "triage"
    assert call["max_tokens"] == 321
    assert call["tools"] == TOOLS


def test_the_default_script_covers_every_route_the_pipeline_uses():
    """If a new mandatory call is added, build_script is the one place to update (G2)."""
    script = build_script()

    assert set(script) == {"intake", "triage", "safety"}
    assert script["safety"], "the safety gate runs on every triage (research D9)"
