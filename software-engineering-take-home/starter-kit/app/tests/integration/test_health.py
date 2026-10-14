"""US3 scenario 1 / FR-032 - readiness means something.

The contract pins the 200 body's `status` to "healthy", so a not-ready service answers 503
with the same shape instead (research D8). Reporting "connected" for an empty collection
would be a readiness signal that means nothing.
"""
from __future__ import annotations

import pytest

from tests.contract.conformance import assert_conforms

HEALTH_PATH = "/api/v1/health"

pytestmark = pytest.mark.integration


def test_health_is_200_and_connected_when_the_corpus_is_loaded(client):
    response = client.get(HEALTH_PATH)

    assert response.status_code == 200
    body = response.json()
    assert_conforms(HEALTH_PATH, "get", 200, body)
    assert body["status"] == "healthy"
    assert body["services"]["vector_db"] == "connected"
    assert body["services"]["llm"] == "configured"


def test_health_is_503_and_disconnected_when_the_store_is_empty(make_client):
    from claim_triage.rag.store_qdrant import QdrantStore

    empty = QdrantStore.in_memory()  # created but deliberately never populated
    client, _ = make_client(vectors=empty, skip_ingest=True)

    response = client.get(HEALTH_PATH)

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["services"]["vector_db"] == "disconnected"


def test_health_reports_a_missing_credential_without_leaking_anything(make_client, settings):
    unconfigured = settings.model_copy(update={"portkey_api_key": __import__("pydantic").SecretStr("")})
    client, _ = make_client(settings=unconfigured)

    body = client.get(HEALTH_PATH).json()

    assert body["services"]["llm"] == "not_configured"


def test_an_unreachable_store_is_disconnected_not_a_crash(make_client):
    class BrokenStore:
        def ensure_collection(self, name, dim):
            return None

        def upsert(self, name, points):
            return None

        def search(self, name, vector, top_k):
            return []

        def count(self, name):
            raise ConnectionError("qdrant is down")

    client, _ = make_client(vectors=BrokenStore(), skip_ingest=True)

    response = client.get(HEALTH_PATH)

    assert response.status_code == 503
    assert response.json()["services"]["vector_db"] == "disconnected"
