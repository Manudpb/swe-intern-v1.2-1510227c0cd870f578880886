"""Shared HTTP fixtures. Required missing assets fail evaluation explicitly."""
import json
import os
from contextlib import ExitStack
from pathlib import Path
import pytest
import requests

DATA = Path(__file__).resolve().parents[1] / 'starter-kit' / 'data'
API_URL = os.environ.get('API_URL', 'http://localhost:8000')
UI_URL = os.environ.get('UI_URL', 'http://localhost:3000')
QDRANT_URL = os.environ.get('QDRANT_URL', 'http://localhost:6333')
GROUND_TRUTH_DIR = Path(os.environ.get('GROUND_TRUTH_DIR', DATA / 'ground-truth'))
TEST_IMAGES_DIR = Path(os.environ.get('TEST_IMAGES_DIR', DATA / 'test-images'))
TEST_DOCUMENTS_DIR = Path(os.environ.get('TEST_DOCUMENTS_DIR', DATA / 'test-documents'))
KNOWLEDGE_BASE_DIR = Path(os.environ.get('KNOWLEDGE_BASE_DIR', DATA / 'knowledge-base'))
TOOLS_DIR = Path(os.environ.get('TOOLS_DIR', DATA.parent / 'tools'))

@pytest.fixture(scope='session')
def api_url(): return API_URL
@pytest.fixture(scope='session')
def ui_url(): return UI_URL
@pytest.fixture(scope='session')
def qdrant_url(): return QDRANT_URL
@pytest.fixture(scope='session')
def ground_truth_dir(): return GROUND_TRUTH_DIR
@pytest.fixture(scope='session')
def test_images_dir(): return TEST_IMAGES_DIR
@pytest.fixture(scope='session')
def test_documents_dir(): return TEST_DOCUMENTS_DIR
@pytest.fixture(scope='session')
def knowledge_base_dir(): return KNOWLEDGE_BASE_DIR
@pytest.fixture(scope='session')
def tools_dir(): return TOOLS_DIR

def load_records(directory):
    records = {p.stem: json.loads(p.read_text(encoding='utf-8-sig')) for p in sorted(directory.glob('*.json'))}
    assert records, f'Required evaluation records missing: {directory}'
    return records

@pytest.fixture(scope='session')
def ground_truth_files(ground_truth_dir): return load_records(ground_truth_dir)
@pytest.fixture(scope='session')
def knowledge_base_files(knowledge_base_dir): return load_records(knowledge_base_dir)

def image_for(directory, image_id):
    matches = [directory / (image_id + ext) for ext in ('.png', '.jpg', '.jpeg') if (directory / (image_id + ext)).is_file()]
    assert len(matches) == 1, f'Expected exactly one fixture for {image_id}; found {matches}'
    return matches[0]

@pytest.fixture(scope='session')
def valid_case(test_images_dir, ground_truth_files):
    gt = ground_truth_files['IMG_001']
    return image_for(test_images_dir, 'IMG_001'), gt

@pytest.fixture(scope='session')
def sample_triage(api_url, valid_case):
    path, gt = valid_case
    response = submit_claim(api_url, path, description=gt['description_hint'], policy_type=gt['policy_type'])
    assert response.status_code in (200, 201), f'Valid submission failed: HTTP {response.status_code}'
    return response.json()

def submit_claim(api_url, image_path=None, description=None, document_path=None, policy_type=None):
    with ExitStack() as stack:
        files = {}
        for name, path in [('image', image_path), ('document', document_path)]:
            if path is not None:
                path = Path(path)
                mime = 'application/pdf' if name == 'document' else ('image/png' if path.suffix.lower() == '.png' else 'image/jpeg')
                files[name] = (path.name, stack.enter_context(path.open('rb')), mime)
        data = {k: v for k, v in [('description', description), ('policy_type', policy_type)] if v is not None}
        if not files and data:
            # Keep text-only requests within the published multipart contract.
            files = {name: (None, value) for name, value in data.items()}
            data = {}
        return requests.post(f'{api_url}/api/v1/claims/triage', files=files or None, data=data, timeout=120)


def pytest_addoption(parser):
    parser.addoption('--accuracy-smoke', action='store_true',
                     help='Only three varied positive cases; diagnostic, not a full grade')
