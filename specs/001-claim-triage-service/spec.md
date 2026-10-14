# Feature Specification: Home-Damage Claim Triage Service

**Feature Branch**: `001-claim-triage-service`

**Created**: 2026-10-14

**Status**: Draft

**Input**: User description: "A home-damage claim triage service for insurance adjusters. An adjuster submits damage photos, a description and an optional PDF (inspection report or contractor quote) for a policy type. The system rejects unsuitable submissions (not property damage, unusable image, personal data, offensive content) with a clear reason; otherwise it returns a triage report: damage type, severity, affected areas, repair-cost range, urgency, recommendation and similar past claims. Cost must come from the company cost table, not from the AI or a contractor quote. Every report has an inspectable step-by-step trace of how it was produced. Report text never promises coverage, gives legal advice, states payout amounts, assigns blame or uses emotional language. Adjusters use it through a simple web page. Each story must have acceptance scenarios that can be verified automatically, including failure scenarios."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Triage a submission into a decision-ready report (Priority: P1)

An adjuster receives a new property-damage claim with a photo of the damage and the claimant's
written account. They submit both and receive, in one step, a structured report that classifies the
damage, rates its severity, lists the affected areas, gives a repair-cost range, sets an urgency
level, and recommends next steps. The report carries a stable identifier so the adjuster can come
back to it later without resubmitting.

**Why this priority**: This is the service. Every other story improves, constrains or explains this
one; none of them delivers value without it. A working version of only this story already replaces
the manual first pass on a claim.

**Independent Test**: Submit one damage photo plus a description and assert the returned report
carries every required field with a value from the permitted set, then fetch the same report by its
identifier and assert it is unchanged. Needs no trace, no web page and no retrieval corpus.

**Acceptance Scenarios**:

1. **Given** a clear photo of a flooded kitchen and the description "pipe burst under the sink
   overnight", **When** the adjuster submits it, **Then** the report classifies damage type as
   `water_damage`, assigns one of `minor | moderate | severe | catastrophic`, lists at least one
   affected area, states a cost range where `min <= max` and currency is `USD`, assigns one of
   `low | medium | high | critical` for urgency, and includes a non-empty recommendation.
2. **Given** a submission that produced report `R`, **When** the adjuster fetches `R` by its
   identifier, **Then** the response is the same report content that was returned at submission
   time.
3. **Given** an identifier that was never issued, **When** the adjuster fetches it, **Then** the
   service answers "not found" rather than inventing a report or returning an empty one.
4. **Given** a submission with neither an image nor a non-blank description, **When** it is
   submitted, **Then** the service refuses it as an invalid request and produces no report.
5. **Given** the underlying model service is unreachable, **When** a submission is made, **Then**
   the service returns an explicit failure rather than a report containing guessed or default
   values.

---

### User Story 2 - Reject unsuitable submissions with a clear reason (Priority: P1)

An adjuster submits something that cannot be triaged — a photo of a parked car, a blurry
unreadable shot, a snapshot of a credit card, or abusive text. Instead of producing a confident but
meaningless report, the service refuses the submission, reports which of the four intake checks
failed, and states in plain language why it stopped. The adjuster can fix the submission and retry.

**Why this priority**: A triage report on a non-damage photo is worse than no report, because an
adjuster may act on it. Refusal is as much the product as assessment, and it is the cheapest story
to verify.

**Independent Test**: Submit each of the four unsuitable categories and assert the submission is
rejected with the offending check flagged false and a human-readable reason; submit a valid case and
assert it is not rejected. Needs no retrieval, no trace and no web page.

**Acceptance Scenarios**:

1. **Given** a photo of an undamaged vehicle in a driveway, **When** it is submitted, **Then** the
   submission is rejected, `is_property_damage` is false, and the reason names the absence of
   property damage.
2. **Given** a photo too blurry to assess, **When** it is submitted, **Then** the submission is
   rejected and `is_valid_image` is false.
3. **Given** an image of a payment card — including a synthetic test card — **When** it is
   submitted, **Then** the submission is rejected and `no_pii_detected` is false.
4. **Given** a description containing abusive or irrelevant content, **When** it is submitted,
   **Then** the submission is rejected and `no_offensive_content` is false.
