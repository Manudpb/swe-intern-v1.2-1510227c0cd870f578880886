---

description: "Task list for Home-Damage Claim Triage Service"
---

# Tasks: Home-Damage Claim Triage Service

**Input**: Design documents from `/specs/001-claim-triage-service/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: Included. The spec requires every acceptance scenario to be automatically verifiable, and
constitution Principle VI mandates a free, injected, failure-covering suite. Test tasks are therefore
first-class, not optional.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US8)
- Include exact file paths in descriptions

**Amendment note (2026-10-14)**: the `/speckit-analyze` remediation added three tasks. Existing ids
are **frozen** and the new tasks carry letter suffixes — `T026a`, `T085a`, `T104a` — so that every
reference made before the amendment still resolves. Total: 115 tasks.

## Path Conventions

`app/` below means `software-engineering-take-home/starter-kit/app/`. Paths outside it are written
from the repository root. The API package is `app/src/claim_triage/`, tests are `app/tests/`.

**Never touch**: `starter-kit/api-contract/openapi.yaml` (read-only authority, Principle I) and
`starter-kit/data/ground-truth/` (never mounted, never read at runtime, Principle V).

## Layering note (read before starting)

Later stories **deepen** earlier ones; they never replace a stub with a real thing. US1 builds the
pipeline with the simplest correct version of each part — the real cost tool (pure arithmetic),
retrieval through the injected port, and the deterministic safety rule pass. US3 then adds startup
ingestion, the health signal and relevance guarantees; US4 adds the area-collapse rules, coverage and
error keys; US5 adds the trace endpoint and the full structural invariants; US6 adds the LLM reviewer
and the rewrite/sanitize/422 ladder. Nothing built in US1 is thrown away.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton, image, Compose wiring, and a free `make test`

- [X] T001 Create the package and test tree under `app/` per plan.md: `app/src/claim_triage/{api,agents,agents/prompts,llm,tools,rag,evidence,domain,trace,store,ui,ui/templates,ui/static}/` and `app/tests/{fakes,fakes/scripts,contract,unit,integration}/`, each Python directory with an `__init__.py`
- [X] T002 [P] Pin runtime dependencies in `app/requirements.txt`: `fastapi`, `uvicorn[standard]`, `anthropic`, `qdrant-client`, `fastembed`, `pypdf`, `Pillow`, `pydantic`, `pydantic-settings`, `jinja2`, `httpx`, `python-multipart` — every entry with an exact `==` version
- [X] T003 [P] Pin test dependencies in `app/requirements-dev.txt`: `pytest`, `pytest-asyncio`, `jsonschema`, `referencing`, `PyYAML`, `beautifulsoup4` — exact versions
- [X] T004 [P] Configure pytest in `app/pyproject.toml`: `testpaths = ["tests"]`, `pythonpath = ["src"]`, `asyncio_mode = "auto"`, markers `unit`, `integration`, `contract`, and `-q` default output
- [X] T005 Write `app/Dockerfile` on `python:3.12-slim`: install both requirements files, copy `src/` and `tests/`, then bake the embedding model with a build step that instantiates `fastembed.TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir="/opt/fastembed")` so no download happens at container start (research D7), set `ENV FASTEMBED_CACHE_DIR=/opt/fastembed`, default command `uvicorn claim_triage.main:app --host 0.0.0.0 --port 8000`
- [X] T006 [P] Add `.dockerignore` in `app/` excluding `__pycache__/`, `.pytest_cache/`, `*.pyc`, `.venv/`
- [X] T007 Add `api` and `ui` services to `software-engineering-take-home/starter-kit/docker-compose.yml`: both `build: ./app`; `api` on `8000:8000` with `QDRANT_URL=http://qdrant:6333`, `depends_on: qdrant`, and read-only mounts of **only** `./data/knowledge-base:/app/data/knowledge-base:ro`, `./tools:/app/tools:ro` and `./api-contract:/app/api-contract:ro`. Declare the credential file as optional so the suite runs without it (finding C2):

  ```yaml
      env_file:
        - path: .env
          required: false
  ```

  The `api-contract` mount is what makes `openapi.yaml` reachable from inside the image, where the tests run (finding C1); it is read-only, so Principle I still holds. `ui` on `3000:3000` with command `uvicorn claim_triage.ui.app:app --host 0.0.0.0 --port 3000`, `API_BASE_URL=http://api:8000`, `depends_on: api`. **Do not mount `./data` wholesale — it contains `ground-truth/` (Principle V)**
