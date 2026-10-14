# AI usage

- **Tools and models used**: Claude Code (Opus) through the funded Portkey gateway, driven with
  the Spec Kit workflow — `/speckit-constitution` → `specify` → `plan` → `tasks` → `analyze` →
  `implement`. The artifacts it produced are in `specs/001-claim-triage-service/` and the
  project rules it worked under are in `.specify/memory/constitution.md`. The application itself
  calls `claude-opus-5` through the same gateway.

- **What I delegated and what I checked myself**: 
  - Delegated: the implementation of each task
    and the test suite. 
  - Checked myself: 
    - the stack (FastAPI, own agent loop with native tool
      calling, Qdrant, fastembed, server-rendered UI), the test strategy (DI via `create_app(deps)`,
      a FakeLLM that replays SDK-shaped responses *and* rejects request shapes the real model
      refuses, in-memory Qdrant with the real knowledge base, contract tests against
      `openapi.yaml`)
  
    - Supervised each decision having the last word when ambiguity was presented.

- **One suggestion I corrected or rejected, and why**: the first draft of the safety design made
  the Claude review optional and off by default, keeping only a lexical word-list check, to
  save budget. I rejected it: a word list never catches a paraphrased promise like "you can
  rest assured this will be taken care of", which is exactly the kind of sentence that creates
  legal exposure. I replaced it with the design now implemented: both detectors on every
  report, a limit passing only when both agree, then one rewrite naming the broken rules, then
  sanitization, then 422 accepting the extra paid call per triage as the cost of a real
  semantic gate. 
- **How I validated the generated code and final behaviour**: 
  - 234 automated tests (`make test`, no paid calls)
  - live scenarios against the running stack: image + text, inspection PDF, contractor quote, text-only, multiple photos, and all five rejection images;

  - make grade-smoke and make grade (see RESULTS.md);

  - manual review of report wording and of the trace.
  
- **Approximate active engineering time, excluding initial installation/access checks**: roughly
  4 hours across one session.
- **Setup/access time and interruptions, recorded separately**: about 30 minutes setup time + 15 minutes interruption.
