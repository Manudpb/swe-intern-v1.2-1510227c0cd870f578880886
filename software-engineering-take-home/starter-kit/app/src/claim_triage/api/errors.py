"""Error response bodies.

400 / 404 / 422 are declared in the contract. 503 is the one documented addition
(research D8, plan.md Complexity Tracking): it is used ONLY for upstream model failure
and for not-ready readiness, never for anything a client did. Returning 400 would blame
the adjuster's submission; 422 would claim a safety failure that never ran.
"""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from claim_triage.api.schemas import IntakeValidation, SafetyChecks


def intake_rejected(validation: IntakeValidation, message: str) -> JSONResponse:
    """400: a failed intake check. Carries the flags AND prose an adjuster can act on."""
    return JSONResponse(
        status_code=400,
        content={
            "error": "intake_validation_failed",
            "intake_validation": validation.model_dump(),
            "message": message,
        },
    )


def not_found(what: str, claim_id: str) -> JSONResponse:
    """404: an identifier we never issued, or a run that has not completed."""
    return JSONResponse(
        status_code=404,
        content={"error": "not_found", "message": f"No {what} for claim id {claim_id}."},
    )


def safety_blocked(checks: SafetyChecks, message: str) -> JSONResponse:
    """422: the safety gate could not produce deliverable text."""
    return JSONResponse(
        status_code=422,
        content={
            "error": "safety_check_failed",
            "safety_checks": checks.model_dump(),
            "message": message,
        },
    )


def upstream_unavailable(message: str) -> JSONResponse:
    """503: model access failed, or the service is not ready. Never a guessed report."""
    return JSONResponse(
        status_code=503,
        content={"error": "upstream_unavailable", "message": message},
    )


def not_ready(services: dict[str, Any]) -> JSONResponse:
    """503 on /health. The contract pins the 200 body's `status` to "healthy", so a
    not-ready service cannot answer 200 truthfully."""
    return JSONResponse(
        status_code=503,
        content={"status": "unhealthy", "services": services},
    )


def bad_request(message: str) -> JSONResponse:
    """400 for a submission carrying neither an image nor a non-blank description (FR-002)."""
    return JSONResponse(
        status_code=400,
        content={
            "error": "invalid_request",
            "intake_validation": {
                "is_property_damage": False,
                "is_valid_image": None,
                "no_pii_detected": True,
                "no_offensive_content": True,
            },
            "message": message,
        },
    )
