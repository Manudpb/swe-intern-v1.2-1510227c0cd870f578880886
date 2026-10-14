# Specification Quality Checklist: Home-Damage Claim Triage Service

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-14
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Validation Record

**Iteration 1** — three gaps found and fixed in `spec.md`:

| Gap | Requirement left unverified | Fix |
|-----|----------------------------|-----|
| Policy-type default was stated but never exercised | FR-003 | Added US4 acceptance scenario 7 |
| No scenario forbade answer-key use at runtime | FR-021 | Added US3 acceptance scenario 6 |
| No scenario checked credentials stay out of output | FR-036 | Added US5 acceptance scenario 8 |

**Iteration 2** — all 16 items pass. Every FR-001 through FR-036 now maps to at least one
acceptance scenario or measurable outcome.

## Notes

Two judgement calls recorded in the spec's Assumptions section rather than as clarification
questions, because each has a defensible default. Both are cheap to reverse during `/speckit-plan`,
but they change observable behaviour, so they are worth a conscious confirmation:

1. **Safety failures are corrected, then delivered** — refusal only after bounded correction
   attempts fail. The alternative (refuse on first violation) is simpler but denies the adjuster a
   usable report over a fixable sentence, and counts against assessment accuracy.
2. **Coverage informs the recommendation but is not a report field** — the published report schema
   has no coverage field, so the required coverage lookup surfaces in the recommendation's wording
   and in the trace.

Two vocabulary notes on the "no implementation details" item, both accepted as given inputs rather
than design choices made here:

- Enum values (`water_damage`, `minor`, `is_valid_image`, …) are quoted because they are the fixed
  business vocabulary of the published contract, not a chosen encoding.
- `starter-kit/api-contract/openapi.yaml` and the two lookup tables are named in Dependencies and in
  FR-015/FR-017/FR-031 because they are supplied artifacts the spec must bind to. No language,
  framework, database or service is named anywhere in the spec.

Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`. None are
outstanding.