5. **Given** any rejected submission, **When** the response is inspected, **Then** it contains no
   triage assessment: the service stopped before classifying damage, pricing repairs or searching
   past claims.
6. **Given** a text-only submission with a valid damage description, **When** it is submitted,
   **Then** it is **not** rejected for a missing image: `is_valid_image` is null, the remaining
   three checks are evaluated against the text, and triage proceeds.
7. **Given** a valid damage photo with a valid description, **When** it is submitted, **Then** all
   four intake checks pass and no rejection occurs.

---

### User Story 3 - Ground the report in similar past claims (Priority: P2)

The adjuster wants to know how the company handled claims like this one before. Each report lists
similar historical claims with a similarity score and a short note on how each was resolved, drawn
from the company's archive of past claims — so the adjuster can sanity-check the assessment against
precedent rather than trusting it blind.

**Why this priority**: Precedent is what makes the report trustworthy to a human reviewer, and it is
what distinguishes this from a one-shot opinion. It is not needed for a first end-to-end path, so it
follows the P1 stories.

**Independent Test**: With the historical archive loaded, search for a known incident type and
assert the returned claims are real archive entries whose damage type matches the query; assert
scores are ordered and in range. Verifiable against the archive alone, without any report.

**Acceptance Scenarios**:

1. **Given** the historical archive is loaded, **When** the service reports its readiness, **Then**
   it indicates the archive is populated and searchable.
2. **Given** a water-damage submission, **When** the report is produced, **Then**
   `similar_past_claims` is non-empty, every `claim_id` is an identifier that exists in the
   archive, and every `similarity_score` is between 0 and 1 inclusive.
3. **Given** a search for "burst pipe flooded kitchen floor", **When** results are returned,
   **Then** the highest-scoring result is a water-damage claim and results are ordered by
   descending score.
4. **Given** a submission describing an incident unlike anything in the archive, **When** the
   report is produced, **Then** `similar_past_claims` is an empty list or contains only low-scoring
   entries — the service does not fabricate a claim identifier that is not in the archive.
5. **Given** the archive is unavailable, **When** a submission is made, **Then** the service either
   reports itself not ready or returns a report with an empty precedent list, and never invents
   precedent.
6. **Given** a submission whose photo filename matches a development answer-key filename, **When**
   the report is produced, **Then** no report value is drawn from that answer key: the service
   searches only the historical archive, and renaming the photo does not change the report.

---

### User Story 4 - Anchor money and coverage to the company tables (Priority: P2)

Repair-cost ranges and coverage facts come from the company's published cost and coverage tables.
The assessment supplies the inputs — damage type, severity, how many distinct areas are affected,
and the policy type — and the tables supply the numbers. A contractor's quote in an attached PDF is
read as evidence but never substituted for the table figure, and the model is never the source of a
dollar amount.

**Why this priority**: Money is the part of the report that cannot be wrong in a way a reviewer
tolerates. It is also exactly checkable, which makes it the highest-confidence requirement in the
spec. It depends on US1 producing an assessment first.

**Independent Test**: For a fixed damage type, severity and area count, assert the report's cost
range equals the table computation to the cent; attach a PDF quoting a conflicting figure and assert
the range does not move. Fully verifiable with a stubbed assessment.

**Acceptance Scenarios**:

1. **Given** an assessment of `water_damage` / `moderate` with two distinct affected areas, **When**
   the cost range is computed, **Then** it equals the table's per-area range multiplied by two
   exactly, with no model-originated adjustment.
2. **Given** an assessment with an empty affected-areas list, **When** the cost range is computed,
   **Then** the area multiplier is treated as 1 rather than 0, so the range is never zero-width at
   zero.
3. **Given** a submission whose attached PDF is a contractor quote for an amount outside the table
   range, **When** the report is produced, **Then** the reported cost range is still the table
   figure, and the quote is at most mentioned as evidence in the narrative.
4. **Given** affected areas reported as "kitchen", "kitchen floor" and "interior", **When** areas
   are counted for pricing, **Then** they count as one distinct area, not three — a room is not
   counted again for its floor or wall, and a specific component is not counted again under a
   generic label.
5. **Given** a `basic_homeowner` policy and a water-damage incident, **When** coverage is consulted,
   **Then** the table's answer (not covered, with that policy's deductible, maximum and notes) is
   what informs the recommendation, and the recommendation does not contradict it.
