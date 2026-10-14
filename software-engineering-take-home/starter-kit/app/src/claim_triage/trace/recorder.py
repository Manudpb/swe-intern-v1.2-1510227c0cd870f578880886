"""The ReAct trace.

Three rules this module exists to enforce, because a reviewer cannot audit a report whose
trace is merely plausible:

* every `act` is paired with the `observe` for that action (invariant I7);
* step numbers run 1..n with no gaps, and `tool_*` fields appear only on their own kind;
* `reason` content is a capped action-purpose summary, never private model reasoning (FR-025).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REASON_CONTENT_LIMIT = 240


class TraceIntegrityError(RuntimeError):
    """A malformed trace is never published. Raised at publish time, not silently fixed."""


@dataclass
class TraceRecorder:
    clock: Any
    steps: list[dict[str, Any]] = field(default_factory=list)
    _started: Any = None
    _pending_act: tuple[str, dict[str, Any]] | None = None

    def start(self) -> None:
        self._started = self.clock()

    # --- recording -----------------------------------------------------------------

    def reason(self, content: str) -> None:
        """An action-purpose summary: what the agent needs next and why it needs it."""
        text = " ".join((content or "").split())
        if not text:
            text = "Deciding the next step from the evidence gathered so far."
        if len(text) > REASON_CONTENT_LIMIT:
            text = text[: REASON_CONTENT_LIMIT - 1].rstrip() + "…"
        self._append("reason", text)

    def act(self, tool_name: str, tool_input: dict[str, Any]) -> None:
        if self._pending_act is not None:
            raise TraceIntegrityError(
                f"Action {self._pending_act[0]} was never observed; cannot start {tool_name}"
            )
        if not tool_name or not isinstance(tool_input, dict) or not tool_input:
            raise TraceIntegrityError("An act step needs a tool name and non-empty inputs")
        self._pending_act = (tool_name, tool_input)
        self._append(
            "act",
            f"Calling {tool_name} with {_summarize(tool_input)}",
            tool_name=tool_name,
            tool_input=tool_input,
        )

    def observe(self, tool_output: dict[str, Any] | list[Any], content: str | None = None) -> None:
        if self._pending_act is None:
            raise TraceIntegrityError("An observation with no preceding action")
        tool_name, _ = self._pending_act
        self._pending_act = None
        if not isinstance(tool_output, (dict, list)) or not tool_output:
            raise TraceIntegrityError(f"{tool_name} returned no substantive output to observe")
        self._append(
            "observe",
            content or f"{tool_name} returned {_summarize(tool_output)}",
            tool_output=tool_output,
        )

    def _append(self, kind: str, content: str, **extra: Any) -> None:
        step: dict[str, Any] = {
            "step_number": len(self.steps) + 1,
            "type": kind,
            "content": content,
            "timestamp": self.clock().isoformat().replace("+00:00", "Z"),
        }
        step.update(extra)
        self.steps.append(step)

    # --- inspection ----------------------------------------------------------------

    def successful_tool_calls(self, tool_name: str) -> list[tuple[dict[str, Any], Any]]:
        """Argument/output pairs for a tool, excluding recorded failures.

        This is the source of truth the report is assembled from (invariant I3).
        """
        out: list[tuple[dict[str, Any], Any]] = []
        pending: dict[str, Any] | None = None
        pending_name: str | None = None
        for step in self.steps:
            if step["type"] == "act":
                pending_name, pending = step["tool_name"], step["tool_input"]
            elif step["type"] == "observe" and pending is not None:
                output = step["tool_output"]
                failed = isinstance(output, dict) and output.get("error")
                if pending_name == tool_name and not failed:
                    out.append((pending, output))
                pending, pending_name = None, None
        return out

    def retrieved_claim_ids(self) -> set[str]:
        """Claim ids that successful retrieval actually returned (invariant I4)."""
        ids: set[str] = set()
        for _args, output in self.successful_tool_calls("search_past_claims"):
            records = output.get("claims") if isinstance(output, dict) else output
            for record in records or []:
                if isinstance(record, dict) and record.get("claim_id"):
                    ids.add(record["claim_id"])
        return ids

    # --- publishing ----------------------------------------------------------------

    def publish(self, claim_id: str) -> dict[str, Any]:
        self._validate()
        duration = 0
        if self._started is not None:
            duration = max(0, int((self.clock() - self._started).total_seconds() * 1000))
        return {"claim_id": claim_id, "steps": list(self.steps), "total_duration_ms": duration}

    def _validate(self) -> None:
        if self._pending_act is not None:
            raise TraceIntegrityError(
                f"Last action {self._pending_act[0]} has no observation"
            )
        if not self.steps:
            raise TraceIntegrityError("A published trace cannot be empty")
        for index, step in enumerate(self.steps, start=1):
            if step["step_number"] != index:
                raise TraceIntegrityError("Trace step numbers must run 1..n with no gaps")
            if step["type"] not in ("reason", "act", "observe"):
                raise TraceIntegrityError(f"Unknown trace event {step['type']}")
            if not str(step.get("content", "")).strip():
                raise TraceIntegrityError("Every trace step needs non-empty content")
            if step["type"] == "act" and not step.get("tool_input"):
                raise TraceIntegrityError("An act step needs non-empty tool inputs")
            if step["type"] == "observe" and not step.get("tool_output"):
                raise TraceIntegrityError("An observe step needs a substantive tool output")
        if not self.successful_tool_calls("estimate_repair_cost"):
            raise TraceIntegrityError("No successful cost evidence in the trace (invariant I9)")
        if not self.successful_tool_calls("search_past_claims"):
            raise TraceIntegrityError("No successful retrieval evidence in the trace (invariant I9)")


def _summarize(value: Any, limit: int = 160) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"
