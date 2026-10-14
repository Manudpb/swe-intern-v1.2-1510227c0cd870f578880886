"""`intakeValidator` — the screen that runs before anything is spent.

Intake runs *before* the ReAct loop, so an unsuitable submission costs one model call instead
of a loop's worth (research D10). Any failed check stops the pipeline with 400: a confident
triage report on a photo of a parked car is worse than no report, because an adjuster may act
on it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claim_triage.api.schemas import IntakeValidation
from claim_triage.deps import Deps
from claim_triage.evidence.images import PreparedImage

PROMPT = (Path(__file__).parent / "prompts" / "intake.md").read_text(encoding="utf-8")

TOOL_NAME = "report_intake_validation"
TOOL = {
    "name": TOOL_NAME,
    "description": "Report the four intake checks and, when one fails, the reason.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_property_damage": {"type": "boolean"},
            "is_valid_image": {"type": "boolean"},
            "no_pii_detected": {"type": "boolean"},
            "no_offensive_content": {"type": "boolean"},
            "reason": {
                "type": "string",
                "description": "One or two sentences an adjuster can act on. Required when a check fails.",
            },
        },
        "required": [
            "is_property_damage",
            "no_pii_detected",
            "no_offensive_content",
            "reason",
        ],
    },
}

_FAILURE_PHRASES = {
    "is_property_damage": "the evidence does not show property or structural damage",
    "is_valid_image": "the image is not clear enough to assess",
    "no_pii_detected": "the submission shows personal information",
    "no_offensive_content": "the submission contains inappropriate or irrelevant content",
}


@dataclass(frozen=True)
class IntakeResult:
    validation: IntakeValidation
    reason: str

    @property
    def accepted(self) -> bool:
        flags = self.validation
        return bool(
            flags.is_property_damage
            and flags.no_pii_detected
            and flags.no_offensive_content
            and (flags.is_valid_image is not False)
        )

    def rejection_message(self) -> str:
        failed = [
            name
            for name, value in self.validation.model_dump().items()
            if value is False
        ]
        detail = "; ".join(_FAILURE_PHRASES[name] for name in failed) or "the submission is unsuitable"
        reason = self.reason.strip()
        base = f"This submission cannot be triaged because {detail}."
        return f"{base} {reason}".strip() if reason else base


def validate(
    deps: Deps, *, images: list[PreparedImage], description: str, document_text: str
) -> IntakeResult:
    """One model call. Text-only submissions get `is_valid_image = None` (FR-006, invariant I2)."""
    content: list[dict[str, Any]] = [image.to_block() for image in images]
    parts = []
    if description.strip():
        parts.append(f"Claimant description:\n{description.strip()}")
    if document_text.strip():
        parts.append(f"Attached document text (excerpt):\n{document_text.strip()[:1500]}")
    if not images:
        parts.append(
            "No photograph was submitted. Judge the three text-based checks from the "
            "description alone; do not report on image quality."
        )
    content.append({"type": "text", "text": "\n\n".join(parts) or "No description provided."})

    response = deps.llm.create_message(
        system=PROMPT,
        messages=[{"role": "user", "content": content}],
        tools=[TOOL],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        max_tokens=deps.settings.safety_max_tokens,
    )

    call = next((c for c in response.tool_calls if c.name == TOOL_NAME), None)
    if call is None:
        # No verdict is not a pass. Refuse rather than assume the submission is fine.
        return IntakeResult(
            validation=IntakeValidation(
                is_property_damage=False,
                is_valid_image=None if not images else False,
                no_pii_detected=True,
                no_offensive_content=True,
            ),
            reason="The intake check did not return a usable verdict.",
        )

    args = call.input
    return IntakeResult(
        validation=IntakeValidation(
            is_property_damage=bool(args.get("is_property_damage")),
            is_valid_image=None if not images else bool(args.get("is_valid_image", True)),
            no_pii_detected=bool(args.get("no_pii_detected")),
            no_offensive_content=bool(args.get("no_offensive_content")),
        ),
        reason=str(args.get("reason") or "").strip(),
    )
