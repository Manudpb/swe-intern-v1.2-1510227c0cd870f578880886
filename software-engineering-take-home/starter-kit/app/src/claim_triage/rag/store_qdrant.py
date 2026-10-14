"""Qdrant behind the VectorStore port.

Production points at the Compose service; tests construct the same class over
`QdrantClient(":memory:")`, which is the client's local mode with an identical API
(research D13). That is what lets the suite run with Qdrant down.
"""
from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from claim_triage.deps import ScoredPoint

NAMESPACE = uuid.UUID("6f3d9c1e-2a4b-4c8d-9e7f-1b2c3d4e5f60")


def point_id(claim_id: str) -> str:
    """Deterministic, so re-ingesting the same corpus upserts rather than duplicates."""
    return str(uuid.uuid5(NAMESPACE, claim_id))


class QdrantStore:
    def __init__(self, client: QdrantClient) -> None:
        self._client = client

    @classmethod
    def in_memory(cls) -> "QdrantStore":
        return cls(QdrantClient(location=":memory:"))

    @classmethod
    def from_url(cls, url: str, timeout: float = 10.0) -> "QdrantStore":
        return cls(QdrantClient(url=url, timeout=int(timeout)))

    def ensure_collection(self, name: str, dim: int) -> None:
        if not self._client.collection_exists(name):
            self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    def upsert(self, name: str, points: list[tuple[str, list[float], dict[str, Any]]]) -> None:
        self._client.upsert(
            collection_name=name,
            points=[
                PointStruct(id=point_id(claim_id), vector=vector, payload=payload)
                for claim_id, vector, payload in points
            ],
        )

    def search(self, name: str, vector: list[float], top_k: int) -> list[ScoredPoint]:
        if not self._client.collection_exists(name):
            return []
        hits = self._client.query_points(
            collection_name=name, query=vector, limit=top_k, with_payload=True
        ).points
        return [
            ScoredPoint(
                claim_id=str((hit.payload or {}).get("claim_id", "")),
                score=float(hit.score),
                payload=dict(hit.payload or {}),
            )
            for hit in hits
        ]

    def count(self, name: str) -> int:
        if not self._client.collection_exists(name):
            return 0
        return int(self._client.count(collection_name=name, exact=True).count)
