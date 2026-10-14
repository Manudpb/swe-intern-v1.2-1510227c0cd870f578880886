# Implementation Plan: Home-Damage Claim Triage Service

**Branch**: `001-claim-triage-service` | **Date**: 2026-10-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-claim-triage-service/spec.md`

## Summary

A FastAPI service that triages home-damage claims: it screens a submission (photos, description,
optional PDF) with a vision-backed intake agent, then runs its own ReAct loop over Claude's native
tool calling — searching a Qdrant index of 30 historical claims, pricing repairs from the company
cost table, and checking the coverage table — and returns a contract-shaped report with an
inspectable trace. Two independent safety detectors — a deterministic rule pass and a low-effort LLM
review — gate the report text before delivery, escalating through rewrite, sanitization and refusal.
A second
container serves a server-rendered HTML page on port 3000 that proxies to the API.

The design turns the spec's consistency requirements into one enforced invariant: **the final
report's scope and cost are copied from the last successful `estimate_repair_cost` call recorded in
the trace**, never re-stated by the model. That single rule satisfies FR-015 (cost from the table,
not the model), FR-024 (trace agrees with report) and FR-012 (areas counted once) at the same time,
and it is cheap to assert in tests.

Everything the test suite needs is injected through `create_app(deps)`, so the whole suite runs
offline with a fake LLM, a deterministic fake embedder and an in-memory Qdrant — no paid calls.

## Technical Context

**Language/Version**: Python 3.12 (slim base image)

**Primary Dependencies**: FastAPI + Uvicorn (API and UI), `anthropic` SDK (Messages API pointed at
the Portkey gateway), `qdrant-client` (server mode in production, local `:memory:` mode in tests),
`fastembed` with `BAAI/bge-small-en-v1.5` (384-dim local embeddings, baked into the image), `pypdf`
(PDF text), `Pillow` (image downscale), `pydantic` + `pydantic-settings`, `Jinja2` (UI templates),
`httpx` (UI → API). Test-only: `pytest`, `pytest-asyncio`, `jsonschema`, `PyYAML`.

**Storage**: Qdrant collection `historical_claims` (30 points, cosine, 384 dims) for retrieval;
reports and traces in a bounded in-memory store for the process lifetime (spec assumption — no
durable report storage in this pilot). The cost and coverage tables are read-only JSON, loaded once
at startup.

**Testing**: `pytest` run inside the API image via `make test`, with zero network and zero paid
calls. Three substitutions carry the suite: `FakeLLM` replaying SDK-shaped responses, a
deterministic bag-of-words embedder, and `QdrantClient(":memory:")` loaded with the real knowledge
base. The real cost and coverage tables are used unmodified. Every API response is validated against
`openapi.yaml`.

**Target Platform**: Linux containers via Docker Compose on a developer machine; API on port 8000,
UI on port 3000, Qdrant on 6333.

**Project Type**: Containerized web service (HTTP API) with a thin server-rendered UI, both built
from one image.

**Performance Goals**: p50 triage under 30 s; hard per-request budget of 110 s so a submission always
answers inside the evaluator's 120 s timeout. Target 5–6 model calls per triage (1 intake + 3–4 loop
rounds + 1 safety review), rising to 8 when the first draft breaks a safety rule and the rewrite
path runs. Images are downscaled before upload to hold input tokens down, and the safety calls are
text-only on low effort.

**Constraints**: One external runtime dependency (the funded model credential). No paid call in any
automated test. Embeddings local, model weights baked in so first run needs no download. Ground
truth never mounted into a container. Credentials never printed, logged or returned. Unbounded
retry loops prohibited; no retry at all on 429/401/403.

**Scale/Scope**: Single-tenant internal pilot. One adjuster at a time; the evaluator's heaviest load
is 35 sequential submissions. 30 historical claims, 6 damage types, 5 policy types, ~9 modules,
~40 tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Contract Fidelity | `openapi.yaml` is never edited; all four endpoints at published paths; pydantic response models mirror the schemas; every response asserted against the contract in tests | **PASS** — with one documented addition (503), see Complexity Tracking |
| II. Reproducible Containerized Delivery | `docker compose up` brings up qdrant + api + ui; UI on 3000, API on 8000; `make setup` → `make health` green; one credential is the only external dependency | **PASS** |
| III. Human-Gated Paid Operations | No test, build step or startup path makes a paid call. The only paid commands remain `make check-claude-access`, `make grade-smoke` and `make grade`, each run only on request | **PASS** |
| IV. One Funded Credential, Local Embeddings | Anthropic SDK against `PORTKEY_BASE_URL` with `x-portkey-provider`; credentials arrive via Compose `env_file`; fastembed runs locally with weights baked in; no second paid credential | **PASS** |
| V. Secret and Answer-Key Isolation | Compose mounts `data/knowledge-base` and `tools` only — never `data/` wholesale, which would carry `ground-truth/` in; settings redact; a log filter scrubs the key; a test asserts the compose mounts stay clean | **PASS** |
| VI. Free, Injected, Failure-Covering Tests | `create_app(deps)` with ports for LLM, embedder, vector store, clock and id factory; failure paths covered for 400, 404, 422 and 503; contract validation on every response | **PASS** |

**Post-Phase-1 re-check**: PASS. The design added no new dependency on a paid service, no new
credential, and no runtime path that reads ground truth. The one deviation (an undeclared 503) was
identified before Phase 0 and is justified below rather than discovered late.

## Project Structure

### Documentation (this feature)

```text
specs/001-claim-triage-service/
├── plan.md              # This file (/speckit-plan command output)
├── research.md           # Phase 0 output — 14 decisions with rationale
├── data-model.md         # Phase 1 output — entities, invariants, normalization rules
├── quickstart.md         # Phase 1 output — how to run and validate
├── contracts/            # Phase 1 output
│   ├── http-api.md       #   binding to openapi.yaml + the 503 addition
│   ├── agent-tools.md    #   the four tool schemas the model sees
│   ├── internal-ports.md #   injected seams and the FakeLLM rejection rules
│   └── ui-contract.md    #   what the page must contain and do
├── checklists/
│   └── requirements.md   # spec quality checklist (/speckit-specify output)
└── tasks.md              # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
software-engineering-take-home/starter-kit/
├── docker-compose.yml                  # EDIT: add api + ui services beside qdrant
├── Makefile                            # EDIT: real `test` target; keep paid targets untouched
├── api-contract/openapi.yaml            # READ-ONLY — the authority (Principle I)
├── data/knowledge-base/                 # mounted read-only into api
├── tools/                               # cost + coverage tables, mounted read-only
└── app/                                 # NEW — one image, two entrypoints
    ├── Dockerfile                       # bakes the fastembed model at build time
    ├── requirements.txt
    ├── requirements-dev.txt
    ├── pyproject.toml                   # pytest config
    ├── src/claim_triage/
    │   ├── main.py                      # create_app(deps) + prod wiring
    │   ├── settings.py                  # env parsing, redaction, log scrubber
    │   ├── deps.py                      # Deps dataclass + Protocol ports
    │   ├── api/
    │   │   ├── routes_claims.py          # POST triage, GET claims/{id}
    │   │   ├── routes_trace.py           # GET agent/trace/{id}
    │   │   ├── routes_health.py
    │   │   ├── schemas.py                # pydantic mirrors of openapi.yaml
    │   │   └── errors.py                 # 400 / 404 / 422 / 503 bodies
    │   ├── agents/
    │   │   ├── intake.py                 # intakeValidator (vision)
    │   │   ├── triage.py                 # triageAgent (ReAct loop)
    │   │   ├── safety.py                 # safetyChecker (deterministic + optional LLM)
    │   │   └── prompts/
    │   ├── llm/
    │   │   ├── ports.py                  # LLMClient protocol
    │   │   └── anthropic_portkey.py      # gateway root, provider header, retry policy
    │   ├── tools/
    │   │   ├── registry.py               # name → schema + handler
    │   │   ├── search_past_claims.py
    │   │   ├── estimate_repair_cost.py   # the only source of money
    │   │   ├── check_coverage.py
    │   │   └── submit_triage.py          # terminal structured answer
    │   ├── rag/
    │   │   ├── embedder_fastembed.py
    │   │   ├── store_qdrant.py
    │   │   └── ingest.py                 # idempotent upsert at startup
    │   ├── evidence/
    │   │   ├── images.py                 # validate, downscale, base64
    │   │   └── pdf.py                    # pypdf text, truncated
    │   ├── domain/
    │   │   ├── areas.py                  # normalize + collapse to distinct areas
    │   │   └── report.py                 # assembly + the trace/report invariant
    │   ├── trace/recorder.py
    │   ├── store/reports.py              # bounded in-memory, lifetime of process
    │   └── ui/
    │       ├── app.py                    # port 3000, proxies to api:8000
    │       ├── templates/
    │       └── static/
    └── tests/
        ├── conftest.py                   # app factory with fakes
        ├── fakes/
        │   ├── fake_llm.py               # scripted, routing, recording, rejecting
        │   ├── fake_embedder.py           # deterministic bag-of-words
        │   └── scripts/                   # per-scenario scripted turns
        ├── contract/test_openapi_conformance.py
        ├── unit/                          # cost, coverage, areas, safety, redaction, retry
        └── integration/                   # triage flow, rejections, multimodal, trace, ui
