# Software Engineering Intern Take-home

Build a small application that helps an insurance adjuster triage fictional home-damage claims. Use photos, text and supporting PDFs to produce a structured report, supported by tools and retrieval from historical claims. The full specification is in [assignment.md](assignment.md).

The roughly four-hour estimate is for planning. You may take longer, but there is no need to finish every requirement if the work takes substantially longer than expected. Incomplete submissions are welcome; explain what works, what remains unfinished and your next steps in both the video and `RESULTS.md`. Follow the submission deadline in your invitation.

## Start here

1. Read [the assignment](assignment.md), especially the API, deliverables and evaluation sections.
2. Install Git, Docker with Compose v2, Python 3.10+ for the coding-tool launcher, and your chosen language tools. GNU Make is convenient; equivalent Docker commands are below. On Windows, Docker Desktop with WSL2 is an option. Contact the invitation sender if you cannot use Docker.
3. Your funded API key, gateway and application model are already filled in `starter-kit/.env`. Run `python configure_access.py application-check` from the packet root to verify access before starting your application. Follow [API_ACCESS.md](API_ACCESS.md) to connect your application and chosen coding tool. Ask your recruiter if `.env` is missing; you do not need to buy API credit or a coding subscription.
4. Work inside `starter-kit/`. It contains data, an API contract, lookup tables and a Qdrant Compose service. **There is no supplied backend or frontend.** Implement them, add their Docker services, and replace the deliberately failing `make test` target with your own test command.
5. Build a thin end-to-end path first, then add retrieval, evidence handling and validation. Record your measurements and remaining limitations in `RESULTS.md`.

```text
assignment.md          Detailed requirements and evaluation
API_ACCESS.md          Application and coding-tool authentication
ACCESS.json            Supplied gateway, models, allowance and expiry
configure_access.py    Local coding-tool launcher and configuration check
AI_USAGE.md            Short reflection to complete
RESULTS.md             Measurements and limitations to complete
starter-kit/           Build your application here
  .env                 Supplied API key, gateway and application model
  api-contract/        OpenAPI contract
  data/knowledge-base/ Historical claims for retrieval
  data/test-images/    40 synthetic development photos
  data/test-documents/ Three synthetic evidence PDFs
  data/ground-truth/   Public development answer key; never use at runtime
  tools/               Cost and coverage lookup tables
auto-grader/           Public acceptance checks
PACKET.json            Packet identifier; include with your submission
```

## Use your coding assistant

`configure_access.py` launches Claude Code, Codex or OpenCode with the interview's funded model access. It reads the gateway and approved model for your chosen tool from `ACCESS.json`, loads the key from `starter-kit/.env`, and applies those settings when starting the tool. Model requests then go through Portkey and use the shared interview allowance.

Install your chosen tool's command-line application and Python 3.10+ first. From the extracted packet root (the folder containing `configure_access.py` and `ACCESS.json`), run **one** of:

```sh
python configure_access.py claude
python configure_access.py codex
python configure_access.py opencode
```

Use the launcher each time you start a coding session for this exercise. To preview non-secret settings without starting a session, add `--check`, for example `python configure_access.py codex --check`; this does not contact Portkey or verify live access. See [API_ACCESS.md](API_ACCESS.md#coding-assistant) for the initial request check and troubleshooting, and [pass the same settings to your backend](API_ACCESS.md#application).

## Run and test

Keep `starter-kit/` and `auto-grader/` side by side. Setup starts working after you add your application services. From `starter-kit/`:

```sh
make setup
make test
make grade
```

Without Make, first run `python configure_access.py application-check` from the packet root, then start services from `starter-kit/` with `docker compose up --build -d --wait --wait-timeout 120`, run your documented language-specific test command, and run public checks with:

```sh
docker compose -f ../auto-grader/docker-compose.grade.yml run --rm --build grader
```

The API should be available at `http://localhost:8000/api/v1/health` and the UI at `http://localhost:3000`. Evaluation results appear in `auto-grader/results/grade_report.json`. The evaluator makes repeated model-backed requests; use the provided access budget and contact us if it is exhausted. The Compose setup downloads public images; local embedding models may be downloaded during initial setup. No additional paid service is required.

Use `make grade-smoke` from `starter-kit/` while iterating: it exercises three varied positive cases and does not produce a full grade. `make grade` always runs all 35 accuracy cases, sequentially, reusing their results across checks. At 10–28 seconds per triage, accuracy alone takes about 6–16 minutes. Progress streams to the console; per-case timings and failures are saved incrementally in `auto-grader/results/accuracy_full.json` (or `accuracy_smoke.json`). The full accuracy timeout allows 35 × 120 seconds plus startup; failed requests still count.

## Submit

Follow [the assignment's submission instructions](assignment.md#53-submission) to upload your solution ZIP and recorded video through the link in your invitation. **Record the video in English.** The assignment also describes the presentation. You may replace this README with your own run instructions and explanation of the solution.

For setup, access or submission help, contact the invitation sender with your packet ID and a redacted error message. Keep credentials out of your code, recording and submission. Use only fictional fixtures and keep your work private.
