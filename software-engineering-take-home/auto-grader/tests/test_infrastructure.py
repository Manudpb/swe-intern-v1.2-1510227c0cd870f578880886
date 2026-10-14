"""HTTP readiness and route checks; UI/modality checks share the 10-point category."""
import time
import requests

class TestInfrastructure:
    def test_health_endpoint_responds(self, api_url):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                response = requests.get(f'{api_url}/api/v1/health', timeout=3)
                if response.status_code == 200 and response.json().get('status') == 'healthy': return
            except (requests.RequestException, ValueError):
                pass
            time.sleep(1)
        assert False, 'API did not become healthy within readiness budget'

    def test_health_reports_vector_db(self, api_url):
        response = requests.get(f'{api_url}/api/v1/health', timeout=10)
        assert response.status_code == 200
        assert response.json()['services']['vector_db'] == 'connected'

    def test_triage_rejects_empty_request(self, api_url):
        response = requests.post(f'{api_url}/api/v1/claims/triage', timeout=10)
        assert response.status_code in (400, 422)

    def test_report_and_trace_can_be_retrieved(self, api_url, sample_triage):
        claim_id = sample_triage['claim_id']
        for route in ('claims', 'agent/trace'):
            response = requests.get(f'{api_url}/api/v1/{route}/{claim_id}', timeout=10)
            assert response.status_code == 200, f'Missing implemented route: {route}'
            assert response.json().get('claim_id') == claim_id