6. **Given** a policy type absent from the coverage table, **When** coverage is consulted, **Then**
   the service reports the lookup as unavailable rather than guessing a deductible or payout.
7. **Given** a submission that states no policy type, **When** coverage is consulted, **Then** the
   lookup uses `standard_homeowner` and the trace records that policy type.

---

### User Story 5 - Inspect how a report was produced (Priority: P2)

For any report, the adjuster can pull up a step-by-step record of how the service got there: what it
set out to find at each step, which tool it used with which inputs, and what that tool actually
returned. The record lets a reviewer confirm the report follows from real lookups rather than a
single guess, without exposing the model's private deliberation.

**Why this priority**: Without this, nobody — adjuster, auditor or reviewer — can tell a grounded
report from a plausible-sounding one. It is a prerequisite for anyone trusting the service in
production, but not for the first working path.

**Independent Test**: Produce one report, fetch its trace, and assert the step sequence is
well-formed, every tool invocation is paired with its observation, and the observations agree with
the report's numbers. Verifiable without the web page or the live model.

**Acceptance Scenarios**:

1. **Given** a completed report, **When** its trace is requested by the report identifier, **Then**
   the trace is returned with that identifier, an ordered list of steps, and a total duration.
2. **Given** a trace, **When** its steps are examined, **Then** step numbers increase without gaps,
   each step is one of reason / act / observe, each timestamp is a valid instant, and each act step
   is followed by the observe step for that action.
3. **Given** a trace, **When** the act steps are examined, **Then** at least two distinct tools
   appear, each act step names its tool and carries non-empty inputs, and each observe step carries
   the actual value the tool returned rather than a restatement of intent.
4. **Given** a trace whose steps include a cost lookup, **When** that observation is compared with
   the report, **Then** the cost range in the observation matches the cost range in the report.
5. **Given** a trace, **When** its content is read, **Then** no step exposes private model
   reasoning: step content is a concise statement of purpose, a tool call, or an observation.
6. **Given** an identifier with no associated run, **When** its trace is requested, **Then** the
   service answers "not found".
7. **Given** a submission rejected at intake, **When** the report list is inspected, **Then** no
   trace claiming tool activity exists for it.
8. **Given** any completed run, **When** its trace, its report and the service's log output are
   searched for the configured model credential, **Then** the credential appears in none of them.

---

### User Story 6 - Keep report language within professional limits (Priority: P2)

Before a report reaches the adjuster, its text is reviewed against five limits: it must not promise
or guarantee coverage, must not give legal or liability advice, must not state a settlement or
payout figure, must not assign fault, and must not use emotional language. Text that crosses a line
is corrected before delivery, and the report records that all five limits hold.

**Why this priority**: A sentence promising coverage or assigning blame is a legal exposure for the
insurer regardless of how accurate the rest of the assessment is. It gates delivery, so it must
exist before the service is shown to anyone outside the team.

**Independent Test**: Feed the reviewer handcrafted report text that violates each limit in turn and
assert the violation is detected and corrected; feed compliant text and assert it passes untouched.
Fully verifiable with no model call.

**Acceptance Scenarios**:

1. **Given** a report whose recommendation reads "this damage is fully covered and will be paid",
   **When** the text is reviewed, **Then** the coverage-promise limit is detected as violated.
2. **Given** a recommendation stating "the claimant should expect a settlement of $12,000", **When**
   the text is reviewed, **Then** the settlement-amount limit is detected as violated — while a
   repair-cost range from the company table remains permitted.
3. **Given** a recommendation stating "the neighbour is liable for this damage", **When** the text
   is reviewed, **Then** the liability and fault limits are detected as violated.
4. **Given** a recommendation containing "we are devastated by this tragic loss", **When** the text
   is reviewed, **Then** the emotional-language limit is detected as violated.
5. **Given** report text that violates a limit, **When** the report is delivered, **Then** the
   delivered text no longer contains the violating statement, and the report's five recorded limit
   flags are all true.
6. **Given** report text that cannot be brought within the limits, **When** delivery is attempted,
   **Then** the service refuses to deliver the report and reports which limits failed, rather than
   delivering unsafe text.
7. **Given** a neutral, professional recommendation, **When** it is reviewed, **Then** all five
   flags are true and the text is returned unmodified.