```

**Structure Decision**: The application lives in `starter-kit/app/` because `docker-compose.yml`
and the supplied data live in `starter-kit/`, and the starter kit's README directs work there. One
image serves both processes — the `api` service runs `claim_triage.main:app` on 8000 and the `ui`
service runs `claim_triage.ui.app:app` on 3000 — which keeps a single dependency set, a single
build, and a UI that can call the API over the Compose network without CORS. A separate frontend
project was rejected: the UI is one page with one form, and a second toolchain would cost more than
it returns at this scope.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| An undeclared `503` response on `POST /api/v1/claims/triage` and `GET /api/v1/health` | The contract declares only 200/400/422 for triage, and the health 200 schema pins `status` to the single value `healthy`. FR-035 still requires an explicit failure when model access dies or the archive is unreachable, and the readiness signal must be able to say "not ready". A 503 carrying `{error, message}` is the honest answer, and OpenAPI treats undeclared statuses as additive rather than contradictory | Returning `400` would claim the adjuster's submission was invalid when it was not, and would be counted by the evaluator as a rejected case. Returning `422` would claim a safety failure that did not happen. Returning `200` with placeholder values is exactly what FR-035 forbids. Adding `status: "unhealthy"` to the 200 health body would break the declared enum, which Principle I does not permit |
| Test dependencies installed in the production image | `make test` must be one command that runs the project's own suite in the same environment the service runs in, with no second build target to keep in sync | A multi-stage image with a separate `test` target doubles the build matrix and lets the test environment drift from production. A host-side virtualenv reintroduces "works on my machine". The cost is a slightly larger image in a pilot that ships no image anywhere |
