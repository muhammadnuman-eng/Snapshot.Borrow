"""Secondary indexes for faster lookups."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any


class SlugIndex:
    def __init__(
        self, key: Callable[[dict[str, Any]], str] = lambda r: str(r.get("slug", ""))
    ) -> None:
        self.key = key
        self._by_slug: dict[str, list[str]] = defaultdict(list)

    def rebuild(self, rows: Iterable[dict[str, Any]]) -> None:
        self._by_slug.clear()
        for row in rows:
            slug = self.key(row)
            item_id = str(row.get("id", ""))
            if slug and item_id:
                self._by_slug[slug].append(item_id)

    def lookup(self, slug: str) -> list[str]:
        return list(self._by_slug.get(slug, []))
