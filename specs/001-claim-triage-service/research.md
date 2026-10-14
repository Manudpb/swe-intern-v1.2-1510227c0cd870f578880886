# Phase 0 Research: Home-Damage Claim Triage Service

**Date**: 2026-10-14 | **Plan**: [plan.md](./plan.md)

The Technical Context carried no `NEEDS CLARIFICATION` markers — the user fixed the stack. What
needed resolving was *how* each choice binds to the supplied packet, and three questions the spec
deliberately left to the plan. Sources are local and authoritative: `API_ACCESS.md`, `ACCESS.json`,
`starter-kit/scripts/check_claude_access.py`, `api-contract/openapi.yaml`, the lookup tables, and
the public checks in `auto-grader/`.

---

## D1. Claude transport through the Portkey gateway

**Decision**: Use the `anthropic` SDK with the gateway **root** as `base_url`, the **unprefixed**
model id, and the provider route in a default header:

```text
base_url        = PORTKEY_BASE_URL with a trailing "/v1" removed   -> https://portkey.bain.dev
api_key         = PORTKEY_API_KEY                                   (SDK sends it as x-api-key)
default_headers = { "x-portkey-api-key": <key>, "x-portkey-provider": "@anthropic---tak-aa853e" }
model           = "claude-opus-5"                                   (route's part after "/")
```

`CLAUDE_MODEL_ROUTE` in `starter-kit/.env` holds `@anthropic---tak-aa853e/claude-opus-5`; the
application splits it on the first `/` into the provider header and the model id. The SDK appends
`/v1/messages` itself, so passing the root yields exactly the URL the packet's own check uses.

