# Phase 1 Data Model: Home-Damage Claim Triage Service

**Date**: 2026-10-14 | **Plan**: [plan.md](./plan.md) | **Spec entities**: [spec.md](./spec.md)

Wire-facing shapes are fixed by `starter-kit/api-contract/openapi.yaml` and are mirrored, not
redesigned. This document records fields, the enums, the validation rules each requirement implies,
and the invariants that hold between entities.

---

## Enumerations

| Enum | Values | Notes |
|---|---|---|
| `DamageType` | `water_damage`, `fire_damage`, `storm_damage`, `break_in`, `vandalism`, `other` | Also the cost table's first key and the coverage table's category vocabulary |
| `Severity` | `minor`, `moderate`, `severe`, `catastrophic` | Ordinal for scoring; the cost table's second key |
| `Urgency` | `low`, `medium`, `high`, `critical` | Derived, not looked up (spec assumption) |
| `PolicyType` | `basic_homeowner`, `standard_homeowner`, `premium_homeowner`, `renters`, `landlord` | Default `standard_homeowner` (FR-003) |
| `StepKind` | `reason`, `act`, `observe` | |

A value outside these sets is never emitted; a model turn proposing one is a tool-input validation
failure, handled as a loop error (FR-009).

---

## Request-side entities

### Submission *(transient — never stored)*

| Field | Type | Rules |
|---|---|---|
| `images` | list of bytes + media type | From multipart `image` (single) and/or repeated `images`. **No count cap** — the contract sets no upper bound and no requirement authorizes refusing a submission for view count (finding U2). Each ≤ 10 MB; media type in `image/jpeg`, `image/png`. Each is downscaled to ≤ 1024 px on the long edge and re-encoded JPEG q80 before upload (D1 token cost) |
| `description` | string or None | Trimmed. Blank counts as absent |
| `document` | bytes or None | `application/pdf`. Text extracted with pypdf, truncated to 8 000 characters. Unreadable → the report notes it (US7 scenario 7) |
| `policy_type` | `PolicyType` | Defaults to `standard_homeowner` |

**Validation**: at least one image **or** a non-blank description, else 400 (FR-002). All images are
views of one incident, never separate claims.

---

## Screening

### IntakeVerdict

Named `intake_validation` on the wire and in code; "IntakeVerdict" and the spec's "Intake Verdict"
are prose aliases for the same thing (finding I3). The wire name is authoritative.

| Field | Type | Rules |
|---|---|---|
| `is_property_damage` | bool | |
| `is_valid_image` | bool or **None** | `None` **only** for a submission with no image (FR-006) |
| `no_pii_detected` | bool | A payment card, synthetic included, forces `false` (FR-007) |
| `no_offensive_content` | bool | Judged from image and text |

**Invariant I1**: any flag `false` → the response is 400 `ValidationError` carrying this verdict and
a non-empty prose `message`, and **no** `triage_assessment` is produced (FR-005, US2 scenario 5).

**Invariant I2**: `is_valid_image is None` **iff** the submission carried no image.

---

## Assessment

### CostRange

| Field | Type | Rules |
|---|---|---|
| `min` | number | `= min_per_area × n` |
| `max` | number | `= max_per_area × n`, and `min ≤ max` (FR-018) |
| `currency` | string | `"USD"` |

where `n = max(1, len(distinct_areas))` (FR-016) and the per-area figures come only from
`tools/cost-estimator.json` (FR-015).

### CoverageFinding *(internal — not a report field)*

`covered: bool`, `deductible: number`, `max_payout: number`, `notes: string`, read from
`tools/coverage-table.json`. Surfaces only through the recommendation's wording and the trace
(spec assumption). An unlisted policy or category yields `{"error": ...}` instead of a guess
(FR-017).

### SimilarClaimRef

| Field | Type | Rules |
|---|---|---|
| `claim_id` | string | **MUST** exist in the knowledge base (FR-020) |
| `similarity_score` | number | `0 ≤ s ≤ 1` |
| `resolution_summary` | string | Non-empty; derived from the record's `resolution` and outcome, not invented |

### TriageAssessment

| Field | Type | Rules |
|---|---|---|
| `damage_type` | `DamageType` | Copied from the final cost call's arguments (I3) |
| `severity` | `Severity` | Copied from the final cost call's arguments (I3) |
| `affected_areas` | list of string | Normalized, distinct, order-preserved; copied verbatim from the final cost call's arguments (I3) |
| `damage_description` | string | Non-empty. For a text-only submission the assembler appends the exact sentence `"No photographic evidence was provided; this assessment is based on the written description alone and carries lower confidence."` so the requirement is checkable rather than qualitative (finding A1, US7 scenario 2). Any source conflict is stated too (US7 scenario 6) |
| `estimated_repair_cost` | `CostRange` | Copied from the final cost observation (I3) |
| `urgency` | `Urgency` | Derived from severity, damage type and ongoing-risk cues |
| `recommendation` | string | Non-empty; must survive the safety gate |
| `similar_past_claims` | list of `SimilarClaimRef` | Subset of what retrieval actually returned (I4) |

### SafetyVerdict

Five booleans: `no_coverage_promises`, `no_legal_advice`, `no_settlement_amounts`,
`no_liability_determination`, `no_emotional_language`.

Each flag is the **conjunction of two detectors** — the deterministic rule pass and the low-effort
LLM review (research D9). A limit is satisfied only if both agree; a disagreement resolves against
the report. Internally each violation also carries the character spans that triggered it, which is
what sanitization deletes; the spans are not part of the wire response.