---

### User Story 7 - Evidence beyond a single photo (Priority: P3)

Real submissions arrive in different shapes: several photos of the same incident from different
angles, a photo with no description, a description with no photo, or a photo plus a PDF inspection
report. The service handles each shape, uses the PDF's findings to refine the scope of damage, notes
reduced confidence when there is no visual evidence, and explains conflicts between sources instead
of silently picking one.

**Why this priority**: These combinations widen real-world coverage and are explicitly required, but
each one degrades gracefully to the single-photo path, so they can follow the core stories.

**Independent Test**: Submit each of the four input combinations and assert a valid report comes back
for each; submit three views of one room and assert the affected-area count does not triple.
Verifiable with fixtures and no web page.

**Acceptance Scenarios**:

1. **Given** an image with no description, **When** it is submitted, **Then** a complete report is
   returned.
2. **Given** a description with no image, **When** it is submitted, **Then** a complete report is
   returned, `is_valid_image` is null, and the narrative states that visual evidence was
   unavailable and confidence is correspondingly limited.
3. **Given** an image, a description and a PDF inspection report, **When** it is submitted, **Then**
   a complete report is returned and the narrative reflects at least one finding from the PDF.
4. **Given** three photos of the same damaged kitchen, **When** they are submitted together,
   **Then** the report describes one incident and the affected-area count reflects the distinct
   rooms shown, not the number of photos.
5. **Given** a PDF whose inspection findings name an affected area the photo does not show, **When**
   the report is produced, **Then** the scope is widened to include it.
6. **Given** a PDF that contradicts the photo evidence on severity, **When** the report is produced,
   **Then** the narrative states the conflict rather than silently resolving it.
7. **Given** an attachment that is not a readable PDF, **When** it is submitted, **Then** the
   service either returns a report based on the remaining evidence and notes the unreadable
   attachment, or rejects the submission with that reason — it does not fail silently.

---

### User Story 8 - Use the service from a web page (Priority: P3)

An adjuster opens a single page in a browser, attaches one or more photos, types the incident
description, optionally attaches a PDF, picks the policy type, and submits. The page then shows the
structured report and the step-by-step record of how it was produced, on the same screen.

**Why this priority**: The page is how a non-technical adjuster reaches the service and is required
for demonstration, but it adds no assessment capability. Functional beats polished.

**Independent Test**: Load the page and assert it offers controls for photos, description, PDF and
policy type plus a submit action; submit a fixture and assert the report fields and the trace steps
both appear. Verifiable by driving the page alone.

**Acceptance Scenarios**:

1. **Given** the service is running, **When** the adjuster opens the application's web address,
   **Then** the page loads and presents a photo upload, a description field, an optional PDF upload,
   a policy-type selection and a submit action.
2. **Given** the page is open, **When** the adjuster submits a photo and a description, **Then** the
   page displays the damage type, severity, affected areas, cost range, urgency, recommendation and
   similar past claims from the returned report.
3. **Given** a report is displayed, **When** the adjuster looks for the reasoning record, **Then**
   the page shows the step-by-step tool activity for that report on the same screen.
4. **Given** a submission the service rejects at intake, **When** the page receives the rejection,
   **Then** it displays the stated reason and the failed checks instead of an empty report or a
   silent failure.
5. **Given** the adjuster submits with neither a photo nor a description, **When** they press
   submit, **Then** the page reports the missing input and does not leave a request in progress
   indefinitely.

---

### Edge Cases

- **Zero affected areas identified**: pricing treats the area multiplier as 1 (US4 scenario 2), so a
  report never carries a $0–$0 range.
- **Overlapping area names**: "kitchen", "kitchen floor" and "interior" collapse to one area
  (US4 scenario 4). The same rule applies across multiple photos of one room.
- **Ambiguous damage type**: when evidence supports no listed category, the type is `other` rather
  than a forced guess, and the narrative says why.
- **Damage type not covered by the stated policy**: the report is still produced in full; coverage
  informs the recommendation and is never expressed as a promise or a refusal of the claim.
- **Model returns malformed or out-of-enum output**: the service rejects the malformed result and
  retries or fails explicitly; it never emits a value outside the permitted set.
