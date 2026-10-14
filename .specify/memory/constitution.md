<!--
Sync Impact Report (scratch material for amendment review; remove before committing)
- Version change: none (unfilled template) -> 1.0.0
- Ratification: initial adoption; the previous file was the unmodified scaffold with all
  placeholders intact, so no prior governance content was superseded.
- Principles added (6; the scaffold offered 5 slots, one was added to keep each cluster testable):
  - [PRINCIPLE_1_NAME] -> I. Contract Fidelity
  - [PRINCIPLE_2_NAME] -> II. Reproducible Containerized Delivery
  - [PRINCIPLE_3_NAME] -> III. Human-Gated Paid Operations (NON-NEGOTIABLE)
  - [PRINCIPLE_4_NAME] -> IV. One Funded Credential, Local Embeddings
  - [PRINCIPLE_5_NAME] -> V. Secret and Answer-Key Isolation (NON-NEGOTIABLE)
  - (new) VI. Free, Injected, Failure-Covering Tests
- Sections added:
  - [SECTION_2_NAME] -> Operational Constraints
  - [SECTION_3_NAME] -> Development Workflow and Quality Gates
  - Governance filled from [GOVERNANCE_RULES]
- Sections removed: none
- Deferred TODOs: none
-->

# Claim Triage System Constitution

## Core Principles

### I. Contract Fidelity

`starter-kit/api-contract/openapi.yaml` is the authoritative interface specification and MUST NOT
be edited to match the implementation; the implementation changes instead. The four documented
endpoints (`POST /api/v1/claims/triage`, `GET /api/v1/claims/{claim_id}`,
`GET /api/v1/agent/trace/{claim_id}`, `GET /api/v1/health`) MUST exist at their published paths with
the published status codes. Every response body the service emits — success and error alike — MUST
be validated against the contract's schemas by an automated check, not by inspection. Required
fields are always present, enums only ever carry listed values, and `is_valid_image` is `null` only
for text-only submissions.

**Rationale**: The evaluator and the reviewing engineer both read the contract first. A response
that drifts from it fails checks that the underlying logic would otherwise pass, and schema
validation in tests is the only way to catch drift before a paid grading run does.

### II. Reproducible Containerized Delivery

The whole system MUST start from `docker compose up` in `starter-kit/` with no manual steps beyond
the supplied `.env`. The UI MUST be reachable at `http://localhost:3000` and the API at
`http://localhost:8000`, which are fixed ports and not configuration preferences. `make setup` MUST
build and start every service and leave `make health` passing; `make test` MUST run the project's
own suite. An LLM credential is the only permitted external dependency: a fresh clone on another
machine MUST reach a working triage with the funded key and nothing else.

**Rationale**: An interviewer runs these exact commands on a clean checkout. Work that only runs on
the author's machine scores as if it does not run.

### III. Human-Gated Paid Operations (NON-NEGOTIABLE)

No command that spends the shared allowance may be run without asking the operator first and
receiving an explicit yes for that specific run. This covers every live model request, every
`configure_access.py application-check` or `scripts/check_claude_access.py` invocation, `make setup`
while it performs a readiness check, `make grade`, `make grade-smoke`, and the per-category
`grade-*` targets. Approval is per-run and never standing: a yes to `grade-smoke` is not a yes to
`grade`. Exhausted budget or `429` responses mean stop and report — never retry in a loop and never
buy replacement credit.

**Rationale**: $30 covers application calls, coding assistance and grading together, and a single
full `make grade` runs 35 sequential model-backed accuracy cases. One unauthorized run can end the
exercise, so spending stays a human decision.

### IV. One Funded Credential, Local Embeddings

All LLM traffic MUST go through the funded Portkey gateway configured in `starter-kit/.env`
(`PORTKEY_API_KEY`, `PORTKEY_BASE_URL`, and the model route) using the routes published in
`ACCESS.json`. Native OpenAI or Anthropic endpoints, personal keys, and alternative providers are
prohibited. The backend receives these values through Compose `environment` or `env_file`, never
through values baked into an image or hardcoded in source. Embeddings MUST run locally, with the
model and its first-run download documented; introducing a second paid credential for retrieval is
prohibited. TLS verification stays on, and a certificate error is escalated rather than disabled.

**Rationale**: The gateway is what the funded allowance is attached to and what the reviewer can
account for. Local embeddings keep retrieval free, offline-capable and outside the budget.

### V. Secret and Answer-Key Isolation (NON-NEGOTIABLE)

`.env` values MUST NOT be printed to a terminal, written to a log, embedded in an error message,
included in the video or committed; diagnostics name the variable and whether it is set, never its
value. `data/ground-truth/` is a development answer key: it MUST NOT be mounted into any application
container, read by any runtime code path, or consulted through filename correspondence such as
`IMG_001.jpg` to `IMG_001.json`. It is permitted only in offline measurement that the running
service cannot reach. Submissions exclude `.env`, credentials and `.interview-tools/`, and retain
`PACKET.json`.

**Rationale**: A leaked key ends access for everyone sharing it, and a service that can see the
answer key produces a score that measures nothing. Both failures are unrecoverable after the fact.

