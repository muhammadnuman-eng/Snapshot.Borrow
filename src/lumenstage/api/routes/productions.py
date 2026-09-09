from __future__ import annotations

from typing import Any

from lumenstage.config.settings import Settings
from lumenstage.services.production import ProductionService
from lumenstage.storage.store import JsonDocumentStore


def list_productions(
    _: dict[str, Any],
    __: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str] | None = None,
    query: dict[str, list[str]] | None = None,
):
    del params, query
    rows = [a.to_dict() for a in ProductionService(store).list()]
    return 200, {"productions": rows, "count": len(rows)}


def create_production(
    body: dict[str, Any],
    __: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str] | None = None,
    query: dict[str, list[str]] | None = None,
):
    del params, query
    item = ProductionService(store).create(
        str(body.get("name", "")), str(body.get("slug", "")), metadata=body.get("metadata") or {}
    )
    return 201, {"production": item.to_dict()}
