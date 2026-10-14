"""US3 - ingestion is idempotent and deterministic.

Restarting the service must not re-embed 30 records, and two API replicas must not duplicate
them. Both properties come from deriving the point id from the claim id.
"""
from __future__ import annotations

import pytest

from claim_triage.rag.ingest import ingest
from claim_triage.rag.store_qdrant import QdrantStore, point_id

pytestmark = pytest.mark.unit


def test_ingestion_stores_the_whole_corpus(make_deps, knowledge_base, settings):
    deps = make_deps()  # the fixture ingests on build

    assert deps.vectors.count(settings.collection_name) == len(knowledge_base)


def test_a_second_run_re_embeds_nothing(make_deps, settings):
    deps = make_deps()
    before = deps.vectors.count(settings.collection_name)
    calls = {"n": 0}

    original = deps.embedder.embed

    def counting(texts):
        calls["n"] += 1
        return original(texts)

    deps.embedder.embed = counting  # type: ignore[method-assign]
    stored = ingest(deps)

    assert stored == before
    assert calls["n"] == 0, "a populated collection must not be re-embedded"


def test_re_ingesting_upserts_rather_than_duplicating(make_deps, settings, knowledge_base):
    deps = make_deps()

    ingest(deps, force=True)

    assert deps.vectors.count(settings.collection_name) == len(knowledge_base)


def test_point_ids_are_deterministic():
    assert point_id("CLM-2023-001") == point_id("CLM-2023-001")
    assert point_id("CLM-2023-001") != point_id("CLM-2023-002")


def test_an_empty_corpus_stores_nothing_and_says_so(make_deps):
    deps = make_deps(knowledge_base={}, vectors=QdrantStore.in_memory(), skip_ingest=True)

    assert ingest(deps) == 0


def test_payload_carries_the_claim_id_for_retrieval(make_deps, settings):
    deps = make_deps()

    hits = deps.vectors.search(settings.collection_name, deps.embedder.embed(["burst pipe"])[0], 3)

    assert hits
    for hit in hits:
        assert hit.claim_id
        assert hit.payload["claim_id"] == hit.claim_id


def test_embedding_text_excludes_the_outcome_fields(knowledge_base):
    """Cost and resolution stay in the payload so they cannot distort similarity (D7)."""
    from claim_triage.rag.corpus import embedding_text

    record = knowledge_base["CLM-2023-001"]
    text = embedding_text(record)

    assert record["description"][:40] in text
    assert str(record["repair_cost_actual"]) not in text
    assert record["resolution"] not in text