- [X] T008 Replace the failing `test` target in `software-engineering-take-home/starter-kit/Makefile` with `docker compose run --rm --no-deps -e APP_ENV=test api python -m pytest -q`; `--no-deps` is required so the suite passes with Qdrant down. Leave `grade`, `grade-smoke` and `check-access` untouched

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The injection seams, the contract mirrors, and the test doubles that every story needs

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T009 Implement `Settings` in `app/src/claim_triage/settings.py` with `pydantic-settings`: `portkey_api_key` (secret), `portkey_base_url`, `claude_model_route`, `qdrant_url`, `knowledge_base_dir`, `tools_dir`, `openapi_path` (default `/app/api-contract/openapi.yaml`, finding C1), `max_tool_rounds=6`, `llm_timeout_s=60`, `request_budget_s=110`, `max_image_bytes=10_485_760`, `pdf_text_limit=8000`. Expose `gateway_root` (base URL with a trailing `/v1` stripped) and `model_id`/`provider_route` from splitting `claude_model_route` on the first `/` (research D1). `__repr__` and `__str__` MUST redact the key
- [X] T010 [P] Add a logging filter in `app/src/claim_triage/settings.py` that replaces any occurrence of the credential value with `***` in every log record message and args, and install it on the root logger in `create_app` (FR-036)
- [X] T011 [P] Define the LLM port in `app/src/claim_triage/llm/ports.py`: `LLMClient` Protocol with `create_message(*, system: str, messages: list[dict], tools: list[dict], max_tokens: int, temperature: float) -> LLMResponse`, plus a vendor-neutral `LLMResponse` exposing `stop_reason`, `text_blocks: list[str]` and `tool_calls: list[ToolCall(id, name, input)]`, and an `LLMUnavailable` exception
- [X] T012 Define `Deps` in `app/src/claim_triage/deps.py` as a frozen dataclass with fields `llm`, `embedder`, `vectors`, `cost_table`, `coverage_table`, `reports`, `clock`, `new_id`, `settings`, and Protocols for `Embedder` (`embed(texts) -> list[list[float]]`, `dimension: int`), `VectorStore` (`ensure_collection`, `upsert`, `search`, `count`), `ReportStore`, `Clock`, `IdFactory` per contracts/internal-ports.md
- [X] T013 Mirror the contract in `app/src/claim_triage/api/schemas.py` as pydantic models: `IntakeValidation` with `is_valid_image: bool | None` (`null` **only** for text-only input), `TriageAssessment`, `CostRange` (`currency` default `"USD"`), `SimilarClaimRef` (`similarity_score` with `ge=0, le=1`), `SafetyChecks`, `TriageResponse` (required `claim_id`, `intake_validation`, `triage_assessment`, `safety_checks`), `AgentTrace`, `TraceStep`, `ValidationError`, `SafetyError`. Enums exactly: `DamageType` = `water_damage|fire_damage|storm_damage|break_in|vandalism|other`; `Severity` = `minor|moderate|severe|catastrophic`; `Urgency` = `low|medium|high|critical`; `PolicyType` = `basic_homeowner|standard_homeowner|premium_homeowner|renters|landlord`
- [X] T014 [P] Implement error responses in `app/src/claim_triage/api/errors.py`: 400 `{error, intake_validation, message}` with non-empty prose `message`, 404 `{error, message}`, 422 `{error, safety_checks, message}`, and 503 `{error: "upstream_unavailable", message}` used **only** for upstream/readiness failure, never for client-caused failure (contracts/http-api.md)
- [X] T015 Implement `create_app(deps: Deps) -> FastAPI` and `build_deps(settings) -> Deps` in `app/src/claim_triage/main.py`; `build_deps` is the only place that constructs real clients, and no request handler may construct a provider (Principle VI)
- [X] T016 [P] Implement `GET /api/v1/health` in `app/src/claim_triage/api/routes_health.py` returning 200 `{status: "healthy", services: {vector_db, llm}}` only when ready, else 503 `{status: "unhealthy", services: {...}}`; `vector_db` is `connected` only when the collection exists with at least 80% of the knowledge-base record count, `llm` is `configured` when the credential and route are present (research D7, D8)
- [X] T017 [P] Implement the trace recorder in `app/src/claim_triage/trace/recorder.py`: `reason(content)`, `act(tool_name, tool_input)`, `observe(tool_output, content)`, emitting `step_number` starting at 1 incrementing by exactly 1, `type` in `reason|act|observe`, non-empty `content` capped at 240 characters for `reason` steps, `timestamp` as RFC 3339 from `deps.clock`, `tool_name`/`tool_input` on `act` steps only, `tool_output` on `observe` steps only, and `total_duration_ms` as an int
- [X] T018 [P] Implement the bounded report store in `app/src/claim_triage/store/reports.py`: LRU of 500 entries holding report and trace by `claim_id`, with a trace published only once its run completes so an in-progress id reads as absent
- [X] T019 [P] Implement `app/src/claim_triage/tools/registry.py` mapping tool name to `{input_schema, handler}` with a duplicate-name guard, and a `to_anthropic_tools()` serializer
- [X] T020 [P] Implement the cost table loader in `app/src/claim_triage/tools/estimate_repair_cost.py`: load `tools/cost-estimator.json` once at startup, immutable, keyed `cost_matrix[damage_type][severity] -> {min_per_area, max_per_area}`
- [X] T021 [P] Implement the coverage table loader in `app/src/claim_triage/tools/check_coverage.py`: load `tools/coverage-table.json` once at startup, immutable, keyed `policies[policy_type] -> {covered_categories, deductible, max_payout, notes}`
- [X] T022 [P] Implement `FastEmbedEmbedder` in `app/src/claim_triage/rag/embedder_fastembed.py` wrapping `BAAI/bge-small-en-v1.5` with an explicit `cache_dir` from settings, `dimension == 384`
- [X] T023 [P] Implement `QdrantStore` in `app/src/claim_triage/rag/store_qdrant.py` against the `VectorStore` port, constructed from either a server URL or `QdrantClient(":memory:")`, collection `historical_claims`, cosine distance, 384 dims, with `count()` for the health signal
- [X] T024 Implement `AnthropicPortkeyClient` in `app/src/claim_triage/llm/anthropic_portkey.py`: `anthropic.Anthropic(base_url=settings.gateway_root, api_key=key, default_headers={"x-portkey-api-key": key, "x-portkey-provider": settings.provider_route})`, calling with `model=settings.model_id` (unprefixed), explicit `max_tokens`, `timeout=llm_timeout_s`; retry **at most once** on 502/503/529 and timeouts and **never** on 429/401/403, raising `LLMUnavailable` otherwise (research D1, D8)
- [X] T025 Build the test app factory in `app/tests/conftest.py`: fixtures for a fixed clock, a counter `new_id` (`claim-0001`, …), the real cost and coverage tables, the real 30-record knowledge base, `QdrantClient(":memory:")`, and an `app_client` fixture calling `create_app(Deps(...))` with fakes and a dummy non-real credential
- [X] T026 Implement `FakeLLM` in `app/tests/fakes/fake_llm.py`: routes by the `intake`/`triage`/`safety` marker in the system prompt, pops the next scripted turn per route, records full request kwargs in `.calls`, and raises `FakeLLMContractError` on all eight rejection rules in contracts/internal-ports.md — missing/non-positive `max_tokens`; `model` containing `@` or `/`; a `tool_result` whose `tool_use_id` matches no prior `tool_use`; an assistant turn ending in `tool_use` with no following `tool_result`; empty `content` list, empty text block or unknown `role`; image `media_type` outside `image/jpeg|png|gif|webp` or raw bytes instead of base64; duplicate tool names or a non-object `input_schema`; and an exhausted script for the route
- [X] T026a Author the scripted turn fixtures in `app/tests/fakes/scripts/`, plus a `build_script(**overrides)` helper in `app/tests/fakes/__init__.py` that assembles a per-route turn list and **appends a clean safety verdict by default** unless a test overrides it (finding G2). Ship one script per scenario: clean triage, each of the four rejection categories, text-only, PDF-widened scope, and each safety path (clean / rewrite-succeeds / rewrite-fails / unsanitizable). Every integration test builds its script from this helper rather than hand-rolling turns, so a new mandatory model call is added in one place
- [X] T027 [P] Implement `FakeEmbedder` in `app/tests/fakes/fake_embedder.py`: tokens hashed into 384 signed buckets and L2-normalized, deterministic across runs with an explicit seed and no reliance on `hash()`, so cosine similarity tracks term overlap
- [X] T028 Implement the conformance helper `assert_conforms(path_template, method, status, body)` in `app/tests/contract/conformance.py`: load the contract from `settings.openapi_path` (the read-only `/app/api-contract/openapi.yaml` mount, **not** a host-relative path — finding C1) with PyYAML once, resolve `#/components/schemas` through a `referencing` registry, validate with the Draft 2020-12 validator and a format checker enabled for `date-time`; fail with an explicit "contract not mounted" message if the path is absent, so a missing mount can never be mistaken for a passing suite (research D12)
- [X] T029 [P] Write `app/tests/unit/test_fake_llm_contract.py` asserting each of the eight `FakeLLM` rejection rules raises, so the suite's own safety net is itself verified
- [X] T030 [P] Write `app/tests/unit/test_settings_redaction.py` asserting the credential never appears in `repr(settings)`, `str(settings)`, or a log record passed through the scrubbing filter (FR-036)

