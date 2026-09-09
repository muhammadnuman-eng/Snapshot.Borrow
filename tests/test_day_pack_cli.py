"""CLI tests for production day packs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lumenstage.cli.main import main
from lumenstage.services.day_pack import DayPackService
from lumenstage.storage.store import JsonDocumentStore
from test_day_pack import (
    OTHER_DATE,
    PACK_DATE,
    EVENING_START,
    REHEARSAL_END,
    REHEARSAL_START,
    add_performance,
    add_rehearsal,
    seed_production,
    seed_rich_day,
)


@pytest.fixture()
def cli_runner(tmp_path: Path):
    def run(*args: str):
        result = main(["--data-dir", str(tmp_path), "day-pack", *args])
        return result

    return run


def test_cli_build_outputs_draft_pack_json(cli_runner, tmp_path: Path, capsys) -> None:
    production = seed_production(JsonDocumentStore(tmp_path / "store.json"))
    add_rehearsal(
        JsonDocumentStore(tmp_path / "store.json"),
        production.id,
        slug="tech",
        room_id="room-main",
        starts_at=REHEARSAL_START,
        ends_at=REHEARSAL_END,
    )
    assert cli_runner("build", production.id, PACK_DATE) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "draft"
    assert payload["version"] == 1
    assert payload["date"] == PACK_DATE
    assert payload["production_id"] == production.id


def test_cli_get_returns_persisted_pack(cli_runner, tmp_path: Path, capsys) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    seed_rich_day(store, production.id)
    assert cli_runner("build", production.id, PACK_DATE) == 0
    pack_id = json.loads(capsys.readouterr().out)["id"]
    assert cli_runner("get", pack_id) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == pack_id
    assert len(payload["performances"]) == 2


def test_cli_list_filters_by_production_date_and_status(cli_runner, tmp_path: Path, capsys) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    assert cli_runner("build", production.id, PACK_DATE) == 0
    capsys.readouterr()
    assert cli_runner("build", production.id, OTHER_DATE, "--publish") == 0
    capsys.readouterr()
    assert cli_runner("list", "--production", production.id, "--date", PACK_DATE) == 0
    draft_rows = json.loads(capsys.readouterr().out)
    assert len(draft_rows) == 1
    assert draft_rows[0]["status"] == "draft"
    assert cli_runner("list", "--production", production.id, "--status", "published") == 0
    published_rows = json.loads(capsys.readouterr().out)
    assert len(published_rows) == 1
    assert published_rows[0]["status"] == "published"


def test_cli_publish_updates_lifecycle(cli_runner, tmp_path: Path, capsys) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    assert cli_runner("build", production.id, PACK_DATE) == 0
    pack_id = json.loads(capsys.readouterr().out)["id"]
    assert cli_runner("publish", pack_id) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "published"
    assert payload["published_at"] is not None


def test_cli_build_with_publish_flag(cli_runner, tmp_path: Path, capsys) -> None:
    production = seed_production(JsonDocumentStore(tmp_path / "store.json"))
    assert cli_runner("build", production.id, PACK_DATE, "--publish") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "published"
    assert payload["published_at"] is not None


def test_cli_unknown_production_reports_error_exit_code(tmp_path: Path, capsys) -> None:
    result = main(["--data-dir", str(tmp_path), "day-pack", "build", "PRD-missing", PACK_DATE])
    assert result == 2
    assert "error:" in capsys.readouterr().err.lower()


def test_cli_publish_already_published_reports_error(cli_runner, tmp_path: Path, capsys) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    assert cli_runner("build", production.id, PACK_DATE, "--publish") == 0
    pack_id = json.loads(capsys.readouterr().out)["id"]
    result = main(["--data-dir", str(tmp_path), "day-pack", "publish", pack_id])
    assert result == 2
    assert "error:" in capsys.readouterr().err.lower()


def test_cli_rebuild_published_pack_reports_error(cli_runner, tmp_path: Path, capsys) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    assert cli_runner("build", production.id, PACK_DATE, "--publish") == 0
    capsys.readouterr()
    result = main(["--data-dir", str(tmp_path), "day-pack", "build", production.id, PACK_DATE])
    assert result == 2
    assert "error:" in capsys.readouterr().err.lower()


def test_cli_persistence_across_invocations(cli_runner, tmp_path: Path, capsys) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    add_performance(store, production.id, slug="evening", starts_at=EVENING_START)
    assert cli_runner("build", production.id, PACK_DATE) == 0
    pack_id = json.loads(capsys.readouterr().out)["id"]
    reloaded = DayPackService(JsonDocumentStore(tmp_path / "store.json"))
    loaded = reloaded.get(pack_id)
    assert loaded.date == PACK_DATE
    assert len(loaded.performances) == 1


def test_cli_rebuild_increments_version(cli_runner, tmp_path: Path, capsys) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    assert cli_runner("build", production.id, PACK_DATE) == 0
    first = json.loads(capsys.readouterr().out)
    add_performance(store, production.id, slug="evening", starts_at=EVENING_START)
    assert cli_runner("build", production.id, PACK_DATE) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["id"] == first["id"]
    assert second["version"] == 2
