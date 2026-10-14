"""The fake that does more than replay.

The whole risk of a free suite is that it proves the orchestration while the real request
shape is malformed — the one class of bug that otherwise only shows up on a paid call. So this
fake is strict about the *request*, not just generous with the response:

1. it routes by the `[route:...]` marker in the system prompt;
2. it records every request kwarg, so tests can assert what a response cannot show;
3. it raises on request shapes the real Messages API refuses (contracts/internal-ports.md).

An exhausted script raises too: a silent extra model call is a bug, not a pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from claim_triage.llm.ports import LLMResponse, ToolCall

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ROUTE_MARKER = re.compile(r"\[route:([a-z_]+)\]")


class FakeLLMContractError(AssertionError):
    """The request would have been rejected by the real API."""


@dataclass
class ScriptedTurn:
    """One model turn. `tool` produces a tool_use block; `text` the purpose sentence."""

    text: str = ""
    tool: str | None = None
    tool_input: dict[str, Any] = field(default_factory=dict)
    stop_reason: str = "tool_use"
    raises: Exception | None = None

    def to_response(self, call_index: int) -> LLMResponse:
        calls = []
        if self.tool:
            calls.append(
                ToolCall(id=f"toolu_fake_{call_index}", name=self.tool, input=dict(self.tool_input))
            )
        return LLMResponse(
            stop_reason=self.stop_reason if self.tool else "end_turn",
            text_blocks=[self.text] if self.text else [],
            tool_calls=calls,
        )


class FakeLLM:
    def __init__(self, script: dict[str, list[ScriptedTurn]] | None = None) -> None:
        self.script: dict[str, list[ScriptedTurn]] = {k: list(v) for k, v in (script or {}).items()}
        self.calls: list[dict[str, Any]] = []
        self._served = 0

    # --- the port ------------------------------------------------------------------

    def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        tool_choice: dict[str, Any] | None = None,
        **extra: Any,
    ) -> LLMResponse:
        route = self._route(system)
        self.calls.append(
            {
                "route": route,
                "system": system,
                "messages": messages,
                "tools": tools,
                "max_tokens": max_tokens,
                "tool_choice": tool_choice,
                "extra": dict(extra),
                "model": getattr(self, "model", "claude-opus-5"),
            }
        )
        self._validate_request(messages, tools, max_tokens, extra, tool_choice)

        queue = self.script.get(route)
        if not queue:
            raise FakeLLMContractError(
                f"script exhausted for route {route!r}: the application made an unscripted "
                f"model call (served {self._served} so far)"
            )
        turn = queue.pop(0)
        self._served += 1
        if turn.raises is not None:
            raise turn.raises
        return turn.to_response(self._served)

    # --- introspection for tests ---------------------------------------------------

    def calls_for(self, route: str) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["route"] == route]

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def remaining(self) -> dict[str, int]:
        return {route: len(turns) for route, turns in self.script.items() if turns}

    # --- the eight rejection rules -------------------------------------------------

    def _route(self, system: str) -> str:
        match = ROUTE_MARKER.search(system or "")
        if not match:
            raise FakeLLMContractError(
                "system prompt carries no [route:...] marker, so the call cannot be attributed "
                "to an agent"
            )
        return match.group(1)

    def _validate_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        extra: dict[str, Any] | None = None,
        tool_choice: dict[str, Any] | None = None,
    ) -> None:
        # 10. a tool_choice must name a tool that was actually declared.
        if tool_choice:
            kind = tool_choice.get("type")
            if kind not in ("auto", "any", "tool"):
                raise FakeLLMContractError(f"unknown tool_choice type {kind!r}")
            if kind == "tool":
                declared = {tool.get("name") for tool in tools or []}
                if tool_choice.get("name") not in declared:
                    raise FakeLLMContractError(
                        f"tool_choice names {tool_choice.get('name')!r}, which is not declared "
                        f"in tools {sorted(str(n) for n in declared)}"
                    )
        # 9. temperature is rejected by the approved model with HTTP 400. Found the hard way
        # on the first live triage; encoded here so it can never reach a paid call again.
        if extra and "temperature" in extra:
            raise FakeLLMContractError(
                "`temperature` is deprecated for this model and the gateway rejects the "
                "request with HTTP 400; do not send it"
            )
        if extra:
            raise FakeLLMContractError(f"unexpected request fields: {sorted(extra)}")

        # 1. max_tokens is required by the Messages API.
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            raise FakeLLMContractError(f"max_tokens must be a positive int, got {max_tokens!r}")

        # 2. the model id must be unprefixed on this interface (research D1).
        model = getattr(self, "model", "claude-opus-5")
        if "@" in model or "/" in model:
            raise FakeLLMContractError(
                f"model {model!r} looks like an OpenAI-style prefixed route; the Anthropic "
                "interface needs the unprefixed id with the provider in x-portkey-provider"
            )

        # 7. tool declarations must be unique and object-schema'd.
        names = [tool.get("name") for tool in tools or []]
        duplicates = {name for name in names if names.count(name) > 1}
        if duplicates:
            raise FakeLLMContractError(
                f"duplicate tool names declared: {sorted(str(name) for name in duplicates)}"
            )
        for tool in tools or []:
            schema = tool.get("input_schema")
            if not isinstance(schema, dict) or schema.get("type") != "object":
                raise FakeLLMContractError(
                    f"tool {tool.get('name')!r} input_schema must be an object schema"
                )

        tool_use_ids: set[str] = set()
        satisfied: set[str] = set()
        for index, message in enumerate(messages):
            role = message.get("role")
            # 5. roles and content must be well formed.
            if role not in ("user", "assistant"):
                raise FakeLLMContractError(f"unknown message role {role!r}")
            content = message.get("content")
            if content is None or content == "" or content == []:
                raise FakeLLMContractError(f"message {index} has empty content")

            blocks = content if isinstance(content, list) else []
            for block in blocks:
                if not isinstance(block, dict):
                    raise FakeLLMContractError(f"message {index} has a non-object content block")
                kind = block.get("type")
                if kind == "text" and not str(block.get("text") or "").strip():
                    raise FakeLLMContractError(f"message {index} has an empty text block")
                if kind == "image":
                    self._validate_image(block, index)
                if kind == "tool_use":
                    tool_use_ids.add(str(block.get("id")))
                if kind == "tool_result":
                    # 3. a tool_result must answer a tool_use we have already seen.
                    ref = str(block.get("tool_use_id"))
                    if ref not in tool_use_ids:
                        raise FakeLLMContractError(
                            f"tool_result references unknown tool_use_id {ref!r}"
                        )
                    satisfied.add(ref)

        # 4. an assistant turn ending in tool_use must be answered before the next request.
        unanswered = tool_use_ids - satisfied
        if unanswered:
            raise FakeLLMContractError(
                f"tool_use {sorted(unanswered)} has no following tool_result; the real API "
                "rejects a conversation left mid-tool-call"
            )

    def _validate_image(self, block: dict[str, Any], index: int) -> None:
        source = block.get("source") or {}
        media_type = source.get("media_type")
        if media_type not in ALLOWED_IMAGE_TYPES:
            raise FakeLLMContractError(
                f"message {index} image media_type {media_type!r} is not one of "
                f"{sorted(ALLOWED_IMAGE_TYPES)}"
            )
        if source.get("type") != "base64":
            raise FakeLLMContractError(f"message {index} image source must be base64")
        data = source.get("data")
        if not isinstance(data, str) or not data:
            raise FakeLLMContractError(
                f"message {index} image carries {type(data).__name__} instead of a base64 string"
            )
