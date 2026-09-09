"""HTTP API tests for production day packs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lumenstage.api.app import LumenStageApp, Request
from lumenstage.config.settings import Settings
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
def app(tmp_path: Path) -> LumenStageApp:
    return LumenStageApp(Settings(data_dir=tmp_path, max_page_size=2))


def send(
    app: LumenStageApp,
    method: str,
    target: str,
    payload: dict[str, object] | None = None,
):
    body = json.dumps(payload).encode() if payload is not None else b""
    return app.handle(Request(method, target, body, headers={"content-type": "application/json"}))


def test_api_build_returns_created_status_and_resource_shape(
    app: LumenStageApp, tmp_path: Path
) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    add_rehearsal(
        store,
        production.id,
        slug="tech",
        room_id="room-main",
        starts_at=REHEARSAL_START,
        ends_at=REHEARSAL_END,
    )
    response = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": PACK_DATE},
    )
    assert response.status == 201
    assert response.payload["resource"] == "day-packs"
    item = response.payload["item"]
    assert item["status"] == "draft"
    assert item["version"] == 1
    assert item["production_id"] == production.id
    assert item["date"] == PACK_DATE
    assert "gaps" in item
    assert "warnings" in item
    assert "call_timeline" in item


def test_api_rebuild_returns_ok_status_and_increments_version(
    app: LumenStageApp, tmp_path: Path
) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    first = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": PACK_DATE},
    )
    add_performance(store, production.id, slug="evening", starts_at=EVENING_START)
    second = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": PACK_DATE},
    )
    assert second.status == 200
    assert second.payload["item"]["id"] == first.payload["item"]["id"]
    assert second.payload["item"]["version"] == 2
    assert len(second.payload["item"]["performances"]) == 1


def test_api_unknown_production_returns_not_found(app: LumenStageApp) -> None:
    response = send(
        app,
        "POST",
        "/api/productions/PRD-notfound01/day-packs",
        {"date": PACK_DATE},
    )
    assert response.status == 404
    assert response.payload["type"] == "not_found"


def test_api_invalid_date_returns_validation_error(app: LumenStageApp, tmp_path: Path) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    response = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": "not-a-date"},
    )
    assert response.status == 400
    assert response.payload["type"] == "validation_error"


def test_api_get_day_pack_by_id(app: LumenStageApp, tmp_path: Path) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    seed_rich_day(store, production.id)
    created = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": PACK_DATE},
    )
    pack_id = created.payload["item"]["id"]
    fetched = send(app, "GET", f"/api/day-packs/{pack_id}")
    assert fetched.status == 200
    assert fetched.payload["resource"] == "day-packs"
    assert fetched.payload["item"]["id"] == pack_id
    assert len(fetched.payload["item"]["sound_cues"]) == 2


def test_api_get_missing_day_pack_returns_not_found(app: LumenStageApp) -> None:
    response = send(app, "GET", "/api/day-packs/DPK-notfound1")
    assert response.status == 404
    assert response.payload["type"] == "not_found"


def test_api_list_supports_status_and_date_filters(app: LumenStageApp, tmp_path: Path) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    draft = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": PACK_DATE},
    )
    published = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": OTHER_DATE, "publish": True},
    )
    by_date = send(app, "GET", f"/api/productions/{production.id}/day-packs?date={PACK_DATE}")
    assert by_date.status == 200
    assert [item["id"] for item in by_date.payload["items"]] == [draft.payload["item"]["id"]]
    by_status = send(
        app,
        "GET",
        f"/api/productions/{production.id}/day-packs?status=published",
    )
    assert [item["id"] for item in by_status.payload["items"]] == [published.payload["item"]["id"]]


def test_api_list_pagination_and_store_revision(app: LumenStageApp, tmp_path: Path) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    for offset, day in enumerate(("2021-03-15", "2021-03-16", "2021-03-17")):
        send(
            app,
            "POST",
            f"/api/productions/{production.id}/day-packs",
            {"date": day},
        )
    response = send(
        app,
        "GET",
        f"/api/productions/{production.id}/day-packs?page=1&page_size=99",
    )
    assert response.status == 200
    assert response.payload["resource"] == "day-packs"
    assert len(response.payload["items"]) == 2
    assert response.payload["pagination"]["page_size"] == 2
    assert response.payload["pagination"]["total"] == 3
    assert response.payload["pagination"]["has_next"] is True
    assert response.payload["store_revision"] == store.revision


def test_api_publish_sets_published_status_and_timestamp(
    app: LumenStageApp, tmp_path: Path
) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    created = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": PACK_DATE},
    )
    pack_id = created.payload["item"]["id"]
    published = send(app, "POST", f"/api/day-packs/{pack_id}/publish", {})
    assert published.status == 200
    item = published.payload["item"]
    assert item["status"] == "published"
    assert item["published_at"] is not None


def test_api_publish_already_published_returns_conflict(app: LumenStageApp, tmp_path: Path) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    created = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": PACK_DATE},
    )
    pack_id = created.payload["item"]["id"]
    send(app, "POST", f"/api/day-packs/{pack_id}/publish", {})
    again = send(app, "POST", f"/api/day-packs/{pack_id}/publish", {})
    assert again.status == 409
    assert again.payload["type"] == "conflict"


def test_api_rebuild_published_pack_returns_conflict(app: LumenStageApp, tmp_path: Path) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    created = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": PACK_DATE, "publish": True},
    )
    rebuilt = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": PACK_DATE},
    )
    assert rebuilt.status == 409
    assert rebuilt.payload["type"] == "conflict"


def test_api_build_with_publish_flag_creates_published_pack(
    app: LumenStageApp, tmp_path: Path
) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    response = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": PACK_DATE, "publish": True},
    )
    assert response.status == 201
    assert response.payload["item"]["status"] == "published"
    assert response.payload["item"]["published_at"] is not None


def test_api_empty_schedule_gap_is_visible_in_payload(app: LumenStageApp, tmp_path: Path) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    response = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": PACK_DATE},
    )
    gap_codes = {gap["code"] for gap in response.payload["item"]["gaps"]}
    assert "empty_schedule" in gap_codes


def test_api_assembled_sections_reflect_linked_catalog_records(
    app: LumenStageApp, tmp_path: Path
) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    seed_rich_day(store, production.id)
    response = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": PACK_DATE},
    )
    item = response.payload["item"]
    assert len(item["performances"]) == 2
    assert [cue["cue_number"] for cue in item["sound_cues"]] == [1, 2]
    assert "unready_sound_cue" in {warning["code"] for warning in item["warnings"]}
    assert "uncovered_role" in {gap["code"] for gap in item["gaps"]}
    assert len(item["call_timeline"]) >= 1


def test_api_different_dates_create_distinct_pack_ids(app: LumenStageApp, tmp_path: Path) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    production = seed_production(store)
    first = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": PACK_DATE},
    )
    second = send(
        app,
        "POST",
        f"/api/productions/{production.id}/day-packs",
        {"date": OTHER_DATE},
    )
    assert first.payload["item"]["id"] != second.payload["item"]["id"]
