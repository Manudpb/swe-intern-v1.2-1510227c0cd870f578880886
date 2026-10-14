"""The adjuster page, on port 3000.

Server-rendered, so the browser only ever talks to its own origin and there is no CORS
configuration to get wrong (research D14). The form posts here; this app forwards the
multipart body to the API over the Compose network and renders the result. The trace panel
fetches from this app's own proxy path.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

log = logging.getLogger(__name__)

HERE = Path(__file__).parent
API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")
POLICY_TYPES = [
    "basic_homeowner",
    "standard_homeowner",
    "premium_homeowner",
    "renters",
    "landlord",
]
SUBMIT_TIMEOUT_S = 150.0

app = FastAPI(title="Claim Triage UI", version="1.0.0")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=str(HERE / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Any:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"policy_types": POLICY_TYPES, "result": None, "error": None},
    )


@app.post("/submit", response_class=HTMLResponse)
async def submit(request: Request) -> Any:
    form = await request.form()
    description = str(form.get("description") or "").strip()
    uploads = [f for f in form.getlist("images") if getattr(f, "filename", "")]
    document = form.get("document")
    has_document = bool(getattr(document, "filename", ""))

    if not uploads and not description:
        return _render(
            request,
            error={
                "title": "Nothing to assess",
                "message": "Attach at least one damage photograph or describe the incident.",
            },
        )

    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for upload in uploads:
        files.append(
            ("images", (upload.filename, await upload.read(), upload.content_type or "image/jpeg"))
        )
    if has_document:
        files.append(
            ("document", (document.filename, await document.read(), "application/pdf"))
        )
    data = {"policy_type": str(form.get("policy_type") or "standard_homeowner")}
    if description:
        data["description"] = description

    try:
        async with httpx.AsyncClient(timeout=SUBMIT_TIMEOUT_S) as client:
            response = await client.post(
                f"{API_BASE_URL}/api/v1/claims/triage", data=data, files=files or None
            )
    except httpx.HTTPError as exc:
        log.warning("Could not reach the API: %s", type(exc).__name__)
        return _render(
            request,
            error={
                "title": "The triage service is unreachable",
                "message": "The API did not respond. Check that the api container is running.",
            },
        )

    return _render_api_response(request, response)


@app.get("/api/v1/agent/trace/{claim_id}")
async def trace_proxy(claim_id: str) -> Any:
    """Same-origin proxy so the trace panel can fetch() without CORS."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{API_BASE_URL}/api/v1/agent/trace/{claim_id}")
    except httpx.HTTPError:
        return JSONResponse(status_code=503, content={"error": "The API is unreachable"})
    return JSONResponse(status_code=response.status_code, content=_json(response))


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """The UI's own liveness, distinct from the API's readiness contract."""
    return {"status": "ok"}


def _render_api_response(request: Request, response: httpx.Response) -> Any:
    payload = _json(response)
    if response.status_code == 200:
        return _render(request, result=payload)
    if response.status_code == 400:
        return _render(
            request,
            error={
                "title": "Submission rejected at intake",
                "message": payload.get("message", "The submission could not be triaged."),
                "intake_validation": payload.get("intake_validation"),
            },
        )
    if response.status_code == 422:
        return _render(
            request,
            error={
                "title": "Report withheld by the safety review",
                "message": payload.get("message", "The report text could not be made safe."),
                "safety_checks": payload.get("safety_checks"),
            },
        )
    return _render(
        request,
        error={
            "title": "The assessment could not be completed",
            "message": payload.get("message", f"The API returned HTTP {response.status_code}."),
        },
    )


def _render(request: Request, *, result: dict | None = None, error: dict | None = None) -> Any:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"policy_types": POLICY_TYPES, "result": result, "error": error},
    )


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}
    except ValueError:
        return {"message": "The API returned a response that was not JSON."}
