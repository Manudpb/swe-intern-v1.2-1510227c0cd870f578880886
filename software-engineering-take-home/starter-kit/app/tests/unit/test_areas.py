"""US4 scenario 4 / FR-012 - rooms are counted once.

This is the rule-level test of `normalize_areas`. T089 tests the same rule through the
multi-photo entry point, so a change here must update both (finding D1).
"""
from __future__ import annotations

import pytest

from claim_triage.domain.areas import distinct_count, normalize_areas

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "raw,expected",
    [
        (["kitchen", "kitchen floor", "interior"], ["kitchen"]),
        (["kitchen", "Dining Room"], ["kitchen", "dining_room"]),
        (["Kitchen", "kitchen"], ["kitchen"]),
        (["kitchen wall", "kitchen ceiling"], ["kitchen"]),
        (["roof", "roof shingles", "exterior"], ["roof"]),
        (["bath", "bathroom"], ["bathroom"]),
        (["basement", "cellar"], ["basement"]),
        (["living room", "lounge"], ["living_room"]),
        ([], []),
        (["", "   "], []),
    ],
)
def test_normalization_collapses_to_distinct_rooms(raw, expected):
    assert normalize_areas(raw) == expected


def test_generic_umbrella_is_dropped_when_a_specific_area_survives():
    assert normalize_areas(["interior", "kitchen", "property"]) == ["kitchen"]


def test_a_generic_umbrella_alone_is_kept_once():
    assert normalize_areas(["interior", "exterior", "property"]) == ["interior"]


def test_first_seen_order_is_preserved():
    assert normalize_areas(["basement", "kitchen", "attic"]) == ["basement", "kitchen", "attic"]


def test_order_matters_because_the_report_copies_the_list_verbatim():
    """Invariant I3 copies the priced list into the report, so order is part of the contract."""
    assert normalize_areas(["kitchen", "basement"]) != normalize_areas(["basement", "kitchen"])


def test_distinct_count_treats_zero_areas_as_one():
    """FR-016: the multiplier is never zero, so a report never carries a zero-width range."""
    assert distinct_count([]) == 1
    assert distinct_count(None) == 1


def test_distinct_count_matches_the_published_checker_exactly():
    """It must NOT apply synonym rules: the grader recomputes with lower+strip only.

    If this collapsed ["bath", "bathroom"] to one while the checker saw two, the cost
    observation would contradict the table and the trace check would fail (research D5).
    """
    args = ["bath", "bathroom"]
    assert distinct_count(args) == max(1, len({a.strip().lower() for a in args})) == 2
    # After normalization the two counts agree, which is why normalization runs first.
    normalized = normalize_areas(args)
    assert distinct_count(normalized) == max(1, len({a.strip().lower() for a in normalized})) == 1