**Checkpoint**: Injection seams, contract mirrors and test doubles exist. Story work can begin.

---

## Phase 3: User Story 1 - Triage a submission into a decision-ready report (Priority: P1) 🎯 MVP

**Goal**: A photo plus a description returns a complete, contract-shaped report retrievable by id.

**Independent Test**: Submit a damage photo plus a description against scripted FakeLLM turns and
assert every required field carries a value from the permitted set; fetch by id and assert it is
unchanged; unknown id → 404; LLM raising → 503.

### Tests for User Story 1

- [X] T031 [P] [US1] Write `app/tests/integration/test_triage_flow.py` asserting a scripted submission returns 200 with all four `TriageResponse` keys, `assert_conforms` passes, `damage_type` is `water_damage`, `min <= max`, currency `USD`, and a non-empty `recommendation` (US1 scenarios 1)
- [X] T032 [P] [US1] Extend `app/tests/integration/test_triage_flow.py` with retrieval-by-id returning byte-identical content (US1 scenario 2) and an unissued id returning 404 with `assert_conforms` on the 404 body (US1 scenario 3)
- [X] T033 [P] [US1] Write `app/tests/integration/test_triage_failures.py` asserting a request with neither image nor non-blank description is refused with no report produced (US1 scenario 4), and an `LLMClient` raising `LLMUnavailable` yields 503 with no guessed field values (US1 scenario 5, FR-035)
- [X] T034 [P] [US1] Write `app/tests/unit/test_report_invariants.py` asserting invariant I3 directly: given a recorded trace, `report.damage_type/severity/affected_areas` equal the last successful `estimate_repair_cost` **arguments** including list order, and `report.estimated_repair_cost.min/max` equal that call's **output**; with no successful cost call the assembler raises rather than returning a model-authored number

### Implementation for User Story 1

