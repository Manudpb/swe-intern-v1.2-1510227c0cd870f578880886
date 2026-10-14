"""US8 - the adjuster page.

The UI app talks to the API over HTTP, so these tests stub that one boundary with a transport
that answers from the real API app. Everything below the transport is the real UI code:
templates, form handling, error rendering.
"""
from __future__ import annotations

import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from claim_triage.main import create_app
from claim_triage.ui import app as ui_module
from tests.fakes import FakeLLM
from tests.fakes.scripts import scenarios

pytestmark = pytest.mark.integration


@pytest.fixture
def ui_client(monkeypatch, make_deps):
    """A UI client whose outbound HTTP lands on a real in-process API app."""
    api_app = create_app(make_deps(llm=FakeLLM(scenarios.clean_triage())))
    api_transport = httpx.ASGITransport(app=api_app)
    original = httpx.AsyncClient

    class RoutedAsyncClient(original):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = api_transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ui_module.httpx, "AsyncClient", RoutedAsyncClient)
    return TestClient(ui_module.app)


def _soup(response) -> BeautifulSoup:
    return BeautifulSoup(response.text, "html.parser")


def test_the_page_loads_as_html(ui_client):
    response = ui_client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_the_form_has_every_control_an_adjuster_needs(ui_client):
    """US8 scenario 1."""
    soup = _soup(ui_client.get("/"))

    file_inputs = soup.find_all("input", {"type": "file"})
    assert file_inputs, "no file upload for damage photographs"
    assert any(inp.get("multiple") is not None for inp in file_inputs), "photos must allow views"
    assert soup.find("textarea"), "no text input for the incident description"
    assert soup.find_all("button") or soup.find_all("input", {"type": "submit"})

    select = soup.find("select", {"name": "policy_type"})
    assert select is not None
    options = [o.get("value") for o in select.find_all("option")]
    assert len(options) == 5
    assert select.find("option", {"selected": True}).get("value") == "standard_homeowner"


def test_the_page_references_the_api(ui_client):
    """The page itself carries the API prefix, and the linked script uses it.

    Checked both ways because the published UI check looks at the page and then follows
    linked <script src> files.
    """
    body = ui_client.get("/").text.lower()
    script = ui_client.get("/static/app.js").text.lower()

    assert "/api/" in body, "the page should name the API prefix without needing a submission"
    assert "fetch(" in script and "/agent/trace/" in script


def test_submitting_renders_every_report_field(ui_client, damage_photo):
    """US8 scenario 2."""
    response = ui_client.post(
        "/submit",
        data={"description": "Burst pipe in the kitchen", "policy_type": "standard_homeowner"},
        files=[("images", ("damage.jpg", damage_photo, "image/jpeg"))],
    )

    assert response.status_code == 200, response.text
    soup = _soup(response)
    assert soup.find(id="report") is not None
    assert "water damage" in soup.find(id="damage-type").text.strip().lower()
    assert soup.find(id="severity").text.strip()
    assert soup.find(id="urgency").text.strip()
    assert "USD" in soup.find(id="cost").text
    assert "kitchen" in soup.find(id="affected-areas").text
    assert soup.find(id="recommendation").text.strip()
    assert soup.find(id="damage-description").text.strip()
    assert soup.find(id="similar-claims") is not None


def test_the_trace_panel_and_its_fetch_path_are_present(ui_client, damage_photo):
    """US8 scenario 3."""
    response = ui_client.post(
        "/submit",
        data={"description": "Burst pipe in the kitchen"},
        files=[("images", ("damage.jpg", damage_photo, "image/jpeg"))],
    )

    soup = _soup(response)
    panel = soup.find(id="trace-panel")
    assert panel is not None
    assert panel.get("data-claim-id")
    script = ui_client.get("/static/app.js").text
    # The prefix comes from the form's data-api-base, so the script holds only the suffix.
    assert "/agent/trace/" in script
    assert "fetch(" in script
    soup_form = _soup(ui_client.get("/")).find(id="claim-form")
    assert soup_form["data-api-base"] == "/api/v1"


