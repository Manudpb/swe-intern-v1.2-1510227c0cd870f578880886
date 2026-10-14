"""The injection point.

`create_app(deps)` is the only way the application is built, and `build_deps(settings)`
is the only place a real client is constructed. No request handler constructs a provider
(constitution Principle VI).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from claim_triage.llm.ports import LLMClient
from claim_triage.settings import Settings


@runtime_checkable
class Embedder(Protocol):
    @property
    def dimension(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class ScoredPoint:
    claim_id: str
    score: float
    payload: dict[str, Any]


@runtime_checkable
class VectorStore(Protocol):
    def ensure_collection(self, name: str, dim: int) -> None: ...

    def upsert(self, name: str, points: list[tuple[str, list[float], dict[str, Any]]]) -> None: ...

    def search(self, name: str, vector: list[float], top_k: int) -> list[ScoredPoint]: ...

    def count(self, name: str) -> int: ...


@runtime_checkable
class ReportStore(Protocol):
    def put(self, claim_id: str, report: dict[str, Any]) -> None: ...

    def get(self, claim_id: str) -> dict[str, Any] | None: ...

    def put_trace(self, claim_id: str, trace: dict[str, Any]) -> None: ...

    def get_trace(self, claim_id: str) -> dict[str, Any] | None: ...


@runtime_checkable
class Clock(Protocol):
    def __call__(self) -> datetime: ...


@runtime_checkable
class IdFactory(Protocol):
    def __call__(self) -> str: ...


@dataclass(frozen=True)
class Deps:
    """Everything the application needs from the outside world, in one substitutable bundle."""

    settings: Settings
    llm: LLMClient
    embedder: Embedder
    vectors: VectorStore
    cost_table: Any  # CostTable; typed loosely to keep tools/ out of the import graph here
    coverage_table: Any  # CoverageTable
    reports: ReportStore
    clock: Clock
    new_id: IdFactory
    knowledge_base: dict[str, dict[str, Any]]
