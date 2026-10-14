"""Readiness.

The contract pins the 200 body's `status` to the single value "healthy", so a not-ready
service cannot answer 200 truthfully. It answers 503 with the same shape instead — the one
documented addition (research D8).

`vector_db` reports `connected` only when the collection holds at least 80% of the corpus,
which is the same bar the public retrieval check applies. Reporting "connected" for an empty
collection would be a readiness signal that means nothing.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from claim_triage.api import errors
from claim_triage.deps import Deps

router = APIRouter()

POPULATION_THRESHOLD = 0.8


@router.get("/health")
async def health(request: Request) -> Any:
    deps: Deps = request.app.state.deps
    expected = len(deps.knowledge_base)
    try:
        stored = deps.vectors.count(deps.settings.collection_name)
    except Exception:  # noqa: BLE001 - an unreachable store is "disconnected", not a crash
        stored = 0

    vector_ready = expected > 0 and stored >= expected * POPULATION_THRESHOLD
    services = {
        "vector_db": "connected" if vector_ready else "disconnected",
        "llm": "configured" if deps.settings.llm_configured else "not_configured",
    }
    if not vector_ready:
        return errors.not_ready(services)
    return JSONResponse(status_code=200, content={"status": "healthy", "services": services})
