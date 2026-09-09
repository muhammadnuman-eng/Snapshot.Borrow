"""Production catalog registry and cross-entity lookups."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lumenstage.storage.store import JsonDocumentStore


@dataclass(slots=True)
class CatalogEntry:
    collection: str
    item_id: str
    name: str
    slug: str
    status: str
    tags: list[str] = field(default_factory=list)

    def matches(self, query: str) -> bool:
        blob = "".join([self.name, self.slug, self.status, "".join(self.tags)]).lower()
        return query.lower() in blob


class ProductionCatalog:
    def __init__(self, store: JsonDocumentStore) -> None:
        self.store = store

    def scan(self) -> list[CatalogEntry]:
        entries: list[CatalogEntry] = []
        for collection in self.store.list_collections():
            for row in self.store.read_collection(collection):
                entries.append(
                    CatalogEntry(
                        collection,
                        str(row.get("id", "")),
                        str(row.get("name", "")),
                        str(row.get("slug", "")),
                        str(row.get("status", "")),
                        list(row.get("tags") or []),
                    )
                )
        return entries

    def search(self, query: str) -> list[CatalogEntry]:
        return [e for e in self.scan() if e.matches(query)]

    def stats(self) -> dict[str, Any]:
        grouped: dict[str, int] = {}
        for entry in self.scan():
            grouped[entry.collection] = grouped.get(entry.collection, 0) + 1
        return {
            "collections": len(grouped),
            "records": sum(grouped.values()),
            "by_collection": grouped,
        }
