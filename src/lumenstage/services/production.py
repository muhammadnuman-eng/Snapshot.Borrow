"""Application service for theatrical productions."""

from __future__ import annotations

from lumenstage.models.production import Production
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class ProductionService(EntityService[Production]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, Production, "productions", "production")

    def advance_stage(self, production_id: str, stage: str) -> Production:
        production = self.get(production_id)
        production.set_stage(stage)
        return self.repo.save(production)

    def ready_for_rehearsal(self) -> list[Production]:
        return [item for item in self.list(status="active") if item.is_ready_for_rehearsal()]

    def by_venue(self, venue_id: str) -> list[Production]:
        return [item for item in self.list() if item.venue_id == venue_id]
