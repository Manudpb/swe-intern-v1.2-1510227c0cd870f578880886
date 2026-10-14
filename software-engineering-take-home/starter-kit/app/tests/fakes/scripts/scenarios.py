"""Named scripts, one per scenario the suite exercises.

Composed from the turn helpers so a change to the pipeline's mandatory calls is made once
in `tests.fakes.build_script` rather than in every test (finding G2).
"""
from __future__ import annotations

from typing import Any

from tests.fakes import (
    build_script,
    cost_turn,
    coverage_turn,
    intake_turn,
    rewrite_turn,
    safety_turn,
    search_turn,
    submit_turn,
)

UNSAFE_DESCRIPTION = "Water pooling across the kitchen floor from a failed supply line."
UNSAFE_RECOMMENDATION = (
    "This damage is fully covered and will be paid. The claimant should expect a settlement "
    "of $12,000."
)
SAFE_RECOMMENDATION = (
    "Assign an adjuster to verify the moisture readings and confirm the assessed scope."
)


def clean_triage(**overrides: Any) -> dict[str, list]:
    """The happy path: one search, one price, one coverage check, one submission."""
    return build_script(**overrides)


def rejected_intake(**flags: Any) -> dict[str, list]:
    """Intake refuses, so no triage or safety turn is ever reached."""
    return {"intake": [intake_turn(**flags)], "triage": [], "safety": []}


def text_only() -> dict[str, list]:
    return build_script(
        triage=[
            search_turn("burst supply pipe moderate water damage kitchen"),
            cost_turn(areas=["kitchen"]),
            submit_turn(
                description="A burst supply pipe caused moderate water damage in the kitchen.",
            ),
        ]
    )


def pdf_widened_scope() -> dict[str, list]:
    """The inspection names the dining room too, so the priced scope is two areas."""
    return build_script(
        triage=[
            search_turn(),
            cost_turn(areas=["kitchen", "dining_room"]),
            submit_turn(
                areas=["kitchen", "dining_room"],
                description=(
                    "Water spread from the kitchen into the adjacent dining room; the attached "
                    "inspection records elevated moisture in both rooms."
                ),
            ),
        ]
    )


def safety_rewrite_succeeds() -> dict[str, list]:
    """Review flags the draft, the rewrite fixes it, the re-review is clean."""
    return build_script(
        triage=[search_turn(), cost_turn(), submit_turn(recommendation=UNSAFE_RECOMMENDATION)],
        safety=[
            safety_turn(
                no_coverage_promises=False,
                no_settlement_amounts=False,
                violations=[
                    {
                        "limit": "no_coverage_promises",
                        "sentence": "This damage is fully covered and will be paid.",
                    },
                    {
                        "limit": "no_settlement_amounts",
                        "sentence": "The claimant should expect a settlement of $12,000.",
                    },
                ],
            ),
            rewrite_turn(UNSAFE_DESCRIPTION, SAFE_RECOMMENDATION),
            safety_turn(),
        ],
    )


def safety_sanitize_path() -> dict[str, list]:
    """The rewrite comes back still violating, so the named sentence is dropped instead."""
    return build_script(
        triage=[search_turn(), cost_turn(), submit_turn(recommendation=UNSAFE_RECOMMENDATION)],
        safety=[
            safety_turn(
                no_coverage_promises=False,
                violations=[
                    {
                        "limit": "no_coverage_promises",
                        "sentence": "This damage is fully covered and will be paid.",
                    }
                ],
            ),
            rewrite_turn(
                UNSAFE_DESCRIPTION,
                "This damage is fully covered and will be paid. " + SAFE_RECOMMENDATION,
            ),
            safety_turn(
                no_coverage_promises=False,
                violations=[
                    {
                        "limit": "no_coverage_promises",
                        "sentence": "This damage is fully covered and will be paid.",
                    }
                ],
            ),
        ],
    )


def safety_unsanitizable() -> dict[str, list]:
    """Every sentence of the recommendation violates, so removal would empty the field."""
    only_sentence = "This claim is fully covered and will be paid."
    return build_script(
        triage=[search_turn(), cost_turn(), submit_turn(recommendation=only_sentence)],
        safety=[
            safety_turn(
                no_coverage_promises=False,
                violations=[{"limit": "no_coverage_promises", "sentence": only_sentence}],
            ),
            rewrite_turn(UNSAFE_DESCRIPTION, only_sentence),
            safety_turn(
                no_coverage_promises=False,
                violations=[{"limit": "no_coverage_promises", "sentence": only_sentence}],
            ),
        ],
    )


def multi_view_same_room() -> dict[str, list]:
    """Three photographs of one kitchen must still price as a single area."""
    return build_script(
        triage=[
            search_turn(),
            cost_turn(areas=["kitchen", "kitchen floor", "interior"]),
            submit_turn(areas=["kitchen", "kitchen floor", "interior"]),
        ]
    )


def no_coverage_call() -> dict[str, list]:
    """A minimal valid loop: retrieval and pricing only (coverage is not a report field)."""
    return build_script(triage=[search_turn(), cost_turn(), submit_turn()])