- [X] T035 [P] [US1] Implement image handling in `app/src/claim_triage/evidence/images.py`: accept `image/jpeg` and `image/png`, reject above `max_image_bytes` (10 MB) per image, downscale to ≤ 1024 px on the long edge, re-encode JPEG q80, return base64 plus media type. **No cap on the number of images** — `openapi.yaml` places no upper bound on `images` and no requirement authorizes refusing a submission for view count, so the per-image size limit is the only bound (finding U2)
- [X] T036 [P] [US1] Implement `normalize_areas(raw) -> list[str]` in `app/src/claim_triage/domain/areas.py` with the five ordered steps from data-model.md: lowercase/trim/collapse spaces and hyphens to `_`; synonym map; drop component suffixes when the parent room is present; drop generic umbrellas (`interior`, `exterior`, `house`, `property`, `whole_house`) when any specific area survives, keeping exactly one if nothing else does; de-duplicate preserving first-seen order
- [X] T037 [US1] Implement the `estimate_repair_cost` handler in `app/src/claim_triage/tools/estimate_repair_cost.py` returning `{min, max, currency: "USD", areas_counted}` where `n = max(1, |{a.strip().lower() for a in affected_areas}|)`, `min = min_per_area × n`, `max = max_per_area × n`; unknown `damage_type`/`severity` returns `{"error": "unknown_cost_key"}` with no fallback figure
- [X] T038 [US1] Implement the `search_past_claims` handler in `app/src/claim_triage/tools/search_past_claims.py` returning `{"claims": [{claim_id, similarity_score, damage_type, severity, affected_areas, resolution_summary}]}` ordered by descending score, `top_k` 1–10 default 5, every `claim_id` from the corpus, scores in `[0, 1]`, and `{"error": "retrieval_unavailable"}` when the store is unreachable
- [X] T039 [US1] Implement the `submit_triage` terminal tool in `app/src/claim_triage/tools/submit_triage.py` whose input schema is the report schema **without any cost field**, returning `{"accepted": true}`, and rejecting invocation before any successful `estimate_repair_cost` with a tool error telling the model to price the damage first (contracts/agent-tools.md)
- [X] T040 [US1] Implement the ReAct loop in `app/src/claim_triage/agents/triage.py`: native tool calling over the registry, maximum 6 tool rounds, recording `reason` from the model's purpose sentence (synthesized from tool name and arguments when the turn carries no text, capped at 240 chars), `act` on each tool call and `observe` on each real return; identical repeated tool calls are answered from the recorded observation without re-running the tool; reaching the cap without `submit_triage` raises for a 503 (research D3, D4)
- [X] T041 [P] [US1] Write the triage system prompt in `app/src/claim_triage/agents/prompts/triage.md` carrying the `triage` route marker, requiring one short action-purpose sentence before each tool call, forbidding deliberation in that sentence, and forbidding any self-authored cost figure
- [X] T042 [US1] Implement report assembly in `app/src/claim_triage/domain/report.py` enforcing invariants I3 and I4: copy scope from the last successful cost call's arguments verbatim and in order, copy `min`/`max` from its output, intersect cited `claim_id`s with ids returned by successful `search_past_claims` observations dropping any others, and log a drift warning when `submit_triage` disagreed with the cost call
- [X] T043 [US1] Implement the deterministic safety rule pass in `app/src/claim_triage/agents/safety.py`: patterns for the five limits over `damage_description` and `recommendation`, each hit recording the limit **and the character span**; this is one of the two detectors US6 later composes (research D9)
- [X] T044 [US1] Implement `POST /api/v1/claims/triage` and `GET /api/v1/claims/{claim_id}` in `app/src/claim_triage/api/routes_claims.py`: accept multipart `image` plus repeated `images`, `description`, `document`, `policy_type` defaulting to `standard_homeowner`; require at least one image or a non-blank description; run the pipeline under the 110 s request budget; store report and trace; return 200, or 404 for an unknown id. The pipeline runs the T043 rule scan over `damage_description` and `recommendation` and populates `safety_checks` in `TriageResponse` from its verdict. In US1 a failing verdict returns 422 without remediation. US6 (T086) replaces this single scan with the full sequence: rule scan AND Claude review, then one rewrite, then sanitize, then 422
- [X] T045 [US1] Derive `urgency` in `app/src/claim_triage/domain/report.py` from severity, damage type and ongoing-risk cues in the evidence, as a documented judgement field with no lookup table (spec assumption)

**Checkpoint**: A real triage runs end to end and is retrievable. This is the MVP.

---

## Phase 4: User Story 2 - Reject unsuitable submissions with a clear reason (Priority: P1)

**Goal**: Unsuitable submissions are refused with the failing check named and a reason an adjuster
can act on, before any tool runs.

**Independent Test**: Submit each of the four unsuitable categories and assert 400 with the offending
flag false, a non-empty prose `message`, and no `triage_assessment`; submit a valid case and assert
no rejection.

### Tests for User Story 2

- [X] T046 [P] [US2] Write `app/tests/integration/test_intake_rejection.py` parametrized over the four categories asserting 400, `assert_conforms` against `ValidationError`, the decisive flag false (`is_property_damage` for a non-damage photo, `is_valid_image` for a blurry image, `no_pii_detected` for a payment card, `no_offensive_content` for abusive text), a non-empty `message`, and **no** `triage_assessment` key (US2 scenarios 1–5)
- [X] T047 [P] [US2] Extend `app/tests/integration/test_intake_rejection.py` asserting a rejected submission produced no trace claiming tool activity, and that the FakeLLM recorded **exactly one** call — proving rejection happens before the loop (US5 scenario 7)
- [X] T048 [P] [US2] Write `app/tests/integration/test_intake_text_only.py` asserting a valid text-only description is **not** rejected, `is_valid_image` is `null`, the other three flags are evaluated, and triage proceeds (US2 scenario 6, FR-006)
- [X] T049 [P] [US2] Extend `app/tests/integration/test_triage_flow.py` asserting a valid photo plus description passes all four intake checks with no rejection (US2 scenario 7)

### Implementation for User Story 2

- [X] T050 [P] [US2] Write the intake system prompt in `app/src/claim_triage/agents/prompts/intake.md` carrying the `intake` route marker and stating the hard rules: a payment card including a synthetic test card sets `no_pii_detected` false; an image too blurry or a screenshot of text sets `is_valid_image` false; a photo with no property or structural damage sets `is_property_damage` false
- [X] T051 [US2] Implement `intakeValidator` in `app/src/claim_triage/agents/intake.py`: one LLM call with images attached returning the four booleans through a forced tool call; for a submission with no image set `is_valid_image = None` and judge the other three from the text; return a structured verdict plus a prose reason naming what failed (FR-004–FR-007)
- [X] T052 [US2] Wire intake into `app/src/claim_triage/api/routes_claims.py` ahead of the loop: any false flag short-circuits to 400 with the verdict and the prose message and no tool ever runs (invariant I1)

**Checkpoint**: US1 and US2 both work independently. Rejection costs exactly one model call.

---

## Phase 5: User Story 3 - Ground the report in similar past claims (Priority: P2)

**Goal**: Reports cite real historical claims, ranked by semantic similarity, with the archive
populated at startup and reported in health.

**Independent Test**: With the real 30-record corpus in an in-memory store, a burst-pipe query ranks
a water-damage claim first, all ids are real, scores are ordered and in `[0, 1]`, and an unavailable
store fabricates nothing.

### Tests for User Story 3

