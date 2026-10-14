# Contract: Agent tools

The four tools exposed to the model, their input schemas, their return shapes, and the rules each
one enforces. Tool returns are recorded verbatim as `observe` steps, so these shapes are also the
trace's evidence format.

---

## `search_past_claims`

Semantic search over the 30 historical claims.

```json
{ "query": "string, non-empty — natural-language description of the damage",
  "top_k": "integer 1-10, default 5" }
```

**Returns** `{"claims": [{"claim_id", "similarity_score", "damage_type", "severity",
"affected_areas", "resolution_summary"}]}` — ordered by descending score.

Rules:

- Every `claim_id` exists in the corpus; nothing is synthesized.
- `0 ≤ similarity_score ≤ 1` (cosine mapped into range).
- An empty corpus or unreachable store returns `{"error": "retrieval_unavailable"}`.
- Results feed invariant I4: only ids seen here may be cited in the report.

---

## `estimate_repair_cost`

The **only** source of money in the system.

```json
{ "damage_type": "enum DamageType",
  "severity":    "enum Severity",
  "affected_areas": "array of non-empty strings" }
```

**Returns** `{"min": number, "max": number, "currency": "USD", "areas_counted": integer}`.

Rules:

- `n = max(1, |{a.strip().lower() for a in affected_areas}|)`; `min = min_per_area × n`,
  `max = max_per_area × n` from `tools/cost-estimator.json`.
- Callers pass **already normalized** areas (see `normalize_areas` in
  [data-model.md](../data-model.md)), so the tool's count and the evaluator's count agree.
- Unknown `damage_type`/`severity` → `{"error": "unknown_cost_key"}`; no fallback figure.
- The last successful call's arguments and output become the report's scope and cost (invariant I3).

---

## `check_coverage`

```json
{ "policy_type": "enum PolicyType",
  "incident_category": "enum DamageType" }
```

**Returns** `{"covered": bool, "deductible": number, "max_payout": number, "notes": string}` from
`tools/coverage-table.json`.

Rules:

- An unlisted policy or category → `{"error": "unknown_coverage_key"}`; never a guessed deductible.
- The result shapes the recommendation's wording only. It is never stated as a promise or a denial,
  and it is not a report field.

---

## `submit_triage`

The terminal action. Its input schema *is* the report schema, which is how structured output is
obtained without parsing prose.

```json
{ "damage_type": "enum DamageType",
  "severity": "enum Severity",
  "affected_areas": "array of strings",
  "damage_description": "string, non-empty",
  "urgency": "enum Urgency",
  "recommendation": "string, non-empty",
  "similar_past_claims": [{"claim_id": "string", "similarity_score": "number 0-1",
                           "resolution_summary": "string"}] }
```

**Returns** `{"accepted": true}`.

Rules:

- No cost field: the model cannot propose money. Cost is taken from the trace (I3).
- `damage_type`, `severity` and `affected_areas` here are advisory; the delivered values are copied
  from the last successful `estimate_repair_cost` arguments. A mismatch is logged as a drift warning,
  not silently accepted.
- Cited `claim_id`s not present in any successful retrieval are dropped (I4).
- Calling it before any `estimate_repair_cost` succeeded is rejected with a tool error telling the
  model to price the damage first.

---

## Safety-route tools

Used by `safetyChecker`, not by the triage loop. Both are forced tool calls so the verdict and the
replacement text arrive structured. Each call is low effort: thinking disabled, `temperature = 0`,
`max_tokens = 300`, text only — no images, no retrieval context (research D9).

### `report_safety_verdict`

```json
{ "no_coverage_promises": "bool",
  "no_legal_advice": "bool",
  "no_settlement_amounts": "bool",
  "no_liability_determination": "bool",
  "no_emotional_language": "bool",
  "violations": [{"limit": "enum of the five limit names",
                  "sentence": "the exact offending sentence, copied verbatim"}] }
```

The quoted sentence is what sanitization deletes, so it must be copied verbatim rather than
paraphrased; a sentence that cannot be located in the source text is treated as a non-finding and
logged as reviewer drift.

### `submit_rewritten_text`

```json
{ "damage_description": "string, non-empty",
  "recommendation": "string, non-empty" }
```

Called on the single rewrite attempt, with the broken limits and the offending sentences named in the
prompt. Factual content — damage type, severity, areas, the cost range — must survive unchanged; the
rewrite may only neutralize wording. Cost and scope are re-imposed from the trace afterwards anyway
(invariant I3), so a rewrite cannot alter the numbers.

## Loop control

- System prompt requires one short purpose sentence before each tool call (recorded as the `reason`
  step, capped at 240 characters, never deliberation).
- Maximum 6 tool rounds. Reaching the cap without `submit_triage` is a failure → 503, not a
  partially-guessed report.
- Per-call timeout 60 s; whole-request budget 110 s.
- A tool that returns `{"error": ...}` is recorded as a real observation and the model may adapt; it
  does not abort the loop.
- Duplicate identical tool calls are answered from the recorded observation without re-running the
  tool, and still recorded, so a stuck model cannot burn the budget.