- **Model service unavailable, rate-limited or timing out**: the submission fails with an explicit
  error (US1 scenario 5). No partially-guessed report is returned and no retry loop is run.
- **Historical archive empty or unreachable**: readiness reports the archive as unavailable; no
  precedent is fabricated (US3 scenario 5).
- **Oversized or non-image upload**: refused as an invalid request before any paid assessment work
  begins.
- **Repeated identical submissions**: each produces its own report with its own identifier; reports
  are never overwritten.
- **Safety correction loop**: correction is attempted a bounded number of times; if the text still
  violates a limit, delivery is refused (US6 scenario 6) rather than retried indefinitely.
- **Trace requested while a run is still in progress**: the service answers "not found" until the
  run completes, rather than returning a half-written trace as final.

## Requirements *(mandatory)*

### Functional Requirements

**Submission and intake**

- **FR-001**: The service MUST accept a submission consisting of one or more damage photos, a text
  description, an optional PDF document and an optional policy type, in any combination that
  includes at least one photo or a non-blank description.
- **FR-002**: The service MUST reject a submission that includes neither a photo nor a non-blank
  description, without performing any assessment work.
- **FR-003**: The service MUST default the policy type to `standard_homeowner` when the submitter
  does not state one.
- **FR-004**: The service MUST evaluate every submission against four intake checks before any
  assessment: shows property damage, image usable for assessment, free of visible personal
  information, free of offensive or irrelevant content.
- **FR-005**: The service MUST reject a submission when any intake check fails, returning the four
  check results and a plain-language reason, and MUST NOT produce a triage assessment for it.
- **FR-006**: For a text-only submission, the service MUST record the image-usability check as "not
  applicable" (null), evaluate the other three checks against the text, and continue to assessment
  when they pass.
- **FR-007**: The service MUST treat an image of a payment card as containing personal information,
  including synthetic or test card images.

**Assessment**

- **FR-008**: The service MUST produce a report containing damage type, severity, affected areas,
  a damage narrative, a repair-cost range, an urgency level, a recommendation and a list of similar
  past claims.
- **FR-009**: Damage type MUST be one of `water_damage`, `fire_damage`, `storm_damage`, `break_in`,
  `vandalism`, `other`; severity one of `minor`, `moderate`, `severe`, `catastrophic`; urgency one of
  `low`, `medium`, `high`, `critical`. The service MUST NOT emit any other value.
- **FR-010**: The service MUST reach its assessment through an iterative loop in which it states
  what it needs, invokes a tool, observes the real result, and continues until the report is
  complete. A single-shot assessment with no tool use MUST NOT satisfy this requirement.
- **FR-011**: The service MUST provide at least three assessment tools: search of past claims by
  natural-language description, repair-cost estimation from damage type / severity / affected areas,
  and coverage lookup from policy type and incident category.
- **FR-012**: The service MUST count distinct affected rooms or exterior components once, collapsing
  a room with its own floor or wall, a specific component with a generic label covering it, and
  repeated views of the same area.
- **FR-013**: The service MUST assign each report a unique identifier at submission and MUST return
  the identical report content on later retrieval by that identifier.
- **FR-014**: The service MUST report "not found" for retrieval of an identifier it never issued.

**Money and coverage**

- **FR-015**: The repair-cost range MUST be computed from the company cost table using the assessed
  damage type, severity and distinct affected-area count. The service MUST NOT let the model, the
  claimant's description or an attached contractor quote set, adjust or override the figure.
- **FR-016**: The service MUST treat a distinct-area count of zero as one when computing cost.
- **FR-017**: Coverage facts (covered or not, deductible, maximum payout, notes) MUST come from the
  company coverage table and MUST NOT be invented when the policy type or incident category is
  absent from it.
- **FR-018**: The reported cost range MUST carry an explicit currency, and `min` MUST NOT exceed
  `max`.

**Precedent**

- **FR-019**: The service MUST build a searchable index of the company's historical claim archive
  and MUST return similar claims by semantic similarity to the submitted description.
- **FR-020**: Every similar claim in a report MUST reference an identifier that exists in the
  archive, carry a similarity score between 0 and 1, and carry a short resolution summary. The
  service MUST NOT fabricate claim identifiers.
- **FR-021**: The service MUST NOT use development answer keys as a retrieval source or derive any
  report value from correspondence between an input filename and an answer-key filename.

