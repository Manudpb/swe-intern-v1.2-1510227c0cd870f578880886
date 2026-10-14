# Home-Damage Claim Triage Service

An AI-powered triage service for property-damage claims. An adjuster submits damage photos, a
description and an optional PDF; the service screens the submission, runs a ReAct loop over
Claude with three tools and a vector search of 30 historical claims, and returns a structured
report with an inspectable execution trace.

## Architecture

### Services

```text
                      ┌──────────────────────────────┐
  browser ───────────▶│ ui  :3000  (FastAPI + Jinja2)│  server-rendered, no CORS:
                      │  GET /   POST /submit        │  the page only ever talks
                      │  GET /api/v1/agent/trace/..  │  to its own origin
                      └──────────────┬───────────────┘
                                     │ httpx, over the Compose network
                      ┌──────────────▼───────────────┐      ┌──────────────────┐
                      │ api :8000  (FastAPI)         │─────▶│ qdrant :6333     │
                      │  POST /api/v1/claims/triage  │      │ 30 claims, 384-d │
                      │  GET  /api/v1/claims/{id}    │      └──────────────────┘
                      │  GET  /api/v1/agent/trace/{id}│
                      │  GET  /api/v1/health         │─────▶ Claude (claude-opus-5)
                      └──────────────────────────────┘       via the funded Portkey
                                                             gateway
```

### One triage request, start to finish

The three agents are **sequential stages, not parallel workers**. Each stage is a gate: it can
end the request, and only a submission that clears all of them becomes a report.

```text
  POST /api/v1/claims/triage   (image(s) + description + optional PDF + policy_type)
        │
        │   at least one image or a non-blank description, else ──────────▶ 400
        ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │ 1. intakeValidator                          1 Claude call, images attached  │
  │    is_property_damage · is_valid_image · no_pii · no_offensive_content      │
  └─────────────────────────────────────────────────────────────────────────────┘
        │
        ├── any check false ──▶ 400 + the four flags + a plain-language reason
        │                       
        ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │ 2. triageAgent — the ReAct loop            ≤ 6 rounds, native tool calling  │
  │                                                                             │
  │    reason ─▶ act ─▶ observe ─▶ reason ─▶ act ─▶ observe ─▶ …             │
  │      │        │                                                              │
  │      │        ├──▶ search_past_claims    fastembed → qdrant :6333           │
  │      │        ├──▶ estimate_repair_cost  cost-estimator.json — the ONLY     │
  │      │        │                          source of money in the system      │
  │      │        ├──▶ check_coverage        coverage-table.json                │
  │      │        └──▶ submit_triage         terminal; has NO cost field        │
  │      │                                                                      │
  │      └── every step recorded to the trace as it happens                     │
  └─────────────────────────────────────────────────────────────────────────────┘
        │
        ├── round cap hit, or no successful pricing ──▶ 503 (never a guess)
        ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │ 3. report assembly                                   domain/report.py       │
  │    damage_type · severity · affected_areas  ← COPIED from the last          │
  │    estimated_repair_cost                      successful cost call's        │
  │                                               arguments and output          │
  │    similar_past_claims ← intersected with what retrieval actually returned  │
  └─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │ 4. safetyChecker            rule pass AND Claude review — both must agree  │
  │    violation ─▶ 1 rewrite (broken rules named) ─▶ re-check ─▶ sanitize     │
  └─────────────────────────────────────────────────────────────────────────────┘
        │
        ├── still violating after the ladder ──▶ 422 + the failing limits
        ▼
  5. claim_id issued, report and trace stored ──────────────────────────▶ 200

     GET /api/v1/claims/{claim_id}        the stored report, byte-identical
     GET /api/v1/agent/trace/{claim_id}   the recorded reason/act/observe steps
```



## Model and infrastructure choices

| Choice | What and why |
|---|---|
| **LLM** | `claude-opus-5` through the funded Portkey gateway, via the Anthropic Messages API. Strong vision for intake screening and reliable native tool calling, which is what the ReAct loop is built on. The gateway root is used **without** `/v1`, the model id **unprefixed**, and the provider route in `x-portkey-provider` — the shape `scripts/check_claude_access.py` already proves against the live gateway. |
| **Embeddings** | `fastembed` with `BAAI/bge-small-en-v1.5` (384-d, ~130 MB), **baked into the image at build time** so the first container start needs no download. Local by design: retrieval must not need a second paid credential. |
| **Vector DB** | Qdrant, the supplied service. One collection, `historical_claims`, 30 points, cosine. Ingestion at startup is idempotent (point ids derive from the claim id), so a restart re-embeds nothing. |
| **API / UI** | FastAPI for both, one image, two entrypoints. The UI is server-rendered HTML with one stylesheet and one small script; the form posts to the UI service, which forwards to the API over the Compose network. No CORS surface and no frontend build step. |
| **Structured output** | A `submit_triage` tool whose input schema *is* the report schema. Provider-validated, with no JSON-in-prose to parse. It deliberately has **no cost field**. |

## Setup

From this directory:

```sh
make setup        # readiness check, then compose up --wait, then make health
```

> **`make setup` spends money.** It runs one small paid Claude request first and stops the
> startup if access fails. To bring the stack up without spending anything:
>
> ```sh
> docker compose up --build -d --wait --wait-timeout 180
> make health
> ```

- API: <http://localhost:8000/api/v1/health>
- UI: <http://localhost:3000>
- Qdrant: <http://localhost:6333/collections>

The first build downloads the embedding model (~130 MB); later builds use the cached layer.


## Trade-offs and limitations

- **Safety checking is two detectors, and costs calls.** Every report is screened by a lexical
  rule pass and a  Claude review; a limit passes only if both agree. It adds 1 paid call per triage and up to 3 on the rewrite path. 
- **Reports live in memory** for the process lifetime. A restart loses them. Durable storage was
  out of scope for a pilot; the vector index persists in its own volume.
- **Cost is computed, not judged**: the model never states a number. But it's computed from the model's classification, so its accuracy is bounded by how well the model judges severity and counts areas.

- **No authentication.** Single-tenant internal pilot, no adjuster accounts or audit identities.


- **Latency is the real weak point.** p50 48.3 s across the 35 graded cases, against the
  starter README's 10-28 s assumption and a 120 s per-case ceiling. Five to six sequential
  model calls per triage is the cause; the safety review is one of them.







## What I would do next
1.


   add pagination for a queue view.
3. **Cache intake by image hash.** The same photo resubmitted should not pay for screening twice.
4. **Make the safety reviewer or the intake validator cheaper**, by batching the two text fields of several reports into
   one call, or by routing it to a smaller approved model.
5. **Stream the trace** to the page over SSE so an adjuster watches the loop instead of waiting.
6. **Confidence on the report**, derived from retrieval scores and evidence completeness, so an
   adjuster can see which assessments to double-check.