- [X] T053 [P] [US3] Write `app/tests/integration/test_retrieval.py` asserting a search for "burst pipe flooded kitchen floor" returns a water-damage claim first with scores in descending order and every `claim_id` present in the real corpus (US3 scenarios 2–3)
- [X] T054 [P] [US3] Extend `app/tests/integration/test_retrieval.py` asserting an unlike-anything query yields an empty list or only low-scoring entries and never an id absent from the corpus (US3 scenario 4), and that an unreachable store yields either a not-ready health signal or an empty precedent list (US3 scenario 5)
- [X] T055 [P] [US3] Write `app/tests/unit/test_ingest.py` asserting ingestion is idempotent — a second run over a populated collection re-embeds nothing and the point count stays at 30 — and that point ids are deterministic from `claim_id`
- [X] T056 [P] [US3] Write `app/tests/integration/test_health.py` asserting 200 `healthy` with `vector_db: connected` when the collection holds the corpus, and 503 `unhealthy` with `vector_db: disconnected` when it is empty, with `assert_conforms` on the 200 body (US3 scenario 1)
- [X] T057 [P] [US3] Write `app/tests/integration/test_no_ground_truth_at_runtime.py` asserting the running app reads no path containing `ground-truth` (patch `open`/`Path.open` and assert no such path is touched during a triage) and that renaming the submitted image filename does not change the report. The compose-mount grep moves to T112, because the compose file is not inside the image where these tests run (findings I1, C1) (US3 scenario 6, FR-021, Principle V)

### Implementation for User Story 3

- [X] T058 [US3] Implement corpus loading and embedding text assembly in `app/src/claim_triage/rag/ingest.py`: embedded text is `description` + `adjuster_notes` + `damage_type` + `severity` + `affected_areas` joined, while `repair_cost_actual`, `resolution` and `fraud_indicators` go to the payload only so they cannot distort similarity (research D7)
- [X] T059 [US3] Make ingestion idempotent in `app/src/claim_triage/rag/ingest.py`: deterministic point ids derived from `claim_id`, upsert, and skip re-embedding when the collection already holds the expected count
- [X] T060 [US3] Run ingestion at API startup in `app/src/claim_triage/main.py` with retry against a not-yet-ready Qdrant, logging progress without ever logging the credential
- [X] T061 [US3] Implement `resolution_summary` derivation in `app/src/claim_triage/tools/search_past_claims.py` from the record's `resolution` and outcome fields, never invented text (data-model.md SimilarClaimRef)

**Checkpoint**: Precedent is real, ranked, and visible in health.

---

## Phase 6: User Story 4 - Anchor money and coverage to the company tables (Priority: P2)

**Goal**: Every dollar figure is table arithmetic; coverage comes from the table; a contractor quote
never moves the number.

**Independent Test**: For a fixed damage type, severity and area count the report's range equals the
table computation exactly; a conflicting quote PDF does not move it; `["kitchen","kitchen floor",
"interior"]` counts as one area.

### Tests for User Story 4

- [X] T062 [P] [US4] Write `app/tests/unit/test_cost.py` asserting `water_damage`/`moderate` with two distinct areas yields exactly `min 4000` / `max 16000`, an empty area list uses multiplier 1 rather than 0 (US4 scenario 2, FR-016), and an unknown key returns `{"error": "unknown_cost_key"}` rather than a figure
- [X] T063 [P] [US4] Write `app/tests/unit/test_areas.py` asserting `["kitchen", "kitchen floor", "interior"]` → `["kitchen"]`, `["kitchen", "Dining Room"]` → `["kitchen", "dining_room"]`, generic-only input keeps exactly one area, and first-seen order is preserved. This is the rule-level test of `normalize_areas`; T089 tests the same rule through the multi-photo entry point, so a change here must update both (finding D1) (US4 scenario 4, FR-012)
- [X] T064 [P] [US4] Write `app/tests/unit/test_coverage.py` asserting `basic_homeowner` + `water_damage` returns `covered: false` with that policy's deductible 2500 and max payout 100000 from the table, and an unlisted policy or category returns `{"error": "unknown_coverage_key"}` rather than a guessed deductible (US4 scenarios 5–6, FR-017)
- [X] T065 [P] [US4] Write `app/tests/integration/test_quote_does_not_move_cost.py` asserting a submission whose PDF quotes a figure outside the table range still reports the table figure, with the quote at most mentioned in the narrative (US4 scenario 3, FR-015)
- [X] T066 [P] [US4] Extend `app/tests/unit/test_coverage.py` asserting a submission stating no policy type consults coverage with `standard_homeowner` and the trace records that policy type (US4 scenario 7, FR-003)

### Implementation for User Story 4

- [X] T067 [US4] Implement the `check_coverage` handler in `app/src/claim_triage/tools/check_coverage.py` returning `{covered, deductible, max_payout, notes}` from the table, with `{"error": "unknown_coverage_key"}` for an unlisted policy or category
- [X] T068 [US4] Ensure `normalize_areas` runs **before** the cost call in `app/src/claim_triage/agents/triage.py`, so the tool's distinct count and the published checker's `max(1, len(set(...)))` agree (research D5)
- [X] T069 [US4] Constrain the recommendation in `app/src/claim_triage/domain/report.py` so coverage shapes its wording without contradicting the table answer and without stating a promise or a denial — coverage is not a report field (spec assumption)

**Checkpoint**: Money and coverage are table-derived and unmovable by the model or a quote.

---

## Phase 7: User Story 5 - Inspect how a report was produced (Priority: P2)

**Goal**: Every report has a retrievable, well-formed trace whose observations agree with the report
and expose no private reasoning.

**Independent Test**: Produce a report, fetch its trace, assert step numbering, act/observe pairing,
≥2 of each kind, a consecutive reason→act→observe triple, cost agreement, and no credential anywhere.

### Tests for User Story 5

