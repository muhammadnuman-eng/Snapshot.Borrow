from __future__ import annotations

from typing import Any

from lumenstage.config.settings import Settings
from lumenstage.storage.store import JsonDocumentStore


def get_health(
    _: dict[str, Any],
    __: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str] | None = None,
    query: dict[str, list[str]] | None = None,
):
    del params, query
    return 200, {"status": "ok", "collections": store.list_collections()}
