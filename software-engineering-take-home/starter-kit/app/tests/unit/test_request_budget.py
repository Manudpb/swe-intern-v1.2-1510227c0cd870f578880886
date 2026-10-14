"""SC-001 / FR-035 - the request budget is enforced, not assumed (finding G3).

Without this, "never hanging beyond 120 seconds" would rest on unverified code. The budget is
what guarantees the caller always gets an answer, even when a model call hangs.
"""
from __future__ import annotations

import time

import pytest

from claim_triage.llm.ports import LLMResponse
from tests.conftest import submit
from tests.fakes import FakeLLM, build_script

pytestmark = pytest.mark.unit


class SlowLLM:
    """Hangs past the budget on its first call."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.calls: list[dict] = []
        self.model = "claude-opus-5"

    def create_message(self, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        time.sleep(self.delay)
        return LLMResponse(stop_reason="end_turn", text_blocks=["too late"], tool_calls=[])


async def test_a_hanging_model_call_yields_503_within_the_budget(make_deps, damage_photo, settings):
    """Driven through the ASGI app directly, the way uvicorn serves it.

    `TestClient` wraps each request in a blocking portal that waits for outstanding worker
    threads on teardown, which would hide the early return. Production writes the response
    as soon as the route returns and lets the orphan finish in the background.
    """
    import httpx

    from claim_triage.main import create_app

    tight = settings.model_copy(update={"request_budget_s": 0.25})
    app = create_app(make_deps(settings=tight, llm=SlowLLM(delay=1.2)))

    started = time.monotonic()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/claims/triage",
            data={"description": "Burst pipe in the kitchen"},
            files=[("images", ("damage.jpg", damage_photo, "image/jpeg"))],
        )
    elapsed = time.monotonic() - started

    assert response.status_code == 503
    assert response.json()["error"] == "upstream_unavailable"
    assert "request budget" in response.json()["message"].lower()
    # Returned on the budget, not after the hung call finished.
    assert elapsed < 1.0, f"the budget did not cut the request short (took {elapsed:.2f}s)"


def test_no_partial_report_is_returned_when_the_budget_trips(make_client, damage_photo, settings):
    tight = settings.model_copy(update={"request_budget_s": 0.5})
    client, _ = make_client(settings=tight, llm=SlowLLM(delay=5.0))

    body = submit(client, images=[damage_photo], description="Burst pipe").json()

    assert "triage_assessment" not in body
    assert "claim_id" not in body


def test_a_fast_pipeline_is_unaffected_by_the_budget(make_client, damage_photo, settings):
    generous = settings.model_copy(update={"request_budget_s": 30.0})
    client, _ = make_client(settings=generous, llm=FakeLLM(build_script()))

    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert response.status_code == 200


def test_the_deadline_is_checked_between_stages(make_client, damage_photo, settings):
    """A per-stage check catches the common case without orphaning a worker thread."""
    from claim_triage.api.routes_claims import BudgetExceeded, _check_budget

    with pytest.raises(BudgetExceeded):
        _check_budget(time.monotonic() - 1.0)

    _check_budget(time.monotonic() + 10.0)  # must not raise
