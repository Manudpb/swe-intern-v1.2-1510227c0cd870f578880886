# Results

Measured values only. Anything not measured says **not measured** — no live-provider numbers
are reported from mocked calls.

## Run/test instructions

From `starter-kit/`:

```sh
docker compose up --build -d --wait --wait-timeout 180   # free
make health                                              # free
make test                                                # free: 234 tests, no paid calls
make setup                                               # PAID: readiness check, then up
make grade-smoke                                         # PAID: 3 positive cases
make grade                                               # PAID: all 35 accuracy cases
```

API at <http://localhost:8000/api/v1/health>, UI at <http://localhost:3000>.

## Models and embedding method

- **LLM**: `claude-opus-5` through the funded Portkey gateway, Anthropic Messages API. Gateway
  root without `/v1`, unprefixed model id, provider route in `x-portkey-provider`.
- **Embeddings**: `fastembed` + `BAAI/bge-small-en-v1.5`, 384-d, cosine, run locally. Baked into
  the image at build time (~130 MB), so no download at container start.
- **Vector store**: Qdrant, collection `historical_claims`.
- **Per-triage model calls**: 1 intake + 3–4 loop rounds + 1 safety review ≈ 5–6, rising to 8
  on the safety rewrite path. Configured caps allow a worst case of 10.

## Test cases exercised, passing checks and remaining failures

**234 tests, 234 passing, 0 failing**, run inside the api image via `make test` with no network
and no paid calls (fake LLM, deterministic fake embedder, in-memory Qdrant, real cost/coverage
tables, real 30-record corpus).

| Area | Count | Covers |
|---|---|---|
| Contract conformance | 17 | Every endpoint, every declared status, validated against `openapi.yaml`; negative cases prove the validator bites |
| Trace invariants | 20 | Numbering, act/observe pairing, ≥2 of each kind, reason→act→observe cycle, cost agreement, no credential, no deliberation |
| Safety | 28 | One fixture per limit, both detectors composed, rewrite → sanitize → 422 ladder, ≤3 safety calls |
| Cost, coverage, areas | 30 | Table arithmetic to the cent, quote cannot move the figure, area collapsing, unknown keys error rather than guess |
| Intake and rejection | 11 | Each of the four checks, text-only null, one-call cost of a rejection |
| Retrieval and ingestion | 16 | Real corpus relevance, no fabricated ids, idempotent ingestion, health signal |
| Multimodal and evidence | 20 | Four input combinations, repeated views, PDF widening scope, unreadable PDF |
| UI | 12 | Form controls, report rendering, trace panel, 400/422/503 rendering |
| FakeLLM request-shape rules | 26 | Ten shapes the real Messages API refuses, two added after the live run caught them |
| Settings, retry, budget | 25 | Redaction, one-retry policy, never retry 429, request-budget 503 |


## Automated report location

`auto-grader/results/grade_report.json`, written by the full run described below. Per-case timings are in `auto-grader/results/accuracy_full.json`.

##
## Accuracy results on the provided development set

**One full `make grade` run, with explicit approval. 20.00/20 automated, every category at
100%.** 35 of 35 accuracy cases attempted, **35 returned, 0 failed, every response HTTP 200**.

| Category | Checks | Score | Weight | Earned |
|---|---|---|---|---|
| infrastructure (incl. UI + multimodal) | 14/14 | 100% | 3 | **3.0** |
| agent_loop (ReAct trace + consistency) | 1/1 | 100% | 6 | **6.0** |
| rag (store, ids, relevance) | 3/3 | 100% | 4 | **4.0** |
| accuracy (35 cases) | 5/5 | 100% | 4 | **4.0** |
| guardrails (intake + output safety) | 7/7 | 100% | 3 | **3.0** |
| **total** | | | **20** | **20.00** |

Accuracy metrics against the published acceptance thresholds:

| Metric | Measured | Minimum | Margin |
|---|---|---|---|
| Damage-type correctness | **0.971** (34/35) | 0.50 | 1.9x |
| Severity score (exact=1, adjacent=0.5) | **0.814** | 0.40 | 2.0x |
| Repair-cost midpoint accuracy | **0.522** | 0.30 | 1.7x |

Cost is the lowest of the three by construction, not by accident: it is derived from the table
using the assessed damage type, severity and distinct-area count, so it inherits severity error.
Severity at 0.814 means a number of cases landed adjacent rather than exact, and one severity
level moves the table's midpoint by roughly 3-4x, which caps what the cost metric can reach.
Improving cost means improving severity, not touching the arithmetic.



## End-to-end P50 latency

**P50 48.3 s across 35 live cases** (n=35, measured client-side by the grader: upload, model
calls, retrieval and tool work, excluding its own assertion time). Range **29.5 s to 72.6 s**.

That is roughly double the 10-28 s the starter README assumes, and the slowest case consumed
about 60% of the grader's 120 s per-case budget. No case timed out, but the margin is narrower
than I would want in production. The cost is structural: 5-6 sequential model calls per triage,
of which the safety review adds one and the rewrite path would add two more.

## Important assumptions, limitations and unfinished requirements

- **The scores are from one run on the public fixtures.** 35 cases is the whole published
  positive set, so there is no held-out data: these numbers show the system works on the set it
  was developed against, not how it generalises. Interviewers run a clean evaluator copy and may
  rename inputs or add cases, and I would expect some movement if they do.
- **Severity is the weakest link.** At 0.814 it is comfortably above the bar but it is what caps
  the cost metric, and it is the judgement most sensitive to prompt wording.
- **Latency is about 2x the starter README's assumption** (p50 48.3 s against 10-28 s), with the
  slowest case at 72.6 s against a 120 s ceiling.
- **No LLM re-review after sanitization.** Stage 4 deletes exactly the spans the detectors
  quoted, so the post-sanitize guarantee is span removal plus the deterministic pass, not a
  fresh semantic judgement. A deliberate cost trade.
- **Default safety rules are lexical** for the free detector; the semantic detector is the
  Claude review, which runs on every report.
- **Reports are in memory**, lost on restart. The vector index persists.


- **No authentication**; single-tenant pilot.
- **Urgency is derived**, not looked up .



## What I would do next

2. **Persist reports** (SQLite or Postgres) so a restart does not lose an adjuster's work, and
   add pagination for a queue view.
3. **Cache intake by image hash.** The same photo resubmitted should not pay for screening twice.
4. **Make the safety reviewer or the intake validator cheaper**, by batching the two text fields of several reports into
   one call, or by routing it to a smaller approved model.
5. **Stream the trace** to the page over SSE so an adjuster watches the loop instead of waiting.
6. **Confidence on the report**, derived from retrieval scores and evidence completeness, so an
   adjuster can see which assessments to double-check.