**Trace**

- **FR-022**: The service MUST record, for every report, an ordered trace of its steps and MUST
  expose it on request by the report identifier.
- **FR-023**: Each trace step MUST carry a sequence number, a step kind (reason, act or observe),
  content, and a timestamp. Act steps MUST additionally carry the tool name and the tool inputs;
  observe steps MUST carry the value the tool actually returned.
- **FR-024**: Each act step MUST be paired with the observe step for that action, and trace
  observations MUST agree with the corresponding values in the final report.
- **FR-025**: Trace content MUST be limited to concise action-purpose summaries, tool calls and
  observations. The service MUST NOT expose private model reasoning.
- **FR-026**: The trace MUST carry a total duration for the run.

**Safety of report text**

- **FR-027**: The service MUST review every report's text against five limits before delivery — no
  coverage promises, no legal or liability advice, no settlement or payout amounts, no assignment of
  fault, no emotional language — and MUST record the outcome of each.
- **FR-028**: When a limit is violated, the service MUST correct or regenerate the text before
  delivery, within a bounded number of attempts.
- **FR-029**: When the text cannot be brought within the limits, the service MUST refuse delivery
  and report which limits failed, rather than delivering violating text.
- **FR-030**: A delivered report MUST record all five limits as satisfied.

**Interface and operation**

- **FR-031**: The service MUST expose its behaviour over the interface published in the project's
  API contract (`starter-kit/api-contract/openapi.yaml`), and every response it emits MUST conform
  to that contract's schemas.
- **FR-032**: The service MUST provide a readiness signal reporting whether the claim archive and
  the model access are available.
- **FR-033**: The service MUST provide a web page through which an adjuster can attach photos, enter
  a description, attach an optional PDF, choose a policy type, submit, and view both the resulting
  report and its trace.
- **FR-034**: The web page MUST display a rejection's stated reason and failed checks when a
  submission is refused.
- **FR-035**: When model access fails, is rate-limited or times out, the service MUST return an
  explicit failure and MUST NOT return a report built from guessed or default values, and MUST NOT
  retry in an unbounded loop.
- **FR-036**: The service MUST NOT write credentials to any response, log line or trace.

### Key Entities

- **Submission**: What an adjuster sends — one or more damage photos, an optional description, an
  optional PDF document, and a policy type. Transient; it is the input to exactly one report.
- **Intake Verdict**: The four-way result of pre-assessment screening (property damage, image
  usability, personal-information absence, content appropriateness), where image usability may be
  "not applicable" for text-only submissions. Determines whether assessment happens at all.
- **Triage Report**: The delivered assessment — identifier, intake verdict, damage type, severity,
  distinct affected areas, damage narrative, repair-cost range, urgency, recommendation, similar past
  claims, and safety-limit outcomes. Retrievable by identifier.
- **Cost Range**: A minimum, a maximum and a currency, derived only from the company cost table.
- **Coverage Finding**: Whether a policy covers an incident category, with deductible, maximum payout
  and notes, read from the company coverage table. Informs the recommendation; not a promise to the
  claimant.
- **Historical Claim**: An archive record of a past claim — identifier, description, damage type,
  severity, affected areas, policy type, actual repair cost, resolution and adjuster notes. The only
  runtime source of precedent.
- **Similar Claim Reference**: A pointer from a report to a historical claim, with similarity score
  and resolution summary.
- **Trace**: The ordered record of one assessment run — report identifier, steps (kind, content,
  tool name, tool inputs, tool output, timestamp) and total duration.
- **Safety Verdict**: The five limit outcomes recorded on a delivered report.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An adjuster submits a photo and description and receives a complete report in a single
  interaction, typically within 30 seconds and never hanging without an answer beyond 120 seconds.
- **SC-002**: Across the 35 valid development cases, the service classifies damage type correctly in
  at least 50% of cases.
- **SC-003**: Across the same cases, severity scores at least 0.4 on average, counting an exact
  match as 1 and an adjacent level as 0.5.
- **SC-004**: Across the same cases, the repair-cost midpoint scores at least 0.3 on average,
  measured as one minus the absolute percentage error, floored at zero.
- **SC-005**: All five unsuitable development cases are rejected with the correct failing check
  identified, and no valid case is rejected.
