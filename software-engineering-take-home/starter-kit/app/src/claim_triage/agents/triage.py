"""`triageAgent` — the ReAct loop.

Reason -> Act -> Observe, over Claude's native tool calling, until the agent calls
`submit_triage`. Three things this module is careful about:

* **Observability without leakage.** The purpose sentence the prompt asks for becomes the
  `reason` step. When a turn arrives with a tool call and no text, a purpose line is
  synthesized from the tool name and arguments, so the reason/act/observe triple always
  exists without depending on the model complying (research D4, FR-025).
* **Normalization before pricing.** `affected_areas` are canonicalized before
  `estimate_repair_cost` sees them, so the tool's count and the published checker's count
  agree (research D5).
* **Bounded work.** At most `max_tool_rounds` rounds; a repeated identical call is answered
  from the recorded observation instead of re-running, so a stuck model cannot burn budget.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claim_triage.deps import Deps
from claim_triage.domain.areas import normalize_areas
from claim_triage.evidence.images import PreparedImage
from claim_triage.llm.ports import LLMUnavailable
from claim_triage.tools import submit_triage
from claim_triage.tools.registry import build_registry
from claim_triage.trace.recorder import TraceRecorder

log = logging.getLogger(__name__)

PROMPT = (Path(__file__).parent / "prompts" / "triage.md").read_text(encoding="utf-8")


class TriageIncomplete(RuntimeError):
    """The loop ended without a priced, submitted assessment. Surfaced as 503."""


@dataclass
class TriageOutcome:
    submitted: dict[str, Any]
    rounds: int


def run(
    deps: Deps,
    *,
    recorder: TraceRecorder,
    images: list[PreparedImage],
    description: str,
    document_text: str,
    document_note: str,
    policy_type: str,
) -> TriageOutcome:
    registry = build_registry(deps)
    tools = registry.to_anthropic_tools()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _opening_content(images, description, document_text, document_note, policy_type)}
    ]
    observed: dict[str, Any] = {}

    for round_index in range(deps.settings.max_tool_rounds):
        response = deps.llm.create_message(
            system=PROMPT,
            messages=messages,
            tools=tools,
            max_tokens=deps.settings.llm_max_tokens,
            temperature=0.0,
        )
        call = response.first_tool_call
        if call is None:
            # No tool call: nudge once by recording the purpose and asking for an action.
            recorder.reason(_purpose(response.text_blocks) or "Deciding which evidence to gather next.")
            messages.append({"role": "assistant", "content": _assistant_text(response.text_blocks)})
            messages.append(
                {
                    "role": "user",
                    "content": "Continue by calling a tool, or call submit_triage if you have priced the damage.",
                }
            )
            continue

        recorder.reason(_purpose(response.text_blocks) or _synthesized_purpose(call.name, call.input))

        arguments = _prepare_arguments(call.name, call.input)
        recorder.act(call.name, arguments)

        signature = _signature(call.name, arguments)
        if signature in observed:
            output = observed[signature]
            recorder.observe(output, f"{call.name} repeated with identical inputs; reusing the recorded result")
        else:
            output = _invoke(registry, call.name, arguments, recorder)
            observed[signature] = output
            recorder.observe(output)

        messages.append({"role": "assistant", "content": _assistant_blocks(response.text_blocks, call)})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": json.dumps(output),
                    }
                ],
            }
        )

        if call.name == submit_triage.NAME and not output.get("error"):
            return TriageOutcome(submitted=arguments, rounds=round_index + 1)

    raise TriageIncomplete(
        f"The assessment did not complete within {deps.settings.max_tool_rounds} tool rounds"
    )


# --- helpers -----------------------------------------------------------------------


def _invoke(registry: Any, name: str, arguments: dict[str, Any], recorder: TraceRecorder) -> dict[str, Any]:
    spec = registry.get(name)
    if spec is None:
        return {"error": "unknown_tool", "message": f"No tool named {name}"}
    try:
        if name == submit_triage.NAME:
            priced = bool(recorder.successful_tool_calls("estimate_repair_cost"))
            return spec.handler(arguments, priced=priced)
        return spec.handler(arguments)
    except LLMUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - a tool failure is observable, not fatal
        log.warning("Tool %s failed: %s", name, type(exc).__name__)
        return {"error": "tool_failed", "message": f"{name} could not complete"}


def _prepare_arguments(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize areas before they reach the cost table or the final answer."""
    arguments = dict(raw)
    if name in ("estimate_repair_cost", "submit_triage"):
        areas = normalize_areas(arguments.get("affected_areas") or [])
        arguments["affected_areas"] = areas or ["unspecified"]
    if not arguments:
        arguments = {"note": "no arguments supplied"}
    return arguments


def _signature(name: str, arguments: dict[str, Any]) -> str:
    return name + "::" + json.dumps(arguments, sort_keys=True, default=str)


def _purpose(text_blocks: list[str]) -> str:
    text = " ".join(block.strip() for block in text_blocks if block.strip()).strip()
    return " ".join(text.split())


def _synthesized_purpose(name: str, arguments: dict[str, Any]) -> str:
    if name == "search_past_claims":
        return f"Looking for comparable historical claims matching: {arguments.get('query', '')}"
    if name == "estimate_repair_cost":
        areas = ", ".join(arguments.get("affected_areas") or [])
        return (
            f"Pricing {arguments.get('damage_type')} rated {arguments.get('severity')} "
            f"across {areas} from the company cost table."
        )
    if name == "check_coverage":
        return (
            f"Checking what {arguments.get('policy_type')} covers for "
            f"{arguments.get('incident_category')} to frame the recommendation."
        )
    if name == "submit_triage":
        return "Submitting the completed assessment for the adjuster."
    return f"Calling {name} to gather the evidence needed next."


def _assistant_text(text_blocks: list[str]) -> str:
    return _purpose(text_blocks) or "Continuing the assessment."


def _assistant_blocks(text_blocks: list[str], call: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    text = _purpose(text_blocks)
    if text:
        blocks.append({"type": "text", "text": text})
    blocks.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.input})
    return blocks


def _opening_content(
    images: list[PreparedImage],
    description: str,
    document_text: str,
    document_note: str,
    policy_type: str,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [image.to_block() for image in images]
    parts = [f"Policy type on file: {policy_type}."]
    if len(images) > 1:
        parts.append(
            f"{len(images)} photographs of the SAME incident are attached. They are different "
            "views, not separate claims, and they do not multiply the affected areas."
        )
    elif not images:
        parts.append("No photograph is available for this claim; assess from the description.")
    if description.strip():
        parts.append(f"Claimant description:\n{description.strip()}")
    else:
        parts.append("The claimant provided no written description.")
    if document_text.strip():
        parts.append(
            "Attached same-incident document text. Treat inspection findings as evidence that "
            "may change the affected scope; a contractor quote does NOT replace the cost "
            f"table's figure:\n{document_text.strip()}"
        )
    if document_note:
        parts.append(document_note)
    content.append({"type": "text", "text": "\n\n".join(parts)})
    return content
