"""Loading the historical claim corpus.

`data/knowledge-base/` is the only runtime retrieval source. `data/ground-truth/` is a
development answer key: it is not mounted into this container and no code path here may
reach it (constitution Principle V, FR-021).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Fields an adjuster's query would describe. repair_cost_actual, resolution and
# fraud_indicators stay in the payload so they cannot distort similarity (research D7).
EMBEDDED_FIELDS = ("description", "adjuster_notes", "damage_type", "severity")


def load_knowledge_base(directory: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not directory.is_dir():
        return records
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8-sig"))
        claim_id = record.get("claim_id") or path.stem
        records[claim_id] = record
    return records


def embedding_text(record: dict[str, Any]) -> str:
    parts = [str(record.get(field, "")) for field in EMBEDDED_FIELDS]
    parts.append(" ".join(record.get("affected_areas") or []))
    return " ".join(part for part in parts if part).strip()


def resolution_summary(record: dict[str, Any]) -> str:
    """Derived from the record's own outcome fields; never invented text."""
    resolution = str(record.get("resolution", "")).replace("_", " ").strip() or "outcome unrecorded"
    cost = record.get("repair_cost_actual")
    areas = ", ".join(record.get("affected_areas") or []) or "unspecified areas"
    if isinstance(cost, (int, float)):
        return f"Resolved as {resolution}; repairs to {areas} cost ${cost:,.0f}."
    return f"Resolved as {resolution}; repairs to {areas}."