def test_the_trace_proxy_returns_the_trace(ui_client, damage_photo):
    submitted = ui_client.post(
        "/submit",
        data={"description": "Burst pipe in the kitchen"},
        files=[("images", ("damage.jpg", damage_photo, "image/jpeg"))],
    )
    claim_id = _soup(submitted).find(id="trace-panel")["data-claim-id"]

    response = ui_client.get(f"/api/v1/agent/trace/{claim_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["claim_id"] == claim_id
    assert payload["steps"]


def test_a_rejection_renders_the_reason_and_the_failed_check(monkeypatch, make_deps, damage_photo):
    """US8 scenario 4."""
    api_app = create_app(
        make_deps(llm=FakeLLM(scenarios.rejected_intake(is_property_damage=False)))
    )
    transport = httpx.ASGITransport(app=api_app)
    original = httpx.AsyncClient

    class Routed(original):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ui_module.httpx, "AsyncClient", Routed)
    client = TestClient(ui_module.app)

    response = client.post(
        "/submit",
        data={"description": "A photo of my car"},
        files=[("images", ("car.jpg", damage_photo, "image/jpeg"))],
    )

    assert response.status_code == 200
    soup = _soup(response)
    panel = soup.find(id="error-panel")
    assert panel is not None
    assert "cannot be triaged" in panel.text
    failed = [li.text.strip() for li in panel.select("li.fail")]
    assert any("is property damage" in text for text in failed)
    assert soup.find(id="report") is None


def test_a_safety_refusal_renders_the_failing_limits(monkeypatch, make_deps, damage_photo):
    api_app = create_app(make_deps(llm=FakeLLM(scenarios.safety_unsanitizable())))
    transport = httpx.ASGITransport(app=api_app)
    original = httpx.AsyncClient

    class Routed(original):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ui_module.httpx, "AsyncClient", Routed)
    client = TestClient(ui_module.app)

    response = client.post(
        "/submit",
        data={"description": "Burst pipe in the kitchen"},
        files=[("images", ("damage.jpg", damage_photo, "image/jpeg"))],
    )

    soup = _soup(response)
    panel = soup.find(id="error-panel")
    assert panel is not None
    assert "safety" in panel.text.lower()
    assert any("no coverage promises" in li.text for li in panel.select("li.fail"))


def test_an_unreachable_api_renders_an_explicit_banner(monkeypatch, damage_photo):
    """US8: a 503 or a dead API never renders as an empty report."""

    class Failing(httpx.AsyncClient):
        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("api is down")

    monkeypatch.setattr(ui_module.httpx, "AsyncClient", Failing)
    client = TestClient(ui_module.app)

    response = client.post(
        "/submit",
        data={"description": "Burst pipe"},
        files=[("images", ("damage.jpg", damage_photo, "image/jpeg"))],
    )

    soup = _soup(response)
    assert soup.find(id="error-panel") is not None
    assert "unreachable" in soup.find(id="error-panel").text.lower()
    assert soup.find(id="report") is None


def test_submitting_nothing_reports_the_missing_input(ui_client):
    """US8 scenario 5: no pending request left hanging."""
    response = ui_client.post("/submit", data={"description": "   "})

    assert response.status_code == 200
    panel = _soup(response).find(id="error-panel")
    assert panel is not None
    assert "at least one damage photograph" in panel.text.lower()


def test_the_script_restores_nothing_silently(ui_client):
    """The in-flight state is handled in the page, not left to the browser default."""
    script = ui_client.get("/static/app.js").text

    assert "disabled = true" in script.replace(" ", " ")
    assert "trace-steps" in script


def test_the_stylesheet_is_served(ui_client):
    response = ui_client.get("/static/app.css")

    assert response.status_code == 200
    assert "body" in response.text
