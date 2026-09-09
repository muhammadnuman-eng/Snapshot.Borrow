from pathlib import Path

from lumenstage.reporting.dashboard import DashboardReport
from lumenstage.reporting.metrics import MetricsCollector
from lumenstage.services.showbook import ShowbookService
from lumenstage.storage.store import JsonDocumentStore


def test_metrics_and_dashboard(tmp_path: Path) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    ShowbookService(store).create("Daily", "daily")
    assert MetricsCollector(store).collect().total_records >= 1
    assert DashboardReport(store).build()["total_records"] >= 1
