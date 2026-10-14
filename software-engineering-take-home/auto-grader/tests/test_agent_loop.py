"""Basic ReAct structure and tool/report consistency, not execution attestation."""
import json
import requests
from trace_checks import validate_trace

class TestAgentLoop:
    def test_trace_has_cycles_and_consistent_evidence(self, api_url, sample_triage, tools_dir, knowledge_base_files):
        response = requests.get(f"{api_url}/api/v1/agent/trace/{sample_triage['claim_id']}", timeout=30)
        assert response.status_code == 200
        trace = response.json()
        assert trace.get('claim_id') == sample_triage['claim_id']
        steps = trace.get('steps', [])
        for kind in ('reason', 'act', 'observe'):
            assert sum(s.get('type') == kind for s in steps) >= 2, f'Expected two {kind} events'
        assert any([s.get('type') for s in steps[i:i+3]] == ['reason', 'act', 'observe'] for i in range(len(steps)-2))
        rules = json.loads((tools_dir / 'cost-estimator.json').read_text(encoding='utf-8-sig'))
        validate_trace(trace, sample_triage['triage_assessment'], rules, knowledge_base_files)
