"""Claim submission and retrieval.

The pipeline, in order: intake screen -> ReAct loop -> report assembly (where scope and money
are copied out of the trace) -> safety gate -> store -> 200.

Every failure mode has exactly one honest answer:
* a failed intake check -> 400 with the flags and prose, and no assessment (FR-005)
* unsanitizable text    -> 422 (FR-029)
* an unknown id         -> 404 (FR-014)
* model access or the request budget gone -> 503, never a guessed report (FR-035)
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from claim_triage.agents import intake, safety, triage
from claim_triage.api import errors
from claim_triage.api.schemas import PolicyType, TriageResponse
from claim_triage.deps import Deps
from claim_triage.domain.report import AssessmentUnavailable, assemble
from claim_triage.evidence import pdf
from claim_triage.evidence.images import ImageRejected, PreparedImage, prepare
from claim_triage.llm.ports import LLMUnavailable
from claim_triage.trace.recorder import TraceIntegrityError, TraceRecorder

log = logging.getLogger(__name__)
router = APIRouter()


class BudgetExceeded(RuntimeError):
    """The request ran past its budget. Surfaced as 503 so the caller never waits forever."""


#: Strong references to abandoned pipeline runs. A worker thread cannot be cancelled, so the
#: task is kept alive until it finishes rather than being garbage-collected mid-flight.
_abandoned: set[asyncio.Task] = set()


@dataclass
class Submission:
    images: list[PreparedImage]
    description: str
    document: pdf.DocumentText | None
    policy_type: str
    had_image: bool


@router.post("/claims/triage")
async def triage_claim(
    request: Request,
    image: UploadFile | None = File(default=None),
    images: list[UploadFile] = File(default_factory=list),
    description: str | None = Form(default=None),
    document: UploadFile | None = File(default=None),
    policy_type: str | None = Form(default=None),
) -> Any:
    deps: Deps = request.app.state.deps

    text = (description or "").strip()
    uploads = [upload for upload in [image, *images] if upload is not None and upload.filename]
    if not uploads and not text:
        return errors.bad_request(
            "Submit at least one damage photograph or a written description of the incident."
        )

    try:
        prepared = [
            prepare(await upload.read(), upload.filename or "", deps.settings.max_image_bytes)
            for upload in uploads
        ]
    except ImageRejected as exc:
        return errors.bad_request(str(exc))

    document_text = None
    if document is not None and document.filename:
        document_text = pdf.extract(await document.read(), deps.settings.pdf_text_limit)

    submission = Submission(
        images=prepared,
        description=text,
        document=document_text,
        policy_type=_policy(policy_type),
        had_image=bool(prepared),
    )

    task = asyncio.create_task(asyncio.to_thread(_run_pipeline, deps, submission))
    try:
        # asyncio.wait, not wait_for: a thread cannot be cancelled, and wait_for would block
        # until it finished anyway. This returns on time and leaves the orphan to finish in
        # the background, so the caller always gets an answer (SC-001).
        done, _pending = await asyncio.wait({task}, timeout=deps.settings.request_budget_s)
        if task not in done:
            _abandoned.add(task)
            task.add_done_callback(_swallow)
            log.warning(
                "Triage exceeded the %.0fs request budget; abandoning the attempt",
                deps.settings.request_budget_s,
            )
            return errors.upstream_unavailable(
                "The assessment did not complete within the request budget."
            )
        return task.result()
    except BudgetExceeded:
        log.warning("Triage exceeded the %.0fs request budget", deps.settings.request_budget_s)
        return errors.upstream_unavailable(
            "The assessment did not complete within the request budget."
        )
    except LLMUnavailable as exc:
        log.warning("Model access failed: %s", exc)
        return errors.upstream_unavailable(str(exc))
    except (AssessmentUnavailable, triage.TriageIncomplete, TraceIntegrityError) as exc:
        log.warning("Assessment could not be completed: %s", exc)
        return errors.upstream_unavailable(str(exc))


def _run_pipeline(deps: Deps, submission: Submission) -> JSONResponse:
    deadline = time.monotonic() + deps.settings.request_budget_s
    document_text = submission.document.text if submission.document and submission.document.usable else ""
    document_note = submission.document.note() if submission.document else ""

    # --- intake: before any tool runs, so a rejection costs one model call ---------
    verdict = intake.validate(
        deps,
        images=submission.images,
        description=submission.description,
        document_text=document_text,
    )
    if not verdict.accepted:
        return errors.intake_rejected(verdict.validation, verdict.rejection_message())
    _check_budget(deadline)

    # --- the ReAct loop -----------------------------------------------------------
    recorder = TraceRecorder(clock=deps.clock)
    recorder.start()
    outcome = triage.run(
        deps,
        recorder=recorder,
        images=submission.images,
        description=submission.description,
        document_text=document_text,
        document_note=document_note,
        policy_type=submission.policy_type,
    )
    _check_budget(deadline)

    # --- assembly: scope and money come from the trace (invariants I3, I4) --------
    assessment = assemble(
        submitted=outcome.submitted,
        recorder=recorder,
        knowledge_base=deps.knowledge_base,
        had_image=submission.had_image,
    )

    # --- the safety gate ----------------------------------------------------------
    cost = assessment.estimated_repair_cost
    outcome_safety = safety.gate(
        deps,
        damage_description=assessment.damage_description,
        recommendation=assessment.recommendation,
        cost_text=f"${cost.min:,.0f} ${cost.max:,.0f} {cost.min:.0f} {cost.max:.0f}",
    )
    if not outcome_safety.delivered:
        return errors.safety_blocked(outcome_safety.checks, outcome_safety.message)

    assessment = assessment.model_copy(
        update={
            "damage_description": outcome_safety.damage_description,
            "recommendation": outcome_safety.recommendation,
        }
    )

    claim_id = deps.new_id()
    report = TriageResponse(
        claim_id=claim_id,
        intake_validation=verdict.validation,
        triage_assessment=assessment,
        safety_checks=outcome_safety.checks,
    )
    body = report.model_dump(mode="json")
    deps.reports.put(claim_id, body)
    # Published only now that the run is complete: until this point the id reads as 404.
    deps.reports.put_trace(claim_id, recorder.publish(claim_id))
    log.info(
        "Triaged %s in %d rounds; safety stages: %s",
        claim_id,
        outcome.rounds,
        ",".join(outcome_safety.stages),
    )
    return JSONResponse(status_code=200, content=body)


@router.get("/claims/{claim_id}")
async def get_report(request: Request, claim_id: str) -> Any:
    deps: Deps = request.app.state.deps
    stored = deps.reports.get(claim_id)
    if stored is None:
        return errors.not_found("report", claim_id)
    return JSONResponse(status_code=200, content=stored)


def _policy(value: str | None) -> str:
    """Absent or unrecognised means the documented default (FR-003)."""
    try:
        return PolicyType(str(value)).value
    except ValueError:
        return PolicyType.standard_homeowner.value


def _check_budget(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise BudgetExceeded("Request budget exhausted")


def _swallow(task: asyncio.Task) -> None:
    """Retrieve an abandoned run's outcome and release it."""
    _abandoned.discard(task)
    if not task.cancelled():
        task.exception()
