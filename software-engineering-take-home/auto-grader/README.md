# Public acceptance checks

These checks evaluate an application's observable behavior. They do not establish who wrote it, prove that a trace represents real execution, or make a hiring decision.

From `starter-kit/`, start the candidate's services with `make setup`, then run `make grade`. The grader uses the sibling `auto-grader/` directory and reaches services through `host.docker.internal`. Override `API_URL`, `UI_URL` and `QDRANT_URL` if needed. The report is written to `auto-grader/results/grade_report.json`.

The diagnostic submission score is **20 automated + 80 manual points**. Automated weights are infrastructure 3, agent loop 6, RAG 4, accuracy 4 and guardrails 3. Manual review covers code quality 15, architecture/trade-offs 15 and video walkthrough 50. The score is diagnostic only and does not determine a hiring rating. Category points equal the published category weight times its passing-check proportion. All checks, including skipped/error cases, stay in that denominator. Missing evidence makes the report incomplete. Exit codes: `0` complete/all checks pass, `1` complete/some checks fail, `2` incomplete evaluation. None is a hiring recommendation.

The accuracy checks reuse one batch of all 35 positive cases, including failed requests. The five negative cases are assessed separately in guardrails. UI and multimodal checks belong to the infrastructure category. Recommendation quality, semantic safety, actual tool execution and embedding quality require interviewer inspection. Direct Qdrant checks need equivalent manual verification when a candidate uses another permitted store.

## Using the results

Run your own application tests as well as these checks. Explain incomplete functionality, provider failures and alternate-store checks in `RESULTS.md`. Report suspected evaluation defects through the invitation sender. Interviewers use a clean evaluator copy and consider the implementation and stated assumptions alongside the report.

Use `make grade-smoke` from `starter-kit/` while iterating: it exercises three varied positive cases and does not produce a full grade. `make grade` always runs all 35 accuracy cases, sequentially, reusing their results across checks. At 10–28 seconds per triage, accuracy alone takes about 6–16 minutes. Progress streams to the console; per-case timings and failures are saved incrementally in `auto-grader/results/accuracy_full.json` (or `accuracy_smoke.json`). The full accuracy timeout allows 35 × 120 seconds plus startup; failed requests still count.
