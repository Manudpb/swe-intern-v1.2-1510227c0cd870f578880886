# Contract: Internal ports and test doubles

Principle VI requires every external dependency to sit behind a seam a test can substitute. These
are the seams. All are `typing.Protocol`s in `claim_triage/deps.py` (or `llm/ports.py`), and nothing
in a request handler constructs its own provider.

## The injection point

```text
create_app(deps: Deps) -> FastAPI
build_deps(settings: Settings) -> Deps     # production wiring, called only from main
```

`Deps` is a frozen dataclass:

| Field | Port | Production | Test double |
|---|---|---|---|
| `llm` | `LLMClient` | `AnthropicPortkeyClient` | `FakeLLM` |
| `embedder` | `Embedder` | `FastEmbedEmbedder` (BAAI/bge-small-en-v1.5) | `FakeEmbedder` (deterministic) |
| `vectors` | `VectorStore` | `QdrantStore` (server at `qdrant:6333`) | `QdrantStore` over `QdrantClient(":memory:")` |
| `cost_table` | `CostTable` | real `tools/cost-estimator.json` | **the same real file** |
| `coverage_table` | `CoverageTable` | real `tools/coverage-table.json` | **the same real file** |
| `reports` | `ReportStore` | bounded in-memory LRU | same |
| `clock` | `Clock` | `datetime.now(timezone.utc)` | fixed, advancing by a fixed step |
| `new_id` | `IdFactory` | `uuid4` | counter (`claim-0001`, …) |
| `settings` | `Settings` | env-derived, redacting | test values, never a real key |

A fixed clock and a counter id factory are what make trace assertions exact instead of approximate.

## Port signatures

```text
LLMClient.create_message(*, system: str, messages: list[dict], tools: list[dict],
                         max_tokens: int, temperature: float) -> LLMResponse
```

`LLMResponse` exposes `stop_reason`, `text_blocks` and `tool_calls` (each with `id`, `name`,
`input`), so the orchestrator never touches a vendor type.

```text
Embedder.embed(texts: list[str]) -> list[list[float]]      # dimension stable per instance
Embedder.dimension: int

VectorStore.ensure_collection(name, dim) -> None
VectorStore.upsert(name, points) -> None                    # idempotent, deterministic ids
VectorStore.search(name, vector, top_k) -> list[ScoredPoint]
VectorStore.count(name) -> int                              # health signal
```

## FakeLLM

Three jobs beyond replaying a response.

**1. Routes by system prompt.** Each agent's system prompt carries a marker (`intake`, `triage`,
`safety`); the fake pops the next scripted turn for that route. An unknown marker, or an exhausted
script, raises — a silent extra model call is a bug, not a pass.

Because the safety review now runs on **every** triage (research D9), every integration script must
include at least one `safety` turn, and a violating-path script needs three (review, rewrite,
re-review). A missing turn surfaces as an exhausted-script error, which is the point: the gate
cannot be skipped by forgetting to script it.

**2. Records every request.** `fake.calls` holds the full kwargs of each call, which is how tests
assert the things a response cannot show:

- the model id is unprefixed (no `@`, no `/`)
- `max_tokens` is set and positive
- images were downscaled before upload (base64 payload under the expected bound)
- the system prompt and messages never contain the credential
- the tool list matches the registry, with no duplicate names

**3. Rejects shapes the real API refuses.** Raises `FakeLLMContractError` on:

| Rejection | Why it matters |
|---|---|
| missing or non-positive `max_tokens` | required by the Messages API |
| `model` containing `@` or `/` | that is the OpenAI-style prefixed route, wrong for this interface (research D1) |
| `tool_result` whose `tool_use_id` matches no prior `tool_use` | the most common loop-assembly bug |
| assistant turn ending in `tool_use` without the following `tool_result` | conversation would be rejected mid-loop |
| empty `content` list, empty text block, unknown `role` | malformed turn |
| image `media_type` outside `image/jpeg|png|gif|webp`, or raw bytes instead of base64 | silently breaks vision |
| duplicate tool names, or an `input_schema` that is not an object schema | tool registration bug |

This is the suite's substitute for a paid integration test: it moves "the request shape was wrong"
from a billed discovery into `make test`.

## FakeEmbedder

Hashes tokens into a 384-dim vector with signed buckets and L2-normalizes, so cosine similarity
tracks term overlap. Deterministic across machines and Python runs (explicit seed, no `hash()`
randomization). Real enough that "a burst-pipe query ranks a water-damage claim first" is a genuine
assertion over the real 30-record corpus.

## What is deliberately *not* faked

The cost table, the coverage table and the knowledge base are the real files. Faking them would make
every arithmetic and retrieval test a tautology, and these are the values the evaluator checks
against.
