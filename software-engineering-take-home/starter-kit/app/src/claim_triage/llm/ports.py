"""The LLM seam.

Nothing above this module touches a vendor type. The orchestrator sees `LLMResponse`,
which is why a fake can stand in for the real client without the tests knowing (Principle VI).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class LLMUnavailable(RuntimeError):
    """Model access failed in a way the caller must surface, never paper over.

    Raised for an unreachable gateway, a timeout, a rate limit, or an error that survived
    the single permitted retry. The API turns this into 503 (FR-035, research D8).
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    stop_reason: str | None = None
    text_blocks: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def first_tool_call(self) -> ToolCall | None:
        return self.tool_calls[0] if self.tool_calls else None


@runtime_checkable
class LLMClient(Protocol):
    def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResponse: ...
