from pathlib import Path

from lumenstage.api.app import LumenStageApp, Request
from lumenstage.config.settings import Settings


def test_health_endpoint(tmp_path: Path) -> None:
    resp = LumenStageApp(Settings(data_dir=tmp_path)).handle(Request("GET", "/health"))
    assert resp.status == 200
    assert resp.payload["status"] == "ok"