- **SC-006**: 100% of delivered reports record all five safety limits as satisfied, and no delivered
  report text contains a coverage promise, legal advice, a settlement amount, an attribution of
  fault or emotional language.
- **SC-007**: 100% of delivered reports have a retrievable trace in which every tool invocation is
  paired with its observation and the cost figure observed matches the cost figure reported.
- **SC-008**: 100% of reported cost ranges equal the company cost table's computation for the
  assessed damage type, severity and distinct-area count.
- **SC-009**: 100% of similar-claim references in delivered reports resolve to identifiers that exist
  in the historical archive.
- **SC-010**: All four input combinations (photo only, photo with description, photo with description
  and PDF, description only) produce a complete report.
- **SC-011**: An engineer unfamiliar with the project brings the whole system up from a clean
  checkout with one documented command and reaches a working submission through the web page without
  manual steps beyond supplying the model credential.
- **SC-012**: The project's own test suite runs to completion offline, with no paid model calls and
  no external services, and covers at least one failure path for each error outcome the API contract
  declares.

## Assumptions

These are the informed defaults chosen where the description left room. Each is a decision that can
be revisited without reopening the spec.

- **Safety failures are corrected, not surfaced as failures.** A report whose text violates a limit
  is regenerated or sanitised and then delivered normally; refusal (US6 scenario 6, FR-029) is the
  last resort after a bounded number of attempts, not the first response. The alternative — refusing
  on first violation — would be simpler but would deny the adjuster a usable report over a fixable
  sentence.
- **Urgency is derived, not looked up.** No urgency table is supplied, so urgency follows from
  severity, damage type and ongoing-risk cues in the evidence (active water, structural or safety
  hazard). It is a judgement field, assessed qualitatively rather than scored against an answer key.
- **Coverage informs the recommendation; it is not a report field.** The coverage lookup is required
  and appears in the trace, but the report schema has no coverage field, so its influence shows up in
  the recommendation's wording — always as context, never as a promise or denial.
- **Reports persist for the service's lifetime, not beyond.** Reports and traces are retrievable for
  as long as the service runs. Durable storage across restarts is out of scope for this pilot; the
  archive index may persist in its own store.
- **No authentication.** The service runs as a single-tenant internal pilot on a local machine; there
  are no adjuster accounts, roles or audit identities. Adding them would not change any requirement
  above.
- **Multiple photos are always the same incident.** Repeated photo fields are additional views of
  one incident, never separate claims, and they never multiply the affected-area count.
- **PDF evidence outranks the photo on scope, not on price.** Same-incident inspection findings widen
  or narrow which areas are affected; a contractor quote never displaces the table-derived cost
  figure (FR-015).
- **"Clear reason" means human-readable prose.** A rejection carries both the four machine-readable
  check flags and a sentence an adjuster can act on; neither alone is sufficient.
- **Development fixtures are references, not appraisals.** The supplied photos, PDFs and answer keys
  are synthetic. Their labels set the accuracy targets in SC-002 through SC-004 but are not treated
  as professional ground truth, and reasonable scope differences are expected.
- **The API contract is a fixed input.** `starter-kit/api-contract/openapi.yaml` is given, not
  designed here; FR-031 binds the implementation to it rather than the reverse.

### Dependencies

- The company historical claim archive (`starter-kit/data/knowledge-base/`, 30 records) — the only
  runtime source of precedent.
- The company cost table (`starter-kit/tools/cost-estimator.json`) — the only source of repair-cost
  figures.
- The company coverage table (`starter-kit/tools/coverage-table.json`) — the only source of coverage
  facts.
- The published API contract (`starter-kit/api-contract/openapi.yaml`).
- Funded model access through the project's configured gateway, which is the service's only external
  runtime dependency.
- Development fixtures for verification: 40 synthetic photos (35 valid, 5 unsuitable) and 3 synthetic
  evidence PDFs.

### Out of Scope

- Claim settlement, payment or any write-back to a policy system of record.
- Fraud scoring, despite the archive carrying fraud indicators.
- Adjuster accounts, authentication, authorisation and multi-tenancy.
- Durable report storage surviving a restart.
- Claimant-facing views; the only user is an internal adjuster.
- Notifications, work queues, assignment and case management.
- Languages other than English, and currencies other than USD.
