"""Application service for production showbooks."""

from __future__ import annotations

from lumenstage.models.showbook import Showbook
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class ShowbookService(EntityService[Showbook]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, Showbook, "showbooks", "showbook")

    def add_section(self, showbook_id: str, title: str) -> Showbook:
        showbook = self.get(showbook_id)
        showbook.add_section(title)
        return self.repo.save(showbook)

    def lock(self, showbook_id: str) -> Showbook:
        showbook = self.get(showbook_id)
        showbook.lock()
        return self.repo.save(showbook)

    def unlocked(self) -> list[Showbook]:
        return [item for item in self.list(status="active") if not item.locked]
