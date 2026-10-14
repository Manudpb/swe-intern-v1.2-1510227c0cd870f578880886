"""Local embeddings.

Retrieval must not need a second paid credential (constitution Principle IV), so embeddings
run locally. The model is baked into the image at build time and an explicit `cache_dir` is
passed rather than relying on an env-var name that has moved between fastembed releases.
"""
from __future__ import annotations

from pathlib import Path

DIMENSION = 384  # BAAI/bge-small-en-v1.5


class FastEmbedEmbedder:
    def __init__(self, model_name: str, cache_dir: Path) -> None:
        from fastembed import TextEmbedding  # imported here so tests need no heavy dependency

        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))
        self._dimension = DIMENSION

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]
