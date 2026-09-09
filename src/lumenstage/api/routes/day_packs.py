"""HTTP operations for production day packs."""

from __future__ import annotations

from typing import Any

from lumenstage.config.settings import Settings
from lumenstage.errors import ValidationError
from lumenstage.services.day_pack import DayPackService
from lumenstage.storage.store import JsonDocumentStore
from lumenstage.utils.pagination import paginate


def _one(query: dict[str, list[str]], name: str, default: str = "") -> str:
    values = query.get(name, [])
    return values[-1] if values else default


def _positive_int(value: str, name: str, default: int) -> int:
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValidationError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise ValidationError(f"{name} must be positive")
    return parsed


def _item_payload(pack) -> dict[str, Any]:
    return {"resource": "day-packs", "item": pack.to_dict()}


def build_day_pack(
    body: dict[str, Any],
    _: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str],
    query: dict[str, list[str]] | None = None,
):
    del query
    production_id = params["production_id"]
    date = str(body.get("date", ""))
    publish = bool(body.get("publish", False))
    pack, created = DayPackService(store).build(production_id, date, publish=publish)
    return (201 if created else 200), _item_payload(pack)


def list_day_packs(
    _: dict[str, Any],
    settings: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str],
    query: dict[str, list[str]],
):
    production_id = params["production_id"]
    date = _one(query, "date") or None
    status = _one(query, "status") or None
    records = DayPackService(store).list(production_id, date=date, status=status)
    page_number = _positive_int(_one(query, "page"), "page", 1)
    requested_size = _positive_int(_one(query, "page_size"), "page_size", 50)
    page = paginate(
        records, page=page_number, page_size=min(requested_size, settings.max_page_size)
    )
    return 200, {
        "resource": "day-packs",
        "items": [item.to_dict() for item in page.items],
        "pagination": {
            "page": page.page,
            "page_size": page.page_size,
            "pages": page.pages,
            "total": page.total,
            "has_next": page.has_next,
            "has_prev": page.has_prev,
        },
        "store_revision": store.revision,
    }


def get_day_pack(
    _: dict[str, Any],
    __: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str],
    query: dict[str, list[str]] | None = None,
):
    del query
    pack = DayPackService(store).get(params["pack_id"])
    return 200, _item_payload(pack)


def publish_day_pack(
    body: dict[str, Any],
    _: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str],
    query: dict[str, list[str]] | None = None,
):
    del body, query
    pack = DayPackService(store).publish(params["pack_id"])
    return 200, _item_payload(pack)
