"""Claude through the funded Portkey gateway.

The request shape is lifted from `starter-kit/scripts/check_claude_access.py`, which already
works against the live gateway (research D1):

    base_url = gateway root WITHOUT /v1      the SDK appends /v1/messages itself
    model    = the route's part after "/"    unprefixed; a prefixed route 404s here
    headers  = x-portkey-api-key + x-portkey-provider

Retry policy (research D8, constitution Principle III): at most ONE retry, only for
502/503/529 and timeouts. Never for 429/401/403 — looping on an exhausted allowance is
forbidden, so a 429 surfaces immediately and tells the operator to pause.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from claim_triage.llm.ports import LLMResponse, LLMUnavailable, ToolCall
from claim_triage.settings import Settings

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {502, 503, 529}
NEVER_RETRY_STATUS = {400, 401, 403, 404, 429}
RETRY_BACKOFF_S = 1.5


class AnthropicPortkeyClient:
    def __init__(self, settings: Settings) -> None:
        import anthropic

        self._anthropic = anthropic
        key = settings.portkey_api_key.get_secret_value()
        self._model = settings.model_id
        self._timeout = settings.llm_timeout_s
        self._client = anthropic.Anthropic(
            base_url=settings.gateway_root,
            api_key=key,
            timeout=settings.llm_timeout_s,
            max_retries=0,  # retries are this class's decision, not the SDK's
            default_headers={
                "x-portkey-api-key": key,
                "x-portkey-provider": settings.provider_route,
            },
        )

    def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResponse:
        attempt = 0
        while True:
            try:
                raw = self._client.messages.create(
                    model=self._model,
                    system=system,
                    messages=messages,
                    tools=tools or self._anthropic.NOT_GIVEN,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return _to_response(raw)
            except Exception as exc:  # noqa: BLE001 - normalized into LLMUnavailable below
                status = getattr(exc, "status_code", None)
                if status in NEVER_RETRY_STATUS:
                    raise LLMUnavailable(_message_for(status), status=status) from None
                retryable = status in RETRYABLE_STATUS or status is None
                if retryable and attempt == 0:
                    attempt += 1
                    log.warning("Model call failed (status=%s); one retry", status)
                    time.sleep(RETRY_BACKOFF_S)
                    continue
                raise LLMUnavailable(_message_for(status), status=status) from None


def _message_for(status: int | None) -> str:
    if status in (401, 403):
        return "Model access denied; check the key, gateway and approved route (no retry attempted)"
    if status == 404:
        return "Model or route not found; check CLAUDE_MODEL_ROUTE"
    if status == 429:
        return "Rate limit or allowance exhausted; pause and contact support. No retry attempted"
    if status in RETRYABLE_STATUS:
        return f"Model provider unavailable (HTTP {status}) after one retry"
    return "Cannot reach the model gateway (network, TLS or timeout) after one retry"


def _to_response(raw: Any) -> LLMResponse:
    texts: list[str] = []
    calls: list[ToolCall] = []
    for block in getattr(raw, "content", []) or []:
        kind = getattr(block, "type", None)
        if kind == "text":
            texts.append(getattr(block, "text", ""))
        elif kind == "tool_use":
            calls.append(
                ToolCall(
                    id=getattr(block, "id", ""),
                    name=getattr(block, "name", ""),
                    input=dict(getattr(block, "input", {}) or {}),
                )
            )
    return LLMResponse(
        stop_reason=getattr(raw, "stop_reason", None), text_blocks=texts, tool_calls=calls
    )