- [X] T070 [P] [US5] Write `app/tests/integration/test_trace.py` asserting the trace returns with the matching `claim_id`, ordered steps and an int `total_duration_ms`, with `assert_conforms` against `AgentTrace` including the `date-time` format on every timestamp (US5 scenario 1)
- [X] T071 [P] [US5] Extend `app/tests/integration/test_trace.py` asserting step numbers increase by exactly 1 with no gaps, each `type` is one of the three kinds, every `act` is immediately followed by the `observe` for that action, and no `act` is unobserved or `observe` orphaned (US5 scenario 2, invariant I7)
- [X] T072 [P] [US5] Extend `app/tests/integration/test_trace.py` asserting at least two distinct tools appear, each `act` carries a non-empty `tool_input` dict, each `observe` carries a non-empty `tool_output` dict or array holding the real returned value, and at least two steps of each kind plus one consecutive `reason → act → observe` triple exist (US5 scenario 3, invariants I8–I9)
- [X] T073 [P] [US5] Extend `app/tests/integration/test_trace.py` asserting the cost observation matches the report's cost range (US5 scenario 4) and that an id with no run returns 404 (US5 scenario 6)
- [X] T074 [P] [US5] Write `app/tests/integration/test_trace_privacy.py` asserting no step content exceeds 240 characters for `reason` steps, no step contains deliberation markers, and the credential appears in no step, no report and no captured log record (US5 scenarios 5 and 8, FR-025, FR-036, invariant I10)

### Implementation for User Story 5

- [X] T075 [US5] Implement `GET /api/v1/agent/trace/{claim_id}` in `app/src/claim_triage/api/routes_trace.py` returning `{claim_id, steps, total_duration_ms}`, and 404 for an unknown id or a run still in progress
- [X] T076 [US5] Enforce the structural invariants in `app/src/claim_triage/trace/recorder.py` at publish time: pairing, numbering and the presence of at least one successful `search_past_claims` and one successful `estimate_repair_cost` observation, raising rather than publishing a malformed trace (invariants I7–I9)
- [X] T077 [US5] Record tool errors as real observations in `app/src/claim_triage/agents/triage.py` — an `{"error": ...}` return is observed and the model may adapt without aborting the loop (contracts/agent-tools.md)

**Checkpoint**: A reviewer can audit any report against its trace.

---

## Phase 8: User Story 6 - Keep report language within professional limits (Priority: P2)

**Goal**: Two independent detectors gate every report's text, escalating rewrite → sanitize → refuse.

**Independent Test**: Feed handcrafted text violating each limit and assert detection and correction;
feed compliant text and assert it passes untouched; assert the unsanitizable case returns 422.

### Tests for User Story 6

- [X] T078 [P] [US6] Write `app/tests/unit/test_safety_rules.py` with one fixture per limit asserting the deterministic pass detects it and records the offending span: "this damage is fully covered and will be paid" (coverage promise), "the claimant should expect a settlement of $12,000" (settlement amount, while a table cost range stays permitted), "the neighbour is liable for this damage" (legal advice and liability), "we are devastated by this tragic loss" (emotional language) (US6 scenarios 1–4)
- [X] T079 [P] [US6] Write `app/tests/unit/test_safety_composition.py` asserting a flag is true only when **both** detectors agree, that a paraphrased promise missed by the rules but caught by the reviewer still fails, and that a rule hit the reviewer passes still fails (research D9)
- [X] T080 [P] [US6] Write `app/tests/integration/test_safety_ladder.py` asserting the rewrite path delivers 200 with the violating sentence gone and all five flags true (US6 scenario 5), the sanitize path delivers 200 after dropping the named sentence, and the unsanitizable path returns 422 with `assert_conforms` against `SafetyError` and the failing flags named (US6 scenario 6)
- [X] T081 [P] [US6] Extend `app/tests/integration/test_safety_ladder.py` asserting clean text is returned unmodified with all five flags true (US6 scenario 7), and asserting at most three safety-route LLM calls occur on the worst path — review, rewrite, re-review (invariant I12)

### Implementation for User Story 6

- [X] T082 [P] [US6] Write the safety prompts in `app/src/claim_triage/agents/prompts/safety_review.md` and `safety_rewrite.md`, both carrying the `safety` route marker; the review prompt requires each violation's offending sentence copied **verbatim**, the rewrite prompt names the broken limits and quotes the offending sentences and requires factual content preserved
- [X] T083 [US6] Implement the low-effort LLM reviewer in `app/src/claim_triage/agents/safety.py` calling the `report_safety_verdict` forced tool with thinking disabled, `temperature = 0`, `max_tokens = 300`, text only — no images, no retrieval context (research D9, contracts/agent-tools.md)
- [X] T084 [US6] Implement verdict composition in `app/src/claim_triage/agents/safety.py`: each flag is the conjunction of both detectors, a disagreement resolves against the report, and a reviewer-quoted sentence that cannot be located in the source is a non-finding logged as reviewer drift
- [X] T085 [US6] Implement the ladder in `app/src/claim_triage/agents/safety.py`: one rewrite via `submit_rewritten_text` naming the broken rules, re-run both detectors, then sanitize by dropping the named sentences and re-run the deterministic pass with a span-removal assertion, then 422 if a span cannot be removed without emptying a required field or the pass still fails. No stage repeats (FR-028, FR-029, invariant I12)
- [X] T085a [US6] Update every existing integration script to carry the turns the composed gate now requires (finding G1): with `build_script` from T026a the default clean safety verdict already covers the happy paths, so audit each script in `app/tests/integration/` and add the explicit turns for the rewrite path (three safety-route turns: review, rewrite, re-review). Rejection scripts need **no** safety turn, because intake short-circuits before a report exists. Run the full suite and confirm no test fails with `FakeLLMContractError: script exhausted`
- [X] T086 [US6] Wire the composed gate into `app/src/claim_triage/api/routes_claims.py`, **replacing** the single rule scan that T044 installed in US1: rule scan **and** Claude review, then one rewrite, then sanitize, then 422. A delivered report always records all five limits true, and 422 is returned otherwise (FR-030, invariant I5)

**Checkpoint**: No report reaches an adjuster without passing two independent judgements.

---

## Phase 9: User Story 7 - Evidence beyond a single photo (Priority: P3)

**Goal**: All four input combinations work, PDF findings refine scope, and repeated views do not
multiply areas.

**Independent Test**: Submit each combination and assert a complete report; submit three views of one
room and assert the area count does not triple.

### Tests for User Story 7