**Rationale**: `API_ACCESS.md` states the rule ("gateway root **without /v1**, the unprefixed Claude
model ID and the supplied provider route in `x-portkey-provider`"), and
`starter-kit/scripts/check_claude_access.py:portkey_target` already implements it against the live
gateway — `gateway.removesuffix("/v1") + "/v1/messages"` with headers `x-api-key`,
`x-portkey-api-key` and `x-portkey-provider`. Reusing a verified shape removes the most likely
source of an avoidable 401/404 on the first paid call.

**Alternatives considered**: The OpenAI-compatible interface with `PORTKEY_BASE_URL` as-is and the
full `@provider/model` route — valid per `API_ACCESS.md`, and the route `ACCESS.json` labels
`application` (gpt-5.5) uses it. Rejected because the user chose Claude, and mixing the two
conventions (prefixed route vs. provider header) is the classic way to produce a confusing 404.
`CLAUDE_MODEL_ROUTE` is read from `.env` with `ACCESS.json`'s `models.claude` as the fallback, so the
route is never hardcoded.

**Risk**: this is the one thing no free test can prove. The FakeLLM compensates by rejecting request
shapes the real gateway would reject (see D11), and a single capability probe
(`make check-claude-access`, paid, asked for first) confirms the live path early.

---

## D2. The trace/report consistency invariant

**Decision**: The orchestrator — not the model — writes the report's money and scope. After the loop
ends, the service takes the **last successful `estimate_repair_cost` observation** and copies:

- `triage_assessment.estimated_repair_cost.min/max` ← that observation's `min`/`max`
- `triage_assessment.damage_type` / `severity` / `affected_areas` ← that call's **arguments**,
  verbatim and in order

and intersects the model's cited claim ids with the set of ids actually returned by successful
`search_past_claims` observations, dropping any id that was never retrieved. If the loop never
produced a successful cost call, the request fails rather than returning a model-authored number.

**Rationale**: three separate spec requirements (FR-015 cost from the table, FR-012 areas counted
once, FR-024 trace agrees with report) collapse into one enforceable rule, and
`auto-grader/trace_checks.py` checks precisely this: `arguments[field] == assessment.get(field)` for
damage type, severity and affected areas, `report.cost == observation.cost`, and every cited claim
id present in a retrieved set. Equality is by value including list order, so the report must *copy*
the arguments rather than restate them. Enforcing it in one place makes it a unit test on
`domain/report.py` instead of a hope about prompt obedience.

**Alternatives considered**: Asking the model to restate scope and cost consistently in its final
answer and validating afterwards — rejected because it converts a deterministic guarantee into a
retry loop, costing paid calls for a problem that does not need the model at all.

---

## D3. Where the model's structured output comes from

**Decision**: Four tools. Three are the required capabilities (`search_past_claims`,
`estimate_repair_cost`, `check_coverage`); the fourth, `submit_triage`, is the terminal action whose
input schema *is* the report schema. The loop ends when the model calls `submit_triage` (or when the
round cap is reached, which is a failure). Its observation is `{"accepted": true}`.

**Rationale**: a tool call is the SDK's own structured-output mechanism — schema-validated by the
provider, with no JSON-in-prose parsing and no markdown fences to strip. It also keeps the trace
uniform: every act step has a tool name, non-empty inputs and a paired observation, which is what
`trace_checks.validate_trace` requires of *every* act step.

**Alternatives considered**: a final free-text turn parsed as JSON (brittle, needs repair prompts);
`response_format`-style forcing (not available on this interface in the same shape). A fifth tool for
PDF text was rejected — the document is extracted once up front and passed in the opening message,
because it is evidence the model needs before it can plan, not something it should have to ask for.

---

## D4. Making the ReAct loop observable without leaking private reasoning

**Decision**: The system prompt requires one short sentence before each tool call naming *what the
model needs and why* — an action-purpose summary, capped at 240 characters when recorded. The
recorder emits that text as a `reason` step, the tool call as `act`, and the real tool return as
`observe`. When a turn arrives with a tool call and no text, the recorder synthesizes a purpose line
from the tool name and arguments, so the `reason → act → observe` triple always exists. Extended
thinking is never enabled, and no assistant text is recorded beyond those capped summaries.

**Rationale**: FR-025 forbids exposing private model reasoning while FR-023/FR-024 and the public
checks require ≥2 of each step kind plus at least one consecutive `reason, act, observe` triple.
Instructing a *purpose* line (not deliberation) satisfies both; synthesizing a fallback removes the
dependence on the model always complying.

**Alternatives considered**: recording the raw assistant text blocks — rejected as the direct route
to leaking reasoning. Emitting a `reason` step with boilerplate text — rejected because
`validate_trace` requires non-empty content and a reviewer would see it is noise.

---

## D5. Area normalization

**Decision**: One pure function, `domain/areas.normalize_areas(raw) -> list[str]`, applied before the
cost call:

1. lowercase, trim, collapse whitespace and hyphens to `_` (so `Dining Room` → `dining_room`)
2. map synonyms to canonical names (`bath` → `bathroom`, `lounge`/`living` → `living_room`, …)
3. strip component suffixes that name part of a room already present (`kitchen_floor`,
   `kitchen_wall`, `kitchen_ceiling` → `kitchen`)
4. drop generic umbrellas (`interior`, `exterior`, `house`, `property`, `whole_house`) when any
   specific area survives; keep one if nothing else does
5. de-duplicate, preserving first-seen order

**Rationale**: FR-012 and the assignment both forbid counting a room twice for its floor or wall, or
a component again under a generic label, and the multiplier drives every cost figure, so an error
here is an error in the most-checked number. `trace_checks` computes the expected cost from
`max(1, len(set(lowercased, stripped arguments)))`, so normalizing *before* the call keeps the tool's
arithmetic and the checker's arithmetic identical. Order preservation matters because D2 copies the
list verbatim into the report.

**Alternatives considered**: normalizing inside the cost tool only — rejected because the report
would then carry the un-normalized list while the cost used the normalized one, breaking D2's
equality. Trusting the prompt to produce clean areas — rejected; it is a string-processing problem.

---

## D6. Cost and coverage are table arithmetic, not model output

**Decision**: `estimate_repair_cost(damage_type, severity, affected_areas)` returns
`min = min_per_area × n`, `max = max_per_area × n` where `n = max(1, distinct(affected_areas))`, read
from `tools/cost-estimator.json`, currency `USD`. Unknown damage type or severity returns
`{"error": ...}` rather than a guess. `check_coverage(policy_type, incident_category)` returns the
table's `covered`, `deductible`, `max_payout`, `notes`; an unlisted policy or category returns
`{"error": ...}`. Tables load once at startup and are treated as immutable.

**Rationale**: FR-015 through FR-018 require it, and the table's own `usage` note specifies the
multiplication rule. A recorded tool error is explicitly tolerated by `validate_trace` (it skips
error observations but still demands successful cost and retrieval evidence), so returning an error
object is safer than inventing a fallback.

**Alternatives considered**: letting the model adjust the range for "unusual" damage — rejected
outright by the constitution and the spec. Caching coverage per policy — unnecessary at this scale.

---

## D7. Local embeddings and the vector store

**Decision**: `fastembed` with `BAAI/bge-small-en-v1.5` (384 dims, cosine). The model is downloaded
**at image build time** into `/opt/fastembed` and the embedder is constructed with an explicit
`cache_dir` pointing there, so no first-run download happens at container start. Production uses the
Qdrant service at `http://qdrant:6333`, collection `historical_claims`, one point per claim record
with the claim id and resolution summary in the payload. Ingestion runs at API startup, is
idempotent (deterministic point ids derived from `claim_id`), and skips re-embedding when the
collection already holds the expected count.

**Rationale**: `API_ACCESS.md` requires local embeddings so retrieval needs no second paid
credential, and asks that the model and its first-run download be documented. An explicit `cache_dir`
is preferred over relying on an environment variable name, because the constructor argument is stable
across fastembed versions while cache env-var names have moved. `bge-small-en-v1.5` is the right size
for 30 records: ~130 MB, CPU-only, strong on short-passage retrieval.

**Embedded text per claim**: `description` + `adjuster_notes` + `damage_type` + `severity` +
`affected_areas`, joined — the fields an adjuster's query would describe. `repair_cost_actual`,
`resolution` and `fraud_indicators` stay in the payload but out of the embedded text so they cannot
distort similarity.

**Alternatives considered**: a hosted embedding route (forbidden without explicit coordinator
approval — Principle IV); `sentence-transformers` (pulls in torch, several GB, slower cold start);
`bge-base` (better quality, ~3× the size, unjustified for 30 records).

**Health signal**: `services.vector_db` reports `connected` only when the collection exists and holds
at least 80% of the knowledge-base record count — the same bar `auto-grader/tests/test_rag.py`
applies — otherwise `disconnected`.

---

## D8. The 503 question the spec left open

**Decision**: Upstream model failure, and not-yet-ready startup, answer **503** with
`{"error": "...", "message": "..."}`. `openapi.yaml` is not edited. The contract test enforces that
200/400/422 bodies match the declared schemas and that 503 is used *only* for upstream or readiness
failure — never for anything a client did.

**Rationale**: the spec's completion note flagged that the contract declares no 5xx while FR-035
requires an explicit failure. Every in-contract alternative misreports the cause: 400 blames the
adjuster's submission (and the evaluator counts it as a rejected case), 422 claims a safety failure
that never ran, 200 with defaults is precisely what FR-035 prohibits. The health 200 body pins
`status` to `healthy`, so a not-ready service cannot answer 200 truthfully either. OpenAPI responses
are additive — an undeclared status does not contradict the document — so this is the narrowest
honest deviation, and it is recorded in the plan's Complexity Tracking.

**Retry policy**: at most one retry, only for 502/503/529 and timeouts, with a short fixed backoff.
Never for 429, 401 or 403 — the constitution forbids looping on an exhausted allowance, and a 429
surfaces immediately as 503 with a message telling the operator to pause.

---

## D9. Safety checking: two detectors, then rewrite, sanitize, refuse

*Operator decision, 2026-10-14 — this supersedes an earlier draft that made the LLM review optional
and off by default.*

**Decision**: `safetyChecker` always runs **both** detectors over the report's `damage_description`
and `recommendation`, and escalates through a fixed four-stage ladder.

**Detectors** (both run on every report; no feature flag):

1. **Deterministic rule pass** — lexical and structural patterns for the five limits: coverage
   promises ("is covered", "will be paid", "guarantee"), legal advice ("you should sue", "legal
   action", "consult counsel"), settlement amounts (currency figures anywhere outside the structured
   cost object), fault attribution ("at fault", "negligent", "caused by the neighbour"), emotional
   language ("devastating", "tragic", "heartbreaking"). Each hit records the limit **and the
   character span** that triggered it.
2. **LLM review on low effort** — one Claude call on the `safety` route, carrying only the two text
   fields and returning the five booleans plus, for each violation, the offending sentence. Low
   effort means: extended thinking disabled, `temperature = 0`, `max_tokens = 300`, no images, no
   retrieval context, a short fixed system prompt, and the verdict returned through a forced tool
   call so nothing has to be parsed from prose. This is the cheapest shape the interface allows
   while still being a semantic judgement.

**Verdict composition**: a limit is satisfied only if **both** detectors say so. The flags are the
intersection — a disagreement resolves against the report, never in its favour.

**Ladder** (bounded, at most three safety-route calls per triage):

| Stage | Action | Model calls |
|---|---|---|
| 1 | Both detectors run | 1 (review) |
| 2 | If any limit failed: **one rewrite**, naming the broken rules and quoting the offending sentences, asking for neutral replacement text that preserves the factual content | 1 (rewrite) |
| 3 | Re-run both detectors on the rewritten text | 1 (re-review) |
| 4 | If still failing: **sanitize** — drop the specific sentences the detectors named, then re-run the deterministic pass and verify the named spans are gone | 0 |
| 5 | If a named span cannot be removed without emptying a required field, or the deterministic pass still fails: **422 `SafetyError`** with the failing flags | 0 |

Clean path: 1 safety call. Violating path: 3 (review, rewrite, re-review), then free stages. No
stage repeats, so the attempt count is bounded by construction (FR-028).

**Why no LLM re-review after sanitization**: stage 4 removes exactly the spans the detectors named,
so each recorded violation is eliminated by construction, and dropping a sentence cannot introduce a
new one. The post-sanitize check is therefore deterministic plus a span-removal assertion. This is a
deliberate cost/confidence trade-off and `RESULTS.md` will say so.

**Rationale**: the deterministic pass is exhaustively unit-testable with no model call — one failure
fixture per limit, which is what US6 requires — while the LLM review catches the paraphrased
violation that no word list will ever match ("you can rest assured this will be taken care of" is a
coverage promise with none of the trigger words). Running both and intersecting means the cheap
detector cannot be fooled by paraphrase and the expensive one cannot be fooled by a pattern it
happens to tolerate. Spec invariant I5 — a delivered report has all five flags true — is now backed
by two independent judgements rather than a word list.

**Cost accepted**: this adds 1 paid call to every triage and 3 to a violating one, so a triage is
5–6 calls clean and up to 8 when the first draft breaks a rule. Across 35 accuracy cases that is
roughly 40 extra calls per full grade, on an allowance shared with coding (Principle III). The
operator took that trade knowingly in exchange for a semantic gate on every delivered report; the
budget protections stay elsewhere — image downscaling, the 6-round loop cap, `max_tokens` caps, and
the single-probe/smoke/grade ladder.

**Alternatives considered**: an LLM judge as the *only* gate (non-deterministic, untestable without
paid calls, and nothing left to unit-test); the deterministic pass alone (the original draft —
rejected by the operator because paraphrased violations pass it); regenerating until clean (violates
the bounded-attempt requirement); sanitizing before attempting a rewrite (throws away the better
outcome — a rewrite preserves the adjuster's information, sanitization just deletes it).

**Test consequence**: because the safety route now fires on every triage, every integration test's
FakeLLM script must include a `safety` turn — and the fake raises on an exhausted script, so a
missing turn fails loudly rather than silently skipping the gate. Tests cover: both detectors
agreeing, each detector catching what the other misses, the rewrite succeeding, the rewrite failing
into sanitization, and sanitization failing into 422.

---

## D10. Intake validation

**Decision**: One Claude call per submission, images attached, returning the four booleans through a
forced tool call. The prompt states the hard rules the fixtures encode: a payment card — including a
synthetic test card — sets `no_pii_detected` false; an image too blurry or a screenshot of text sets
`is_valid_image` false; a photo with no property or structural damage sets `is_property_damage`
false. For text-only submissions no vision call is made for image usability: `is_valid_image` is
`null` and the other three are judged from the text. Any false flag → 400 `ValidationError` with the
flags and a plain-language `message`, and the pipeline stops before any tool runs.

**Rationale**: FR-004 through FR-007 and US2. Running intake *before* the loop means the five
rejection fixtures cost one call each instead of five. The 400 body carries both the machine flags
and prose because the spec's assumption says neither alone is sufficient — and
`auto-grader/tests/test_guardrails.py` asserts a non-empty `message` string and the decisive flag
being `false` with no `triage_assessment` present.

**Alternatives considered**: folding intake into the ReAct loop as a tool — rejected: it delays
rejection until after billable tool rounds and muddles two agents the assignment names separately.

---

## D11. FakeLLM: what "rejects request shapes the real model refuses" means

**Decision**: `FakeLLM` implements the `LLMClient` port and is strict about the request, not just
generous with the response. It routes by a marker in the system prompt (`intake` / `triage` /
`safety`), pops the next scripted turn for that route, records every request kwarg for assertions,
and **raises** when the request would be rejected by the real API:

- `max_tokens` missing or non-positive
- `model` containing `@` or `/` (that is the OpenAI-style prefixed route, wrong for this interface)
- a `tool_result` block whose `tool_use_id` matches no preceding `tool_use`
- an assistant turn ending in `tool_use` that is not followed by a user turn carrying its
  `tool_result`
- an empty `content` list, an empty text block, or a message with an unknown `role`
- an image block whose `media_type` is outside `image/jpeg|png|gif|webp`, or that carries raw bytes
  instead of base64
- a `tools` list containing two tools with the same name, or a tool whose `input_schema` is not an
  object schema
- the script being exhausted for that route (a silent extra call is a bug, not a pass)

**Rationale**: the whole risk of a free suite is that it proves the orchestration while the real
request shape is malformed — exactly the failure that only shows up on a paid call. Encoding the
provider's known constraints into the fake moves that class of bug into `make test`. The recorded
kwargs also let tests assert the things that matter but are invisible in the response: that the
unprefixed model id was used, that `x-portkey-provider` was set, that images were downscaled before
upload, and that the system prompt never contains the credential.

**Alternatives considered**: `respx`/HTTP-level mocking of the SDK (tests the SDK rather than the
application, and ties the suite to the SDK's wire format); recording real responses as cassettes
(requires a paid call to record, and re-recording on every prompt change).

---

## D12. Contract validation mechanism

**Decision**: Parse `api-contract/openapi.yaml` with `PyYAML`, build a `referencing` registry for the
`#/components/schemas` pointers, and validate with `jsonschema` using the Draft 2020-12 validator and
a format checker enabled for `date-time`. One helper — `assert_conforms(path, method, status, body)`
— is called by every API test, success and failure alike.

**Rationale**: OpenAPI 3.1 schemas *are* JSON Schema 2020-12, so a plain validator handles
`type: [boolean, "null"]` and the nested `$ref`s without a translation layer. Enabling the `date-time`
format checker makes the trace timestamp requirement real rather than decorative. Principle I asks
for automated validation of every response, not a subset.

**Alternatives considered**: `openapi-core` (heavier, and 3.1 support has lagged); `schemathesis`
(property-based fuzzing is valuable but wants a live server and would drive paid calls unless every
operation is stubbed); hand-written assertions (the drift this is meant to catch).

---

## D13. Test doubles for retrieval

**Decision**: `QdrantClient(":memory:")` — the client's local mode, same API as the server — loaded
with the **real** 30 knowledge-base records, plus a deterministic embedder: tokens are hashed into a
384-dim vector with signed buckets and L2-normalized, so cosine similarity tracks term overlap. The
cost and coverage tables are the real files, unmodified.

**Rationale**: Principle VI requires an in-memory store and no network; using the real corpus and the
real tables keeps the tests meaningful (US3's "a burst-pipe query ranks a water-damage claim first"
is a genuine assertion, not a tautology against a stub). Term-overlap similarity is strong enough for
that ordering assertion while staying fully deterministic across machines.

**Alternatives considered**: a fake vector store returning a fixed list (would make every retrieval
test vacuous); running real fastembed in tests (loads 130 MB of weights, slows the suite, and makes
scores depend on the model version).

---

## D14. UI shape and the no-CORS path

**Decision**: A second Compose service from the same image runs a small FastAPI + Jinja2 app on port
3000. `GET /` renders the form (file input accepting multiple images, a textarea for the description,
a file input for the PDF, a `<select>` for policy type, a submit button). The form posts to the UI
app, which forwards the multipart body to `http://api:8000/api/v1/claims/triage` with `httpx` and
renders the report — or, on 400, the stated reason and the failed checks. The trace panel is filled
by a small `fetch()` against the UI's own proxy path `/api/v1/agent/trace/{id}`.

**Rationale**: server-side forwarding means the browser only ever talks to its own origin, so no CORS
configuration exists to get wrong, and the page works with JavaScript disabled for everything except
the trace panel. The public UI checks look for a file input, a text input, a submit control, a
results area and a reference to `/api/` or `fetch(` in the page — all of which this shape has
naturally rather than by accommodation. Sharing the image avoids a second dependency set for one
page.

**Alternatives considered**: static HTML served by nginx with the browser calling port 8000 directly
(needs CORS on the API and exposes the API origin in the page); a React SPA (a second toolchain, and
the public check explicitly treats a client-rendered shell as insufficient evidence without browser
review).

---

## Resolved: no open clarifications

Both decisions the spec deferred are now settled — the upstream-failure status code (D8) and the
safety-failure behaviour (D9, implementing the spec's stated assumption with a default that protects
the allowance). No `NEEDS CLARIFICATION` remains.

**Carried risks**, to be stated in `RESULTS.md` rather than hidden:

1. The live gateway request shape is unproven until the one capability probe runs (D1/D11).
2. Safety has a semantic detector on every report, but no LLM re-review after sanitization — the
   post-sanitize guarantee is span removal plus the deterministic pass, not a fresh judgement (D9).
   The safety ladder also adds 1–3 paid calls per triage, which is the budget cost of that gate.
3. Triage accuracy against the fixtures is unmeasured until a paid run; the free suite proves
   structure, consistency and failure handling, not classification quality.
