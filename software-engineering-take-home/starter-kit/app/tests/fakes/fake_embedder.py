"""A deterministic embedder.

Tokens are hashed into signed buckets and the vector is L2-normalized, so cosine similarity
tracks term overlap. That is real enough for a meaningful relevance assertion over the actual
30-record corpus ("a burst-pipe query ranks a water-damage claim first") while staying
identical across machines and Python runs — an explicit seed, never the randomized `hash()`.
"""
from __future__ import annotations

import hashlib
import math
import re

DIMENSION = 384
SEED = b"claim-triage-test-embedder-v1"
_TOKEN = re.compile(r"[a-z0-9]+")


class FakeEmbedder:
    def __init__(self, dimension: int = DIMENSION) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        tokens = _TOKEN.findall((text or "").lower())
        for token in tokens:
            digest = hashlib.sha256(SEED + token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]
