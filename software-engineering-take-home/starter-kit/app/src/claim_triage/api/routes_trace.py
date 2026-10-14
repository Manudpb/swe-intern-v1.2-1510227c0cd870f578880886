"""The ReAct execution trace.

A trace is published only once its run completes, so an id for an in-progress or failed run
reads as 404 rather than returning a half-written trace as final (spec.md edge cases).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from claim_triage.api import errors
from claim_triage.deps import Deps

router = APIRouter()


@router.get("/agent/trace/{claim_id}")
async def get_trace(request: Request, claim_id: str) -> Any:
    deps: Deps = request.app.state.deps
    stored = deps.reports.get_trace(claim_id)
    if stored is None:
        return errors.not_found("trace", claim_id)
    return JSONResponse(status_code=200, content=stored)
