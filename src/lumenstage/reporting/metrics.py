"""Aggregate production metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lumenstage.storage.store import JsonDocumentStore


@dataclass(slots=True)
class MetricsSnapshot:
    collections: dict[str, int] = field(default_factory=dict)
    total_records: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"collections": dict(self.collections), "total_records": self.total_records}


class MetricsCollector:
    def __init__(self, store: JsonDocumentStore) -> None:
        self.store = store

    def collect(self) -> MetricsSnapshot:
        snap = MetricsSnapshot()
        for name in self.store.list_collections():
            count = len(self.store.read_collection(name))
            snap.collections[name] = count
            snap.total_records += count
        return snap
