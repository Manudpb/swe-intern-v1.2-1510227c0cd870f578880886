# Contract: HTTP API

**Authority**: `software-engineering-take-home/starter-kit/api-contract/openapi.yaml` — read-only.
This file records how the implementation binds to it and the one documented addition. Where this
file and the YAML disagree, the YAML wins (Principle I).

## Endpoints

| Method | Path | Declared responses | Implementation notes |
|---|---|---|---|
| `POST` | `/api/v1/claims/triage` | 200, 400, 422 | multipart; `image` and/or repeated `images`, `description`, `document`, `policy_type` |
| `GET` | `/api/v1/claims/{claim_id}` | 200, 404 | returns the stored report unchanged |
| `GET` | `/api/v1/agent/trace/{claim_id}` | 200, 404 | 404 until the run completes |
| `GET` | `/api/v1/health` | 200 | `status` is pinned to `healthy` by the schema |

## Request binding for `POST /claims/triage`

- `image` (single file) and `images` (repeated) are both accepted and merged into one view list;
  0–5 images, each ≤ 10 MB, `image/jpeg` or `image/png`.
- `description` — optional string; blank is treated as absent.
- `document` — optional `application/pdf`.
- `policy_type` — optional; absent means `standard_homeowner`.
- A request with no image and no non-blank description is rejected. A request with **no body at all**
  is rejected by request parsing (422), which the published checks accept alongside 400.

## Response bodies

`200` → `TriageResponse` = `{claim_id, intake_validation, triage_assessment, safety_checks}`, all
four required.

`400` → `ValidationError` = `{error, intake_validation, message}`. `message` is non-empty prose
naming what failed. **No** `triage_assessment` key is present.

`404` → body unconstrained by the contract; the implementation returns `{error, message}`.

`422` → `SafetyError` = `{error, safety_checks, message}`, used **only** when the safety gate cannot
produce deliverable text, and for request-parsing failures emitted by the framework.

`200` on `/health` → `{status: "healthy", services: {vector_db: connected|disconnected, llm:
configured|not_configured}}`.

## The documented addition: 503

Not declared in the YAML. Used for exactly two conditions, never for client-caused failures:

| Condition | Body |
|---|---|
| Model access unreachable, timed out, rate-limited (429), or returning an error after the single permitted retry | `{error: "upstream_unavailable", message: "..."}` |
| Service not ready — archive missing or under-populated — on `/health` | `{status: "unhealthy", services: {...}}` |

Rationale and rejected alternatives are in [research.md D8](../research.md) and the plan's Complexity
Tracking. A 429 from the gateway never triggers a retry; it surfaces as 503 with a message telling
the operator to pause and check the allowance.

## Conformance testing

One helper, used by every API test:

```text
assert_conforms(path_template, method, status, body)
```

It loads the YAML once, resolves `#/components/schemas` refs through a `referencing` registry, and
validates with the Draft 2020-12 validator plus a format checker for `date-time`. Rules the suite
enforces:

1. Every 200/400/422 body validates against its declared schema.
2. Enum fields are tested at their boundaries — a response carrying a value outside the enum fails.
3. `intake_validation.is_valid_image` is `null` **only** in the text-only case.
4. 503 appears only for the two conditions above (asserted by injecting an LLM port that raises).
5. Each declared status has at least one failure-path test: 400 (each of the four intake flags), 404
   (unknown report id, unknown trace id), 422 (unsanitizable text), 503 (upstream failure).
