# Quickstart: running and validating the claim triage service

**Date**: 2026-10-14 | **Plan**: [plan.md](./plan.md)

All commands run from `software-engineering-take-home/starter-kit/` unless stated otherwise.

> **Paid-command warning.** `make setup`, `make check-claude-access`, `make grade-smoke` and
> `make grade` all spend the shared $30 allowance. Constitution Principle III requires an explicit
> go-ahead from the operator for each individual run. `make test` is free and offline — use it as
> the default loop.

## Prerequisites

- Docker Desktop with Compose v2 (WSL2 backend on Windows)
- `starter-kit/.env` present, carrying `PORTKEY_API_KEY`, `PORTKEY_BASE_URL`, `LLM_MODEL` and
  `CLAUDE_MODEL_ROUTE` (supplied; never printed, never committed)
- Python 3.10+ on the host only for the readiness check script
- Network access on first build: the image downloads `BAAI/bge-small-en-v1.5` (~130 MB) at build
  time so no download happens at container start

## The free loop

```sh
docker compose build api          # builds the image, bakes the embedding model
make test                         # pytest inside the api image: no network, no paid calls
```

`make test` runs `docker compose run --rm --no-deps api python -m pytest -q`. `--no-deps` is
deliberate: the suite must pass with Qdrant down, because it uses an in-memory store.

Expected: all tests pass with no outbound network. If a test needs a credential or a live service,
that is a bug in the test, not a missing setup step.

## Bringing the system up *(paid — ask first)*

```sh
make setup                        # readiness check, then compose up --wait, then make health
```

`make setup` runs `scripts/check_claude_access.py` first — **one small paid Claude request** — and
stops the whole startup if access fails. To bring the stack up without spending anything:

```sh
docker compose up --build -d --wait --wait-timeout 180
make health
```

Then:

- API health: <http://localhost:8000/api/v1/health> → `{"status":"healthy","services":{"vector_db":"connected","llm":"configured"}}`
- UI: <http://localhost:3000>
- Qdrant: <http://localhost:6333/collections> → `historical_claims` with 30 points

First startup embeds 30 records; subsequent starts detect the populated collection and skip
re-embedding.

## Validating each user story

Numbers refer to the stories in [spec.md](./spec.md). Everything in the "free" column is covered by
`make test`; the paid rows need the stack up and an approved run.

| Story | Validation | Paid? |
|---|---|---|
| US1 triage report | `tests/integration/test_triage_flow.py` — scripted FakeLLM turns produce a full report; fetch by id returns identical content; unknown id → 404; LLM raising → 503 | free |
| US2 rejections | `tests/integration/test_intake_rejection.py` — each of the four flags false → 400 with prose `message` and no `triage_assessment`; text-only → `is_valid_image` null | free |
| US3 precedent | `tests/integration/test_retrieval.py` — real 30-record corpus in `:memory:` Qdrant; burst-pipe query ranks a water-damage claim first; ids all real; empty-store path | free |
| US4 money and coverage | `tests/unit/test_cost.py`, `test_coverage.py`, `test_areas.py` — table arithmetic to the cent; contractor-quote PDF does not move the range; `["kitchen","kitchen floor","interior"]` → 1 area; missing policy → error not guess | free |
| US5 trace | `tests/integration/test_trace.py` + `tests/unit/test_report_invariants.py` — step numbering, act/observe pairing, ≥2 of each kind, the reason→act→observe triple, cost agreement, no credential anywhere | free |
| US6 safety | `tests/unit/test_safety.py` + `tests/integration/test_safety_ladder.py` — one fixture per limit for the rule pass; each detector catching what the other misses; rewrite succeeds; rewrite fails into sanitization; sanitization fails into 422; clean text untouched | free |
| US7 evidence | `tests/integration/test_multimodal.py` — four input combinations, repeated views do not multiply areas, PDF widens scope, unreadable PDF noted | free |
| US8 web page | `tests/integration/test_ui.py` — form controls present, result region renders report fields, 400 renders the reason, trace panel path proxies | free |

### End-to-end spot check *(paid — ask first)*

```sh
# A real submission through the real model
curl -s -X POST http://localhost:8000/api/v1/claims/triage \
  -F "image=@data/test-images/IMG_001.jpg" \
  -F "description=Burst pipe under kitchen sink, water pooling on floor" \
  -F "policy_type=standard_homeowner" | tee /tmp/triage.json

CLAIM=$(python -c "import json;print(json.load(open('/tmp/triage.json'))['claim_id'])")
curl -s http://localhost:8000/api/v1/claims/$CLAIM
curl -s http://localhost:8000/api/v1/agent/trace/$CLAIM
```

Expect `water_damage`, `moderate`, `["kitchen"]`, cost `2000`–`8000`, all four intake flags true, all
five safety flags true, and a trace whose cost observation matches the report.

### Public acceptance checks *(paid — ask first, one rung at a time)*

```sh
make grade-smoke     # three varied positive cases; diagnostic only
make grade           # all 35 accuracy cases, ~6-16 minutes; run once, late
```

Results land in `../auto-grader/results/grade_report.json`, with incremental per-case timings in
`accuracy_full.json` / `accuracy_smoke.json`.

## Troubleshooting

| Symptom | Check |
|---|---|
| `vector_db: disconnected` | `docker compose logs api` for ingestion errors; `curl localhost:6333/collections` for the collection and its point count |
| 401/403 from the gateway | the key, `PORTKEY_BASE_URL` and `CLAUDE_MODEL_ROUTE` in `.env`. Share only a redacted error and the packet id with support. Never print the key |
| 429 or exhausted budget | stop. Do not retry, do not buy credit. Contact support |
| 503 on triage | the model path is unreachable or timed out; the message says which. The service is refusing to guess, which is the designed behaviour |
| Slow first build | the embedding model download; it is cached in the image layer afterwards |
| `make test` wants network | a regression in dependency injection: some code path is constructing a real client instead of using `deps` |

## Before submitting

- `make test` green
- `docker compose up` from a clean checkout reaches a working submission through the page
- `README.md` (architecture, model choice, setup, trade-offs, limitations, next steps),
  `AI_USAGE.md`, `RESULTS.md` written
- `.env`, credentials and `.interview-tools/` excluded from the ZIP; `PACKET.json` retained
- no ground-truth path mounted into any container (`grep -n ground-truth docker-compose.yml`
  returns nothing)
