"""Retrieval sanity checks; ranking quality and embedding implementation also need review."""
import requests

class TestRAG:
    def test_vector_db_has_records(self, qdrant_url, knowledge_base_files):
        try:
            response = requests.get(f'{qdrant_url}/collections', timeout=5)
            response.raise_for_status()
        except requests.RequestException:
            import pytest
            pytest.skip('Alternative vector store: interviewer must verify ingestion; do not treat this as a pass')
        total = 0
        for collection in response.json().get('result', {}).get('collections', []):
            detail = requests.get(f"{qdrant_url}/collections/{collection['name']}", timeout=5)
            detail.raise_for_status()
            total += detail.json().get('result', {}).get('points_count', 0)
        assert total >= len(knowledge_base_files) * 0.8

    def test_similar_claims_are_real_and_relevant(self, sample_triage, knowledge_base_files):
        claims = sample_triage['triage_assessment'].get('similar_past_claims')
        assert isinstance(claims, list) and claims
        ids = [c.get('claim_id') for c in claims]
        assert all(i in knowledge_base_files for i in ids), 'Fabricated historical claim ID'
        assert any(knowledge_base_files[i]['damage_type'] == 'water_damage' for i in ids), 'No water-damage record for the supplied burst-pipe case'

    def test_similarity_scores(self, sample_triage):
        claims = sample_triage['triage_assessment'].get('similar_past_claims', [])
        assert claims
        for claim in claims:
            value = claim.get('similarity_score')
            assert isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1
