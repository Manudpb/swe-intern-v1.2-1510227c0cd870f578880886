"""Positive acceptance and all five labelled negative intake cases."""
import pytest
from conftest import submit_claim, image_for

class TestInputGuardrails:
    def test_valid_damage_image_accepted(self, sample_triage):
        validation = sample_triage.get('intake_validation', {})
        for field in ('is_property_damage', 'is_valid_image', 'no_pii_detected', 'no_offensive_content'):
            assert validation.get(field) is True, field

    @pytest.mark.parametrize('image_id', ['IMG_036', 'IMG_037', 'IMG_038', 'IMG_039', 'IMG_040'])
    def test_unsuitable_evidence_rejected(self, image_id, api_url, test_images_dir, ground_truth_files):
        expected = ground_truth_files[image_id]['intake_validation']
        response = submit_claim(api_url, image_for(test_images_dir, image_id))
        assert response.status_code == 400, f'{image_id}: expected input rejection, got {response.status_code}'
        payload = response.json()
        assert isinstance(payload.get('message'), str) and payload['message'].strip()
        validation = payload.get('intake_validation', {})
        # The decisive rejection flag must be false; uncertain secondary flags need not be guessed.
        field = {'IMG_036':'is_property_damage', 'IMG_037':'is_property_damage', 'IMG_038':'is_property_damage', 'IMG_039':'is_valid_image', 'IMG_040':'no_pii_detected'}[image_id]
        assert expected[field] is False
        assert validation.get(field) is False, f'{image_id}: missing rejection reason {field}'
        assert not payload.get('triage_assessment'), 'Rejected input must not proceed to triage'

class TestOutputSafety:
    def test_clean_output_passes_safety(self, sample_triage):
        safety = sample_triage.get('safety_checks', {})
        for field in ('no_coverage_promises', 'no_legal_advice', 'no_settlement_amounts', 'no_liability_determination', 'no_emotional_language'):
            assert safety.get(field) is True, field
        # Semantic safety still requires human review; flags alone do not prove it.
