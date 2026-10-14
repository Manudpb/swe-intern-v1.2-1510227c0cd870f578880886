"""Research D8 - one retry for transient faults, never for an exhausted allowance.

The constitution forbids looping on a 429: the allowance is shared with coding and grading,
so a rate limit must surface immediately and tell the operator to pause.
"""
from __future__ import annotations

import pytest

from claim_triage.llm.anthropic_portkey import (
    NEVER_RETRY_STATUS,
    RETRYABLE_STATUS,
    AnthropicPortkeyClient,
    _message_for,
)
from claim_triage.llm.ports import LLMUnavailable

pytestmark = pytest.mark.unit


class FakeStatusError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status_code = status


class StubMessages:
    def __init__(self, failures: list[Exception], result: object = None) -> None:
        self.failures = list(failures)
        self.result = result
        self.attempts = 0

    def create(self, **_kwargs):
        self.attempts += 1
        if self.failures:
            raise self.failures.pop(0)
        return self.result


@pytest.fixture
def client(settings, monkeypatch):
    """A real client with the SDK construction stubbed out: no network, no credential use."""
    import sys
    import types

    fake_sdk = types.ModuleType("anthropic")

    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.messages = None

    fake_sdk.Anthropic = FakeAnthropic
    fake_sdk.NOT_GIVEN = object()
    monkeypatch.setitem(sys.modules, "anthropic", fake_sdk)

    built = AnthropicPortkeyClient(settings)
    monkeypatch.setattr("claim_triage.llm.anthropic_portkey.RETRY_BACKOFF_S", 0.0)
    return built


class StubResponse:
    stop_reason = "end_turn"
    content: list = []


@pytest.mark.parametrize("status", sorted(RETRYABLE_STATUS))
def test_a_transient_status_is_retried_exactly_once(client, status):
    stub = StubMessages([FakeStatusError(status)], StubResponse())
    client._client.messages = stub  # type: ignore[attr-defined]

    client.create_message(system="[route:triage]", messages=[], tools=[], max_tokens=10)

    assert stub.attempts == 2, "one failure plus one retry"


@pytest.mark.parametrize("status", sorted(RETRYABLE_STATUS))
def test_a_second_failure_is_not_retried_again(client, status):
    stub = StubMessages([FakeStatusError(status), FakeStatusError(status)], StubResponse())
    client._client.messages = stub  # type: ignore[attr-defined]

    with pytest.raises(LLMUnavailable):
        client.create_message(system="[route:triage]", messages=[], tools=[], max_tokens=10)

    assert stub.attempts == 2, "bounded: never an unbounded retry loop"


@pytest.mark.parametrize("status", sorted(NEVER_RETRY_STATUS))
def test_client_errors_and_rate_limits_are_never_retried(client, status):
    stub = StubMessages([FakeStatusError(status)], StubResponse())
    client._client.messages = stub  # type: ignore[attr-defined]

    with pytest.raises(LLMUnavailable):
        client.create_message(system="[route:triage]", messages=[], tools=[], max_tokens=10)

    assert stub.attempts == 1, f"HTTP {status} must not be retried"


def test_a_rate_limit_message_tells_the_operator_to_pause():
    message = _message_for(429)

    assert "pause" in message.lower()
    assert "no retry" in message.lower()


def test_an_auth_failure_names_the_route_not_the_key():
    message = _message_for(401)

    assert "route" in message.lower()
    assert "sk-" not in message


def test_a_network_error_with_no_status_is_retried_once(client):
    stub = StubMessages([OSError("connection reset")], StubResponse())
    client._client.messages = stub  # type: ignore[attr-defined]

    client.create_message(system="[route:triage]", messages=[], tools=[], max_tokens=10)

    assert stub.attempts == 2


def test_the_client_is_built_with_the_gateway_root_and_provider_header(client, settings):
    kwargs = client._client.kwargs  # type: ignore[attr-defined]

    assert kwargs["base_url"] == settings.gateway_root
    assert kwargs["base_url"].endswith("portkey.example")
    assert kwargs["default_headers"]["x-portkey-provider"] == settings.provider_route
    assert kwargs["max_retries"] == 0, "retries are this class's decision, not the SDK's"
