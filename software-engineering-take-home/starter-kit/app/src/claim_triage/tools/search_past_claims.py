"""Semantic search over the historical claim corpus.

Every returned claim id exists in the corpus; nothing is synthesized. The ids returned here
are the only ones the final report may cite (invariant I4).
"""
from __future__ import annotations

from typing import Any

from claim_triage.deps import Deps
from claim_triage.rag.corpus import resolution_summary

NAME = "search_past_claims"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Natural-language description of the damage to match against.",
        },
        "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
    },
    "required": ["query"],
}

DESCRIPTION = "Search the company's historical claims for incidents similar to this one."

DEFAULT_TOP_K = 5


def run(deps: Deps, arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        return {"error": "invalid_query", "message": "query must be a non-empty string"}

    top_k = arguments.get("top_k") or DEFAULT_TOP_K
    try:
        top_k = max(1, min(10, int(top_k)))
    except (TypeError, ValueError):
        top_k = DEFAULT_TOP_K

    try:
        vector = deps.embedder.embed([query])[0]
        hits = deps.vectors.search(deps.settings.collection_name, vector, top_k)
    except Exception:  # noqa: BLE001 - an unreachable store is a recorded tool failure
        return {"error": "retrieval_unavailable", "message": "The claim archive is unreachable"}

    claims: list[dict[str, Any]] = []
    for hit in hits:
        record = deps.knowledge_base.get(hit.claim_id)
        if not record:
            continue  # never surface an id that is not in the corpus
        claims.append(
            {
                "claim_id": hit.claim_id,
                "similarity_score": round(max(0.0, min(1.0, hit.score)), 4),
                "damage_type": record.get("damage_type"),
                "severity": record.get("severity"),
                "affected_areas": record.get("affected_areas") or [],
                "resolution_summary": resolution_summary(record),
            }
        )
    if not claims:
        return {"error": "no_similar_claims", "message": "No comparable historical claim found"}
    return {"claims": claims}
