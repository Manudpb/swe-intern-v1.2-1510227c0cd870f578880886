"""Input contract acceptance checks, included in the infrastructure category."""
from io import BytesIO
from PIL import Image
import pytest
import requests
from conftest import submit_claim

class TestMultiModal:
    @pytest.mark.parametrize('format,mime', [('JPEG', 'image/jpeg'), ('PNG', 'image/png')])
    def test_image_only(self, api_url, valid_case, format, mime):
        # Keep both advertised input formats covered after distributing JPEG fixtures.
        with Image.open(valid_case[0]) as image, BytesIO() as encoded:
            image.save(encoded, format=format)
            response = requests.post(f'{api_url}/api/v1/claims/triage',
                                     files={'image': ('damage.' + format.lower(), encoded.getvalue(), mime)}, timeout=120)
        assert response.status_code in (200, 201)
        assert 'triage_assessment' in response.json()

    def test_image_plus_text(self, sample_triage):
        assert sample_triage['triage_assessment']['damage_description'].strip()

    def test_image_plus_text_plus_pdf(self, api_url, valid_case, test_documents_dir):
        document = test_documents_dir / 'IMG_001-inspection.pdf'
        assert document.is_file(), 'Required inspection PDF missing'
        response = submit_claim(api_url, valid_case[0], description='A burst pipe damaged the kitchen. Use the attached same-incident inspection to determine the full affected scope.', document_path=document)
        assert response.status_code in (200, 201)
        assessment = response.json()['triage_assessment']
        areas = {a.strip().lower().replace(' ', '_') for a in assessment.get('affected_areas', [])}
        assert {'kitchen', 'dining_room'} <= areas, 'Inspection identifies additional dining-room damage; PDF evidence was not used'
        assert assessment['estimated_repair_cost']['min'] == 4000
        assert assessment['estimated_repair_cost']['max'] == 16000

    def test_text_only(self, api_url):
        response = submit_claim(api_url, description='A burst supply pipe caused moderate water damage in the kitchen only. No photo is available.', policy_type='standard_homeowner')
        assert response.status_code in (200, 201), 'Text-only input is required; no dummy image is submitted'
        payload = response.json()
        assert 'triage_assessment' in payload
        assert payload['intake_validation']['is_valid_image'] is None, 'Absent visual check must be null, not a claimed image pass'

    def test_multiple_photos(self, api_url, valid_case):
        # Same incident, two views; repeat the image to ensure rooms are not counted twice.
        path, gt = valid_case
        mime = 'image/png' if path.suffix == '.png' else 'image/jpeg'
        with path.open('rb') as first, path.open('rb') as second:
            response = requests.post(f'{api_url}/api/v1/claims/triage', files=[('images', (path.name, first, mime)), ('images', ('second-view' + path.suffix, second, mime))], data={'description':gt['description_hint'], 'policy_type':gt['policy_type']}, timeout=120)
        assert response.status_code in (200, 201)
        assert response.json()['triage_assessment']['estimated_repair_cost'] == gt['estimated_repair_cost']
