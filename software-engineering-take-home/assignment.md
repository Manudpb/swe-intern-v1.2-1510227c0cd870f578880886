# Software Engineering Intern Assignment: Home Damage Claim Triage

An insurance technology company is building an **AI-powered claim triage system** to help adjusters process incoming property damage claims faster and more consistently. Claimants submit damage photos, text descriptions, and supporting documents. The system must analyze the submission, research similar past claims, and produce a structured triage report.

Your task is to build a **multi-agent system** with a ReAct (Reason + Act) loop, backed by a vector knowledge base of historical claims, exposed through a lightweight web UI that supports multi-modal inputs.

You may use any programming language or framework. Bain provides funded OpenAI/Anthropic model access through a candidate-specific Portkey key for your application and compatible coding assistant; see [API_ACCESS.md](API_ACCESS.md). Local models or another provider are permitted if you already have suitable access, but no personal purchase is expected. We care about your decisions, not your vendor choice.

**Expected effort**: roughly four hours, including tests and documentation. This is a planning estimate, not a time limit; you may take longer and do not need to stop after four hours. If the exercise starts taking substantially longer than expected, you do not need to complete every requirement. Incomplete submissions are welcome; explain what works, what remains unfinished and what you would do next in both your video and `RESULTS.md`. Follow the submission deadline in your invitation. This is a build-from-materials exercise: the starter kit contains no backend or frontend implementation.

For this intern exercise, prioritize a working vertical slice and basic validation, then expand toward the requirements below. The full evaluator shows coverage of those requirements; an incomplete score is not an automatic hiring rejection. No prior insurance expertise or production architecture experience is expected.

---

## 1) System Architecture

Build a system composed of the following agents and capabilities:

### 1.1 Intake Validation Agent: `intakeValidator`

Validates the incoming submission before processing. Returns a structured check:

| Field | Type | Description |
|---|---|---|
| `is_property_damage` | boolean | Image shows property/structural damage |
| `is_valid_image` | boolean or null | Image is clear enough to assess (not blurry, not a screenshot of text) |
| `no_pii_detected` | boolean | No visible personal information (SSN, credit cards, etc.) |
| `no_offensive_content` | boolean | No inappropriate or irrelevant content |

If a check is false, reject with HTTP 400, the intake flags and a clear reason; do not proceed to triage. For text-only input, set `is_valid_image` to null and state that visual evidence was unavailable. Evaluate the other checks against the text. Payment-card images, including synthetic test cards, are unsuitable and must set `no_pii_detected` to false.

### 1.2 Triage Agent (ReAct Loop): `triageAgent`

This is the core of the system. Given a validated claim submission (image + text description + optional documents), the agent must **reason about what information it needs, take actions using tools, observe results, and iterate** until it can produce a complete triage assessment.

The agent must implement a **ReAct loop** — not a single-shot prompt. The agent should demonstrate observable Reason → Act → Observe cycles in its execution trace.

**Required tools** (you must implement at least these three):

#### Tool 1: `search_past_claims`
Search the vector knowledge base of historical claims for similar incidents.
- **Input**: `query` (string) — natural language description of the damage
- **Output**: List of similar past claims with similarity scores
- **Implementation**: You must embed the provided historical claims into a vector store and perform semantic search.

#### Tool 2: `estimate_repair_cost`
Estimate repair costs based on damage characteristics.
- **Input**: `damage_type` (enum), `severity` (enum), `affected_areas` (list of strings)
- **Output**: Cost range `{ min, max, currency }`
- **Implementation**: Use the provided cost estimation lookup table (`tools/cost-estimator.json`).

#### Tool 3: `check_coverage`
Check what a given policy type covers for the incident category.
- **Input**: `policy_type` (enum), `incident_category` (enum)
- **Output**: Coverage details `{ covered, deductible, max_payout, notes }`
- **Implementation**: Use the provided coverage table (`tools/coverage-table.json`).

**Triage output schema:**

```json
{
  "damage_type": "water_damage | fire_damage | storm_damage | break_in | vandalism | other",
  "severity": "minor | moderate | severe | catastrophic",
  "affected_areas": ["kitchen", "basement"],
  "damage_description": "Free-text description of observed damage",
  "estimated_repair_cost": {
    "min": 3500,
    "max": 7000,
    "currency": "USD"
  },
  "urgency": "low | medium | high | critical",
  "recommendation": "Free-text next-steps recommendation for the adjuster",
  "similar_past_claims": [
    {
      "claim_id": "CLM-2023-847",
      "similarity_score": 0.89,
      "resolution_summary": "Short summary of how the similar claim was resolved"
    }
  ]
}
```