- [X] T087 [P] [US7] Write `app/tests/integration/test_multimodal.py` asserting image-only returns a complete report (US7 scenario 1), and text-only returns a complete report with `is_valid_image` null whose `damage_description` ends with the exact limited-confidence sentence defined in T094 (finding A1) (US7 scenario 2)
- [X] T088 [P] [US7] Extend `app/tests/integration/test_multimodal.py` asserting image + text + PDF returns a complete report whose narrative reflects at least one PDF finding (US7 scenario 3), and that the inspection PDF widens scope to include `dining_room` yielding cost `min 4000` / `max 16000` (US7 scenario 5)
- [X] T089 [P] [US7] Extend `app/tests/integration/test_multimodal.py` asserting three views of one damaged kitchen describe one incident with the area count reflecting distinct rooms, not photo count — the end-to-end counterpart of T063's rule-level test (finding D1) (US7 scenario 4, FR-012)
- [X] T090 [P] [US7] Write `app/tests/integration/test_evidence_conflicts.py` asserting a PDF contradicting the photo on severity produces a narrative that states the conflict rather than silently resolving it (US7 scenario 6), and that an unreadable PDF is either noted in the report or rejected with that reason, never failing silently (US7 scenario 7)

### Implementation for User Story 7

- [X] T091 [P] [US7] Implement PDF extraction in `app/src/claim_triage/evidence/pdf.py` with pypdf, truncating to the 8 000-character limit, returning a structured result that distinguishes "no text found" and "unreadable" from success
- [X] T092 [US7] Merge `image` and repeated `images` into one view list in `app/src/claim_triage/api/routes_claims.py`, treating all views as one incident and never as separate claims (spec assumption)
- [X] T093 [US7] Pass PDF text into the opening triage message in `app/src/claim_triage/agents/triage.py` as same-incident evidence that may widen or narrow scope but never displaces the table cost figure, and require unresolved conflicts to be stated in the narrative (FR-015, US7 scenario 6)
- [X] T094 [US7] Add the limited-confidence note for text-only submissions in `app/src/claim_triage/domain/report.py`: append the exact sentence `"No photographic evidence was provided; this assessment is based on the written description alone and carries lower confidence."` to `damage_description`, appended by the assembler rather than requested from the model so the assertion is exact (finding A1, FR-006, US7 scenario 2)

**Checkpoint**: Real-world submission shapes all produce usable reports.

---

## Phase 10: User Story 8 - Use the service from a web page (Priority: P3)

**Goal**: An adjuster submits and reads a report plus its trace in a browser on port 3000.

**Independent Test**: Load the page and assert the four controls and the submit action exist; submit
a fixture and assert the report fields and trace steps both render.

### Tests for User Story 8

- [X] T095 [P] [US8] Write `app/tests/integration/test_ui.py` asserting `GET /` returns 200 `text/html` containing a file input, a textarea, a policy-type `<select>` with five options and `standard_homeowner` preselected, and a submit button, parsed with BeautifulSoup (US8 scenario 1)
- [X] T096 [P] [US8] Extend `app/tests/integration/test_ui.py` asserting a submitted fixture renders damage type, severity, affected areas, cost range with currency, urgency, recommendation and similar past claims (US8 scenario 2), and that the trace panel region and its `/api/v1/agent/trace/` fetch path are present (US8 scenario 3)
- [X] T097 [P] [US8] Extend `app/tests/integration/test_ui.py` asserting a 400 from the API renders the stated reason and the four intake flags with the failing one marked (US8 scenario 4), a 422 renders the safety refusal, a 503 renders an explicit error banner, and submitting with neither photo nor description reports the missing input without leaving a request pending (US8 scenario 5)

### Implementation for User Story 8

- [X] T098 [US8] Implement the UI app in `app/src/claim_triage/ui/app.py`: `GET /` renders the form, `POST /submit` forwards the multipart body to `${API_BASE_URL}/api/v1/claims/triage` with httpx and renders 200/400/422/503 distinctly, `GET /api/v1/agent/trace/{claim_id}` proxies the API so the panel fetches same-origin with no CORS, and `/static/*` serves the assets (contracts/ui-contract.md)
- [X] T099 [P] [US8] Write `app/src/claim_triage/ui/templates/index.html` with the form (`images` multiple accepting `image/jpeg,image/png`, `description` textarea, `document` accepting `application/pdf`, `policy_type` select, submit button) and the labelled result and trace regions
- [X] T100 [P] [US8] Write `app/src/claim_triage/ui/static/app.css` and `app/src/claim_triage/ui/static/app.js` — one stylesheet, and a small script for the trace-panel `fetch()` and the in-flight button state; no bundler, no framework

**Checkpoint**: All eight stories are independently functional.

---

## Phase 11: Polish & Cross-Cutting Concerns

