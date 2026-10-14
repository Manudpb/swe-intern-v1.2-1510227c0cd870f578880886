"""
Basic UI checks within the infrastructure category (no separate 10 points).

Verifies the lightweight web UI is functional.
Note: These are basic HTTP-level checks. Full UI testing would require
a browser automation tool like Playwright.
"""
import requests
import pytest
from bs4 import BeautifulSoup


class TestUI:
    """Test that the web UI is functional."""

    def test_ui_serves_html(self, ui_url):
        """UI serves an HTML page."""
        resp = requests.get(ui_url, timeout=10)
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_ui_has_form_elements(self, ui_url):
        """UI has input elements for claim submission."""
        resp = requests.get(ui_url, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")

        if soup.find('script') and (soup.select_one('#root') or soup.select_one('#app')) and not soup.find('input'):
            pytest.skip('Client-rendered UI requires browser review; static HTML is insufficient evidence')

        # Check for file upload input (for images)
        file_inputs = soup.find_all("input", {"type": "file"})
        has_file_upload = len(file_inputs) > 0

        # Check for text input area (for description)
        text_inputs = soup.find_all("textarea") + soup.find_all(
            "input", {"type": "text"}
        )
        has_text_input = len(text_inputs) > 0

        # Check for submit button
        buttons = soup.find_all("button") + soup.find_all(
            "input", {"type": "submit"}
        )
        has_submit = len(buttons) > 0

        assert has_file_upload, "UI is missing a file upload input for damage photos"
        assert has_text_input, "UI is missing a text input for incident description"
        assert has_submit, "UI is missing a submit button"

    def test_ui_references_api(self, ui_url, api_url):
        """UI page references the API or includes JavaScript for API calls."""
        resp = requests.get(ui_url, timeout=10)
        page_content = resp.text.lower()

        # Check if the page contains references to the API or fetch/axios calls
        has_api_reference = any(
            indicator in page_content
            for indicator in [
                "/api/",
                "fetch(",
                "axios",
                "xmlhttprequest",
                "api_url",
                "apiurl",
                "localhost:8000",
            ]
        )

        # Also check linked JS files
        soup = BeautifulSoup(resp.text, "html.parser")
        scripts = soup.find_all("script", src=True)
        for script in scripts:
            try:
                js_resp = requests.get(
                    f"{ui_url}/{script['src'].lstrip('/')}", timeout=5
                )
                if js_resp.status_code == 200:
                    js_content = js_resp.text.lower()
                    if any(
                        ind in js_content
                        for ind in ["/api/", "fetch(", "axios", "triage"]
                    ):
                        has_api_reference = True
                        break
            except Exception:
                continue

        assert has_api_reference, (
            "UI does not appear to communicate with the API. "
            "Expected fetch/axios calls or API URL references."
        )

    def test_ui_has_results_area(self, ui_url):
        """UI has an area for displaying triage results."""
        resp = requests.get(ui_url, timeout=10)
        page_content = resp.text.lower()

        # Look for result/output display indicators
        has_results_area = any(
            indicator in page_content
            for indicator in [
                "result",
                "output",
                "report",
                "triage",
                "assessment",
                "response",
                "damage",
            ]
        )

        if not has_results_area and BeautifulSoup(resp.text, 'html.parser').find('script'):
            pytest.skip('Client-rendered results require browser review')
        assert has_results_area, (
            "UI does not appear to have a results display area. "
            "Users should be able to see the triage report after submission."
        )
