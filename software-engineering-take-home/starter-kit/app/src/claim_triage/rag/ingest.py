"""Embedding the historical corpus into the vector store.

Idempotent on purpose: point ids are derived deterministically from the claim id, and a
collection that already holds the expected count is left alone. Restarting the service must
not re-embed 30 records, and two API replicas must not duplicate them.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from claim_triage.deps import Deps
from claim_triage.rag.corpus import embedding_text

log = logging.getLogger(__name__)


def ingest(deps: Deps, *, force: bool = False) -> int:
    """Ensure the collection holds the corpus. Returns the number of points stored."""
    records = deps.knowledge_base
    if not records:
        log.warning("No knowledge-base records found; retrieval will be unavailable")
        return 0

    name = deps.settings.collection_name
    deps.vectors.ensure_collection(name, deps.embedder.dimension)

    existing = deps.vectors.count(name)
    if not force and existing >= len(records):
        log.info("Collection %s already holds %d points; skipping embedding", name, existing)
        return existing

    claim_ids = list(records)
    vectors = deps.embedder.embed([embedding_text(records[cid]) for cid in claim_ids])
    points: list[tuple[str, list[float], dict[str, Any]]] = []
    for claim_id, vector in zip(claim_ids, vectors, strict=True):
        record = records[claim_id]
        points.append(
            (
                claim_id,
                vector,
                {
                    "claim_id": claim_id,
                    "damage_type": record.get("damage_type"),
                    "severity": record.get("severity"),
                    "affected_areas": record.get("affected_areas") or [],
                    "policy_type": record.get("policy_type"),
                    "resolution": record.get("resolution"),
                    "repair_cost_actual": record.get("repair_cost_actual"),
                },
            )
        )
    deps.vectors.upsert(name, points)
    stored = deps.vectors.count(name)
    log.info("Embedded %d historical claims into %s", len(points), name)
    return stored


def ingest_with_retry(deps: Deps, *, attempts: int = 10, delay: float = 2.0) -> int:
    """Qdrant may still be starting when the API comes up. Bounded retries, never a loop."""
    for attempt in range(1, attempts + 1):
        try:
            return ingest(deps)
        except Exception as exc:  # noqa: BLE001 - startup races are expected and retried
            if attempt == attempts:
                log.error("Ingestion failed after %d attempts: %s", attempts, type(exc).__name__)
                return 0
            log.info("Vector store not ready (attempt %d/%d); retrying", attempt, attempts)
            time.sleep(delay)
    return 0