### VI. Free, Injected, Failure-Covering Tests

A single `make test` MUST run the project's own suite to completion with zero paid model calls,
using a fake LLM, fake or local embeddings and an in-memory vector store — no network, no Qdrant
container, no API key required. The suite MUST cover at least one failure path per error status the
contract declares (400 from failed intake validation, 404 for an unknown claim or trace, 422 from a
failed output safety check), and MUST assert every response against `openapi.yaml` per Principle I.
Every external dependency — model client, embedding model, vector store, clock, filesystem — MUST
be injected at a seam so a test can substitute it; code that constructs its own provider inside a
request handler is not acceptable.

**Rationale**: Tests that cost money get run once and then avoided, which defeats their purpose.
Injection is what makes a free suite possible, and failure paths are where contract compliance and
error handling are actually judged.

## Operational Constraints

- **Paid-operation ladder**: at most one capability probe early in the project to confirm the
  gateway, route and image-input support work; `make grade-smoke` (three positive cases) while
  iterating; and a single full `make grade` once, as late as is useful. Each rung needs its own
  approval under Principle III.
- **Model routes**: the application route and the Claude route both come from `ACCESS.json`; the
  gateway root is used without `/v1` for the Anthropic Messages interface and with `/v1` for the
  OpenAI-compatible interface. The key travels in `x-portkey-api-key`, and the provider route in
  `x-portkey-provider` for Anthropic-SDK calls.
- **Readiness check**: because this project calls Claude through the gateway's Messages API rather
  than the packet's default Chat Completions route, `make setup` runs
  `starter-kit/scripts/check_claude_access.py` as the documented equivalent readiness check with
  `CHECK_PORTKEY=0`. That substitution MUST stay documented in the README and MUST NOT be presented
  as a successful run of the packet's own Portkey check.
- **Agents**: the three required agents (`intakeValidator`, `triageAgent`, `safetyChecker`) and the
  three required tools (`search_past_claims`, `estimate_repair_cost`, `check_coverage`) are a floor,
  not a menu. `triageAgent` runs an observable ReAct loop with paired act/observe steps; a
  single-shot prompt does not satisfy it. `estimate_repair_cost` and `check_coverage` read
  `tools/cost-estimator.json` and `tools/coverage-table.json` — their outputs stay consistent with
  those tables and with the final report.
- **Traces**: exported traces carry concise action-purpose summaries, tool names, tool inputs and
  actual observations. Private model reasoning MUST NOT be exposed.
- **Retrieval corpus**: `data/knowledge-base/` is the only runtime retrieval source, per
  Principle V.
- **Evaluator posture**: a suspected grader defect is reported in `RESULTS.md`, not worked around by
  changing behavior to satisfy a check the requirements do not ask for.

## Development Workflow and Quality Gates

- Build a thin end-to-end vertical slice first — intake, one ReAct cycle, contract-shaped response —
  then widen to retrieval, evidence handling and guardrails. A narrow working path outranks broad
  unfinished scaffolding.
- `make test` MUST pass before any change is committed. A failing or skipped suite is reported as
  such, never described as passing.
- Contract changes in behavior are validated by the schema assertions of Principle VI before any
  paid verification is proposed.
- Paid verification is a gate, not a loop: fix what the free suite and `grade-smoke` reveal before
  requesting the single full `make grade`.
- Deliverables tracked as first-class work, not afterthoughts: `README.md` (architecture diagram,
  model and vector-DB choices with reasons, setup, trade-offs, limitations, next steps),
  `AI_USAGE.md` (tools, delegation, corrections, validation), `RESULTS.md` (measurements and
  remaining limitations).
- Unfinished work is stated plainly in `RESULTS.md` and the video, with what remains and what would
  come next. Incomplete and honest outranks complete-sounding and unverified.

## Governance

This constitution supersedes ad-hoc preference and convenience for the duration of the exercise.
Where it conflicts with a generated plan, spec or task list, this document wins and the artifact is
corrected.

**Amendment procedure**: amendments are proposed to the operator with the principle affected, the
reason, and the proposed replacement text; they take effect only once the operator approves and this
file is updated in the same change. Principles III and V are marked NON-NEGOTIABLE: they may be
amended but never waived for a single run, and no plan, task or agent instruction may create an
exception to them.

**Versioning policy**: semantic versioning of this document. MAJOR for removing or redefining a
principle in a backward-incompatible way; MINOR for a new principle or materially expanded guidance;
PATCH for clarifications and wording that change no obligation. The version line below is updated in
the same change as the content it describes.

**Compliance review**: every plan and task list generated for this project is checked against these
principles before implementation starts, and any deviation is justified in writing or dropped.
Before a paid verification run and before submission, the operator confirms that Principles I, II,
V and VI hold: contract validation passes, `docker compose up` yields a healthy API on 8000 and UI
on 3000, no secret or ground-truth path has leaked into the application or the repository, and
`make test` passes offline with no paid calls.

**Version**: 1.0.0 | **Ratified**: 2026-10-14 | **Last Amended**: 2026-10-14