- [X] T101 [P] Write `software-engineering-take-home/starter-kit/README.md`: ASCII architecture diagram, the model choice and why (Claude via the funded Portkey gateway), the vector-DB and embedding choices, `make setup` instructions, the `CHECK_PORTKEY=0` readiness-check substitution stated honestly as not a run of the packet's own check, trade-offs, limitations and next steps
- [X] T102 [P] Write `software-engineering-take-home/AI_USAGE.md` covering tools used, what was delegated, corrections made and how the output was validated
- [X] T103 [P] Write `software-engineering-take-home/RESULTS.md` recording measurements and the three carried risks from research.md: the live request shape is unproven until the capability probe, there is no LLM re-review after sanitization, and classification accuracy is unmeasured until a paid run. Also record that SC-002–SC-005 have no free proxy — accuracy and the five rejection fixtures are verified only by paid runs (finding G4)
- [X] T104 [P] Add `app/tests/unit/test_retry_policy.py` asserting one retry on 502/503/529 and timeouts, and **no** retry on 429/401/403, with 429 surfacing as 503 carrying a pause-and-check message (research D8)
- [X] T104a [P] Add `app/tests/unit/test_request_budget.py` asserting an injected `LLMClient` that sleeps past `request_budget_s` trips the 110 s budget and yields 503 with no partial report, so SC-001's "never hanging beyond 120 s" is verified rather than assumed (finding G3, FR-035)
- [X] T105 [P] Add `app/tests/contract/test_openapi_conformance.py` sweeping every endpoint and every declared status so each of 200/400/404/422 has at least one validated body, and asserting 503 is produced only for upstream or readiness failure
- [X] T106 Run `make test` and confirm the whole suite passes with no network and no paid call; fix any code path that constructs a real client instead of using `deps`
- [ ] T107 **PAID — ask the operator first.** Run the single capability probe `make check-claude-access` from `starter-kit/` to confirm the live gateway, route and credential work (constitution Principle III)
- [X] T108 Bring the stack up with `docker compose up --build -d --wait` and confirm `make health`, the UI at `http://localhost:3000`, and `historical_claims` holding 30 points at `http://localhost:6333/collections`
- [ ] T109 **PAID — ask the operator first.** Run `make grade-smoke` (three varied positive cases) and fix what it reveals using the free suite. `make grade-guardrails` is available as a cheaper intermediate rung (five intake calls) and is the only verification of SC-005 short of a full grade (finding G4) — it is a separate paid run needing its own go-ahead
- [ ] T110 **PAID — ask the operator first.** Run `make grade` once, late, and record the results from `auto-grader/results/grade_report.json` in `RESULTS.md`
- [ ] T111 Run the `quickstart.md` validation walkthrough end to end and confirm every story's stated independent test passes
- [ ] T112 Pre-submission check, run on the host (not in the image): `.env`, credentials and `.interview-tools/` excluded from the ZIP, `PACKET.json` retained, and `grep -rn ground-truth starter-kit/docker-compose.yml starter-kit/app/src` returning nothing — the compose-mount half of the old T057 (findings I1, Principle V). Also confirm `make test` passes with `.env` temporarily renamed away (finding C2)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately
- **Foundational (Phase 2)**: depends on Setup — **blocks every user story**
- **US1 (Phase 3)**: depends on Foundational. Delivers the MVP
- **US2 (Phase 4)**: depends on Foundational. Independent of US1, though both touch `routes_claims.py`
- **US3 (Phase 5)**, **US4 (Phase 6)**: depend on Foundational; deepen the tools US1 wired up
- **US5 (Phase 7)**: depends on Foundational; the recorder (T017) already exists, so this phase adds exposure and enforcement
- **US6 (Phase 8)**: depends on T043 (the rule pass built in US1) for its first detector, and on T026a for the script helper T085a edits. T085a runs **before** T086, so no earlier test is left with an exhausted script
- **US7 (Phase 9)**, **US8 (Phase 10)**: depend on Foundational; US8's richer assertions read best after US5
- **Polish (Phase 11)**: after the stories you intend to ship. T106 before T107; T107 before T109; T109 before T110

### Within Each User Story

- Tests are written first and must fail before implementation
- Pure functions (`areas.py`, table handlers) before the agents that call them
- Agents before the routes that expose them
- `domain/report.py` invariants before any assertion that depends on them

### File-contention warnings (do not mark these [P] against each other)

- `api/routes_claims.py` — T044, T052, T086, T092
- `agents/triage.py` — T040, T068, T077, T093
- `agents/safety.py` — T043, T083, T084, T085
- `domain/report.py` — T042, T045, T069, T094
- `tests/fakes/scripts/` and `tests/fakes/__init__.py` — T026a, T085a (T085a edits what T026a creates)
- `rag/ingest.py` — T058, T059
- `tools/search_past_claims.py` — T038, T061
- `tests/integration/test_triage_flow.py` — T031, T032, T049
- `tests/integration/test_trace.py` — T070, T071, T072, T073
- `tests/integration/test_multimodal.py` — T087, T088, T089
- `tests/integration/test_intake_rejection.py` — T046, T047
- `tests/integration/test_safety_ladder.py` — T080, T081
- `tests/unit/test_coverage.py` — T064, T066

### Parallel Opportunities

- Phase 1: T002, T003, T004, T006 together
- Phase 2: T010, T011, T014, T016, T017, T018, T019, T020, T021, T022, T023, T027, T029, T030 together
- Within each story, every test task marked [P] runs in parallel
- Once Foundational is done, US1–US8 can be staffed in parallel, respecting the contention list above

---

## Parallel Example: User Story 1

```bash
# All four US1 test tasks together (they must fail first):
Task: "T031 Integration test for the triage happy path in app/tests/integration/test_triage_flow.py"
Task: "T033 Failure-path tests in app/tests/integration/test_triage_failures.py"
Task: "T034 Invariant I3 unit test in app/tests/unit/test_report_invariants.py"

# Then the two pure modules together:
Task: "T035 Image handling in app/src/claim_triage/evidence/images.py"
Task: "T036 normalize_areas in app/src/claim_triage/domain/areas.py"
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Phase 1 Setup
2. Phase 2 Foundational — critical, blocks everything
3. Phase 3 US1
4. **Stop and validate**: a scripted submission returns a contract-conforming report, retrievable by
   id, with cost and scope provably copied from the trace
5. `make test` green, offline, no paid call

### Incremental Delivery

Setup + Foundational → US1 (MVP) → US2 (both P1 stories done, the vertical slice is honest) → US3,
US4, US5, US6 (the P2 quality and auditability layer) → US7, US8 (breadth and the browser) → Polish.

Each story leaves the suite green and the previous stories working.

### Budget Strategy (constitution Principle III)

Phases 1–10 cost nothing: every test runs against the fakes. The only paid commands are T107
(one capability probe), T109 (`grade-smoke`) and T110 (a single full `grade`), each run **only**
after asking the operator. If the probe fails, stop and report rather than retrying.

---

## Notes

- `[P]` = different files, no dependencies on incomplete tasks
- `[Story]` maps a task to its user story for traceability
- Verify each test fails before implementing against it
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently
- Never edit `openapi.yaml`; never mount or read `data/ground-truth/`; never print a credential