### 1.3 Output Safety Agent: `safetyChecker`

Reviews the triage output and blocks responses that contain:

| Field | Type | Description |
|---|---|---|
| `no_coverage_promises` | boolean | Does not guarantee or promise coverage |
| `no_legal_advice` | boolean | Does not provide legal counsel or liability opinions |
| `no_settlement_amounts` | boolean | Does not state specific settlement/payout figures |
| `no_liability_determination` | boolean | Does not assign fault or blame |
| `no_emotional_language` | boolean | Maintains professional, neutral tone |

If any safety check fails, the system should sanitize or regenerate the output before returning it.

---

## 2) Provided Assets

Your starter kit contains:

```
starter-kit/
├── docker-compose.yml          # Pre-configured vector DB; add your services
├── Makefile                     # Build, run, test, and grade commands
├── data/
│   ├── knowledge-base/         # ~30 historical claim records (JSON) — embed these
│   ├── test-images/            # 40 synthetic images: 35 damage cases and 5 rejection cases
│   ├── test-documents/         # Three fictional PDF estimates/inspection reports
│   └── ground-truth/           # Expected triage outputs for auto-grading
├── api-contract/
│   └── openapi.yaml            # API specification your service must implement
└── tools/
    ├── cost-estimator.json     # Lookup table for repair cost estimation
    └── coverage-table.json     # Policy coverage lookup table
```

### Key conventions:
- Image filenames match ground truth filenames: `test-images/IMG_001.jpg` ↔ `ground-truth/IMG_001.json`
- Historical claims in `knowledge-base/` are your RAG source — embed them into your vector store
- The `docker-compose.yml` includes a Qdrant vector database. You may swap it for another vector DB if you prefer, but document your choice.

---

## 3) Technical Requirements

### 3.1 API Contract