**Invariant I5**: a delivered report has all five `true` (FR-030). If neither the single rewrite nor
sanitization can reach that state, the response is 422 `SafetyError` instead (FR-029).

**Invariant I12**: the ladder runs at most one rewrite and one sanitization, so at most three
safety-route model calls occur per triage — review, rewrite, re-review. No stage repeats, which makes
the attempt count bounded by construction (FR-028).

### TriageReport *(stored, retrievable)*

`claim_id` (uuid4 string, issued at submission), `intake_validation`, `triage_assessment`,
`safety_checks`.

**Invariant I6**: `GET /api/v1/claims/{claim_id}` returns byte-identical content to what the
submission returned (FR-013); an unknown id is 404 (FR-014).

---

## Trace

### TraceStep

| Field | Type | Rules |
|---|---|---|
| `step_number` | int | Starts at 1, increments by exactly 1, no gaps |
| `type` | `StepKind` | |
| `content` | string | Non-empty. Action-purpose summary, tool call description, or observation. Capped at 240 chars for `reason` steps. Never private reasoning (FR-025) |
| `tool_name` | string | **Only** on `act` steps; non-empty |
| `tool_input` | object | **Only** on `act` steps; non-empty |
| `tool_output` | object or array | **Only** on `observe` steps; non-empty |
| `timestamp` | RFC 3339 date-time | Monotonic non-decreasing across the trace |

### Trace

`claim_id`, `steps` (ordered), `total_duration_ms` (int).

**Invariant I7**: every `act` step is immediately followed by the `observe` step for that action; no
`act` is left unobserved and no `observe` is orphaned.

**Invariant I8**: the trace contains at least two steps of each kind and at least one consecutive
`reason → act → observe` triple.

**Invariant I9**: at least one successful `search_past_claims` and one successful
`estimate_repair_cost` observation exist in any delivered report's trace.

**Invariant I10**: no trace, report or log line contains the credential (FR-036).

---

## Retrieval

### HistoricalClaim *(read-only corpus, 30 records)*

Source fields: `claim_id`, `description`, `adjuster_notes`, `damage_type`, `severity`,
`affected_areas`, `policy_type`, `date_filed`, `date_resolved`, `repair_cost_actual`, `resolution`,
`fraud_indicators`, `case_reference`.

**Embedded text** = `description` + `adjuster_notes` + `damage_type` + `severity` +
`affected_areas` (D7). `repair_cost_actual`, `resolution` and `fraud_indicators` live in the payload
only, so they cannot distort similarity.

**Invariant I11**: the corpus is the only runtime retrieval source. `data/ground-truth/` is never
mounted, read, or reachable by filename correspondence (FR-021, Principle V).

---

## The central invariants

**I3 — Scope and money come from the trace, not the model.** Let `A` be the arguments and `O` the
output of the **last successful** `estimate_repair_cost` call. Then:

```text
report.damage_type      == A.damage_type
report.severity         == A.severity
report.affected_areas   == A.affected_areas          (same values, same order)
report.estimated_repair_cost.min == O.min
report.estimated_repair_cost.max == O.max
```

No such call → the request fails (503) rather than returning a model-authored figure.

**I4 — Citations are earned.** `{c.claim_id for c in report.similar_past_claims}` ⊆ the union of
claim ids returned by successful `search_past_claims` observations. Ids outside that set are dropped
before delivery, never renamed or invented.

Both are enforced in one place (`domain/report.py`) and unit-tested directly, so they hold regardless
of what the model returns.

---

## Area normalization (the function behind FR-012)

`normalize_areas(raw: list[str]) -> list[str]`:

1. lowercase, trim, collapse spaces/hyphens → `_` — `"Dining Room"` → `dining_room`
2. synonym map — `bath`→`bathroom`, `lounge`/`living`→`living_room`, `attic_space`→`attic`, …
3. drop component suffixes when the parent room is present — `kitchen_floor`, `kitchen_wall`,
   `kitchen_ceiling`, `kitchen_subfloor` → `kitchen`
4. drop generic umbrellas (`interior`, `exterior`, `house`, `property`, `whole_house`) when any
   specific area survives; keep exactly one if nothing else does
5. de-duplicate preserving first-seen order

Worked example from the spec (US4 scenario 4): `["kitchen", "kitchen floor", "interior"]` →
`["kitchen"]` → `n = 1`.

Worked example from the PDF case (US7 scenario 5): `["kitchen", "Dining Room"]` →
`["kitchen", "dining_room"]` → `n = 2` → water/moderate → `min 4000`, `max 16000`.

---

## Lifecycle

```text
Submission
   → IntakeVerdict ── any false ──→ 400 ValidationError (stop; no trace of tool activity)
        │ all pass
        ▼
   ReAct loop (≤ 6 tool rounds) ──→ TraceStep*       ── no successful cost call ──→ 503
        │ submit_triage called
        ▼
   TriageAssessment (I3 + I4 applied)
        ▼
   SafetyVerdict  (rules ∧ LLM review)
        │ any limit false
        ├──→ rewrite once (broken rules named) ──→ re-run both detectors
        │         │ still failing
        │         ├──→ sanitize: drop the named sentences ──→ deterministic re-check
        │         │         │ still failing or field would empty
        │         │         └──→ 422 SafetyError
        │         ▼ clean
        │       deliver
        ▼ all five true
        │ all five true
        ▼
   TriageReport stored by claim_id, Trace stored by claim_id ──→ 200
```

Reports and traces live in a bounded in-memory store (LRU, 500 entries) for the process lifetime.
A trace is published only once its run completes; until then the id reads as 404 (spec edge case).
