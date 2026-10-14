"""US3 - precedent is real, ranked, and never invented.

Run against the real 30-record corpus in an in-memory store with a deterministic embedder, so
"a burst-pipe query ranks a water-damage claim first" is a genuine assertion rather than a
tautology against a stub (research D13).
"""
from __future__ import annotations

import pytest

from claim_triage.tools import search_past_claims
from tests.conftest import submit

pytestmark = pytest.mark.integration


def test_a_burst_pipe_query_ranks_a_water_damage_claim_first(deps, knowledge_base):
    result = search_past_claims.run(
        deps, {"query": "burst pipe flooded kitchen floor water damage", "top_k": 5}
    )

    claims = result["claims"]
    assert claims
    assert knowledge_base[claims[0]["claim_id"]]["damage_type"] == "water_damage"


def test_results_are_ordered_by_descending_similarity(deps):
    result = search_past_claims.run(deps, {"query": "fire damage smoke in the kitchen"})

    scores = [claim["similarity_score"] for claim in result["claims"]]
    assert scores == sorted(scores, reverse=True)


def test_every_returned_claim_id_is_real_and_scores_are_in_range(deps, knowledge_base):
    result = search_past_claims.run(deps, {"query": "storm damage to the roof"})

    for claim in result["claims"]:
        assert claim["claim_id"] in knowledge_base
        assert 0.0 <= claim["similarity_score"] <= 1.0
        assert claim["resolution_summary"].strip()


def test_top_k_is_respected_and_clamped(deps):
    assert len(search_past_claims.run(deps, {"query": "water damage", "top_k": 3})["claims"]) <= 3
    assert len(search_past_claims.run(deps, {"query": "water damage", "top_k": 99})["claims"]) <= 10


def test_an_empty_query_is_an_error_not_a_blind_search(deps):
    result = search_past_claims.run(deps, {"query": "   "})

    assert result["error"] == "invalid_query"


def test_an_unreachable_store_returns_an_error_and_invents_nothing(make_deps):
    class BrokenStore:
        def ensure_collection(self, name, dim):
            return None

        def upsert(self, name, points):
            return None

        def count(self, name):
            return 0

        def search(self, name, vector, top_k):
            raise ConnectionError("qdrant is down")

    deps = make_deps(vectors=BrokenStore(), skip_ingest=True)
    result = search_past_claims.run(deps, {"query": "burst pipe"})

    assert result["error"] == "retrieval_unavailable"
    assert "claims" not in result


def test_a_report_only_cites_retrieved_claims(client, damage_photo, knowledge_base):
    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    cited = response.json()["triage_assessment"]["similar_past_claims"]
    assert cited
    for claim in cited:
        assert claim["claim_id"] in knowledge_base


def test_a_fabricated_citation_is_dropped_from_the_report(make_client, damage_photo):
    """US3 scenario 4: the service does not pass through an id retrieval never returned."""
    from tests.fakes import FakeLLM, build_script, cost_turn, search_turn, submit_turn

    llm = FakeLLM(
        build_script(
            triage=[
                search_turn(),
                cost_turn(),
                submit_turn(
                    claims=[
                        {
                            "claim_id": "CLM-9999-999",
                            "similarity_score": 0.99,
                            "resolution_summary": "Entirely invented.",
                        }
                    ]
                ),
            ]
        )
    )
    client, _ = make_client(llm=llm)

    response = submit(client, images=[damage_photo], description="Burst pipe in the kitchen")

    assert response.status_code == 200
    cited = response.json()["triage_assessment"]["similar_past_claims"]
    assert all(claim["claim_id"] != "CLM-9999-999" for claim in cited)


def test_resolution_summaries_come_from_the_record(deps, knowledge_base):
    result = search_past_claims.run(deps, {"query": "burst pipe kitchen water"})

    claim = result["claims"][0]
    record = knowledge_base[claim["claim_id"]]
    summary = claim["resolution_summary"].lower()
    assert record["resolution"].replace("_", " ") in summary
