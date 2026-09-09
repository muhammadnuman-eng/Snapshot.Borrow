from __future__ import annotations

import json
from pathlib import Path

from lumenstage.cli.main import main


def test_cli_catalog_crud_round_trip(tmp_path: Path, capsys) -> None:
    common = ["--data-dir", str(tmp_path), "catalog", "productions"]
    assert main([*common, "create", "Hamlet", "hamlet", "--tag", "Classic"]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["tags"] == ["classic"]
    item_id = created["id"]
    assert main([*common, "update", item_id, "--status", "inactive"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "inactive"
    assert main([*common, "get", item_id]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "Hamlet"
    assert main([*common, "delete", item_id]) == 0
    assert json.loads(capsys.readouterr().out)["deleted"] == item_id


def test_cli_reports_domain_errors_without_traceback(tmp_path: Path, capsys) -> None:
    result = main(["--data-dir", str(tmp_path), "catalog", "productions", "get", "missing"])
    assert result == 2
    assert "error:" in capsys.readouterr().err


def test_cli_lists_registry_resources(tmp_path: Path, capsys) -> None:
    assert main(["--data-dir", str(tmp_path), "resources"]) == 0
    resources = json.loads(capsys.readouterr().out)
    assert len(resources) == 16
    assert any(item["name"] == "performances" for item in resources)