Your service must expose the following endpoints (see `api-contract/openapi.yaml` for full spec):

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/claims/triage` | Submit a claim for triage (multipart: image + text + optional PDF) |
| `GET` | `/api/v1/claims/{id}` | Retrieve a completed triage report |
| `GET` | `/api/v1/health` | Health check (returns 200 when ready) |
| `GET` | `/api/v1/agent/trace/{id}` | Return the ReAct execution trace for a triage run |

The `/agent/trace/{id}` endpoint returns the execution events for the claim. Log concise action-purpose summaries, tool names and inputs, and actual observations; do not expose private model reasoning. Pair each action with its observation in the exported trace. Retrieval observations may be a list of records or an object containing `claims`. The evaluator checks basic structure and consistency with the lookup tables and final report; a trace alone cannot prove model execution.

### 3.2 Infrastructure

- Everything must run via `docker compose up`
- A `make setup` command should build and start all services
- A `make test` command should run your own test suite
- The system must be fully functional with only an LLM API key as external dependency

### 3.3 UI

Build a lightweight web UI that allows a user to:
1. Upload one or more damage photos
2. Enter a text description of the incident
3. Optionally upload supporting documents (PDF)
4. Submit the claim and view the structured triage report
5. View tool execution and concise action-purpose summaries (the ReAct steps; no private model reasoning)

The UI does not need to be polished — functional is sufficient. You may use any frontend framework or even a simple HTML page.

### 3.4 Multi-Modal Input

Your system must handle these input combinations:
- Image only
- Image + text description
- Image + text + PDF document
- Text only (must produce a triage for a valid description, noting limited confidence without visual evidence)

Use multipart `image` for a single photo or repeated `images` fields for multiple views of the same incident. At least an image or a non-blank description is required. Additional views do not multiply affected areas. PDF text is evidence: use same-incident inspection findings to update the scope, and explain unresolved conflicts. Contractor quotes do not replace the structured estimate from the supplied cost table.

Count distinct affected rooms or exterior components once. Do not count a room again for its floor/wall, or a specific component again under a generic label such as `interior`. The historical corpus provides context; ground-truth records are development answer keys and must not be used as runtime retrieval material or filename-based answers.

---

## 4) Evaluation Criteria

Your submission receives a diagnostic score out of 100: **20 points from automated checks (`make grade`) and 80 from manual review**. The video carries 50 points because explaining your implementation, choices and limitations is central to the assessment. This score is diagnostic only; hiring decisions also consider the live discussion and other interview evidence, with no automatic score cutoff. Presentation polish does not replace technical understanding.

### 4.1 Auto-Graded Components (20 points)

| Category | Points | What we check |
|---|---|---|
| **Infrastructure** | 3 | HTTP readiness, API/UI availability and required input combinations (including document use) |
| **ReAct Loop** | 6 | Trace structure, substantive tool inputs/outputs, and agreement with the final report; actual execution also needs code review |
| **RAG / Embeddings** | 4 | Store population, known claim IDs, and basic relevance; embedding quality also needs manual review |
| **Triage Accuracy** | 4 | Damage type, severity, cost estimate accuracy vs. ground truth |
| **Guardrails** | 3 | Input validation and output safety checks match ground truth booleans |

### 4.2 Manually Reviewed Components (80 points)

| Category | Points | What we look for |
|---|---|---|
| **Code Quality** | 15 | Readable structure, appropriate dependencies, error handling, configuration and validation |
| **Architecture / Trade-offs** | 15 | README explains choices (model, framework, vector DB), trade-offs, limitations and next steps |
| **Video Walkthrough** | 50 | Demonstrates what works and explains architecture, decisions and one technical topic with concrete evidence; clear communication, not production polish |

### 4.3 Interpreting automated results

The public grader is a development aid. The stated requirements are the goal; report suspected evaluation defects rather than changing behavior merely to satisfy a misleading check. Interviewers run a clean evaluator copy and may rename inputs or use additional cases within the same published requirements.

Each automated category receives its published points multiplied by its passing-check proportion. UI and multimodal checks are part of the 3-point infrastructure category, not extra points. Skips/errors receive no passing credit and make the evaluation incomplete. Alternative vector stores are permitted; checks that require direct database inspection need interviewer verification for those implementations.

The accuracy category reports aggregate damage-type correctness (minimum 50%), severity score (exact=1, adjacent=0.5; minimum mean 0.4), and repair-cost midpoint accuracy (`max(0, 1 - absolute_percentage_error)`; minimum mean 0.3). These are initial acceptance thresholds, not evidence of perfect accuracy or hiring cutoffs. All positive cases remain in the denominator, including rejected requests and provider failures. The same batch is reused across accuracy checks. Recommendation presence and output structure are also checked; recommendation quality and semantic safety are reviewed by a person, not an implemented LLM judge.

The photos and PDFs are synthetic development fixtures, with provenance in `data/ASSET-SOURCES.json`. Their labels are exercise references, not professional damage appraisals. Explain uncertainty and reasonable differences in scope; interviewers consider the evidence as well as the automated result.

---

## 5) Deliverables

### 5.1 Codebase with README

Write a concise README that helps an engineer from the client run and understand your submission. Clear, useful documentation matters more than length or polish.

- [ ] Working codebase in a Git repository
- [ ] README covering:
  - Architecture diagram (can be ASCII or an image)
  - Which LLM provider/model(s) you chose and why
  - Setup instructions (`make setup` should be sufficient)
  - Any trade-offs, limitations, or known issues
  - What you would improve given more time
- [ ] Tests for important behavior and at least one failure case, runnable with your documented test command
- [ ] A short `AI_USAGE.md` describing tools, delegation, corrections and validation
- [ ] The original `PACKET.json` identifier

### 5.2 Intern Screen Recording (max 5 minutes)

Record a short presentation of your work for a technical audience. **The video must be in English.** Give context, demonstrate what works, and walk through your architecture and key decisions. If your submission is incomplete, explain what remains unfinished and what you would do next. Choose one topic to explore a little more closely—for example, how a claim moves through the ReAct loop and what its trace shows. Focus on the parts that best explain your approach rather than trying to cover every detail.

Use Clipchamp or another screen recorder. Please keep your camera on; contact the invitation sender if you need an alternative. Do not edit the video or prepare slides; production polish earns no additional credit. We assess how clearly you explain and present your work.

### 5.3 Submission

Upload both of the following through the link in your invitation:

- A ZIP of your solution as it stands: source code, tests, data, dependency and Docker configuration, README, `AI_USAGE.md`, `RESULTS.md`, and the original `PACKET.json`. Exclude credentials, `.env` files, local environments and generated dependency folders.
- Your recorded presentation as an MP4, uploaded separately to the same link.

Keep your submission private. We will discuss your work in the live follow-up.
