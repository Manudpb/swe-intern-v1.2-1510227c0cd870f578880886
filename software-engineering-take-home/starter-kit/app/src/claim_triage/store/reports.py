"""Bounded in-memory report and trace storage.

Reports live for the process lifetime; durable storage across restarts is out of scope for
this pilot (spec.md Assumptions). A trace is published only once its run completes, so an
in-progress id reads as absent and the API answers 404 rather than returning a half-written
trace as final.
"""
from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Any

MAX_ENTRIES = 500


class InMemoryReportStore:
    def __init__(self, max_entries: int = MAX_ENTRIES) -> None:
        self._max = max_entries
        self._reports: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._traces: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = Lock()

    def put(self, claim_id: str, report: dict[str, Any]) -> None:
        with self._lock:
            _insert(self._reports, claim_id, report, self._max)

    def get(self, claim_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._reports.get(claim_id)

    def put_trace(self, claim_id: str, trace: dict[str, Any]) -> None:
        with self._lock:
            _insert(self._traces, claim_id, trace, self._max)

    def get_trace(self, claim_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._traces.get(claim_id)


def _insert(store: OrderedDict, key: str, value: Any, limit: int) -> None:
    store[key] = value
    store.move_to_end(key)
    while len(store) > limit:
        store.popitem(last=False)
