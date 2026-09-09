from __future__ import annotations

from typing import Any

from lumenstage.config.settings import Settings
from lumenstage.services.showbook import ShowbookService
from lumenstage.storage.store import JsonDocumentStore


def list_showbooks(
    _: dict[str, Any],
    __: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str] | None = None,
    query: dict[str, list[str]] | None = None,
):
    del params, query
    rows = [p.to_dict() for p in ShowbookService(store).list()]
    return 200, {"showbooks": rows, "count": len(rows)}


def create_showbook(
    body: dict[str, Any],
    __: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str] | None = None,
    query: dict[str, list[str]] | None = None,
):
    del params, query
    item = ShowbookService(store).create(
        str(body.get("name", "")), str(body.get("slug", "")), tags=body.get("tags") or []
    )
    return 201, {"showbook": item.to_dict()}
