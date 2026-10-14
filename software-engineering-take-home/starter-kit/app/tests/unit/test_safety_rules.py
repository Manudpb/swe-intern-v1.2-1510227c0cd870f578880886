"""US6 scenarios 1 to 4 - the deterministic detector, one fixture per limit.

The free detector is exhaustively testable, which is why it exists alongside the LLM review.
Each case also checks that the offending span is recorded, because sanitization deletes spans.
"""
from __future__ import annotations

import pytest

from claim_triage.agents.safety import rule_scan

pytestmark = pytest.mark.unit

NEUTRAL = "Water pooling across the kitchen floor from a failed supply line under the sink."


def test_coverage_promise_is_detected():
    verdict = rule_scan(NEUTRAL, "This damage is fully covered and will be paid.")

    assert verdict.checks.no_coverage_promises is False
    assert any(v.limit == "no_coverage_promises" for v in verdict.violations)


@pytest.mark.parametrize(
    "text",
    [
        "The claim is approved and coverage is confirmed.",
        "You can rest assured this will be taken care of.",
        "We guarantee the repairs will be reimbursed.",
    ],
)
def test_other_coverage_promise_phrasings(text):
    assert rule_scan(NEUTRAL, text).checks.no_coverage_promises is False


def test_settlement_amount_is_detected():
    verdict = rule_scan(NEUTRAL, "The claimant should expect a settlement of $12,000.")

    assert verdict.checks.no_settlement_amounts is False


def test_a_currency_figure_in_prose_reads_as_a_settlement_amount():
    verdict = rule_scan(NEUTRAL, "We will pay $8,400 for the repairs.")

    assert verdict.checks.no_settlement_amounts is False


def test_the_table_cost_range_is_permitted():
    """A repair-cost range from the company table is not a settlement figure."""
    verdict = rule_scan(
        NEUTRAL,
        "Repairs are estimated between $2,000 and $8,000 based on the company cost table.",
        cost_text="$2,000 $8,000 2000 8000",
    )

    assert verdict.checks.no_settlement_amounts is True
    assert verdict.clean


def test_legal_advice_and_liability_are_detected():
    verdict = rule_scan(NEUTRAL, "The neighbour is liable for this damage and should be sued.")

    assert verdict.checks.no_liability_determination is False
    assert verdict.checks.no_legal_advice is False


def test_fault_attribution_is_detected():
    verdict = rule_scan(NEUTRAL, "The tenant was negligent and is at fault for the leak.")

    assert verdict.checks.no_liability_determination is False


def test_emotional_language_is_detected():
    verdict = rule_scan(NEUTRAL, "We are devastated by this tragic loss.")

    assert verdict.checks.no_emotional_language is False


def test_neutral_professional_text_passes_untouched():
    verdict = rule_scan(
        NEUTRAL, "Assign an adjuster to verify the moisture readings and confirm the scope."
    )

    assert verdict.clean
    assert verdict.violations == []


def test_violations_record_the_exact_sentence_for_sanitization():
    offending = "This damage is fully covered and will be paid."
    verdict = rule_scan(NEUTRAL, f"Inspect the property. {offending}")

    sentences = [v.sentence for v in verdict.violations]
    assert offending in sentences


def test_the_damage_description_is_scanned_too():
    verdict = rule_scan("This tragic flood devastated the home.", "Inspect the property.")

    assert verdict.checks.no_emotional_language is False
