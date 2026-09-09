"""Dashboard-style summary report."""

from __future__ import annotations

from typing import Any

from lumenstage.reporting.metrics import MetricsCollector
from lumenstage.storage.store import JsonDocumentStore


class DashboardReport:
    def __init__(self, store: JsonDocumentStore) -> None:
        self.store = store

    def build(self) -> dict[str, Any]:
        metrics = MetricsCollector(self.store).collect()
        top = sorted(metrics.collections.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {
            "total_records": metrics.total_records,
            "top_collections": [{"name": n, "count": c} for n, c in top],
            "collection_count": len(metrics.collections),
        }
