"""Application service for scheduled performances."""

from __future__ import annotations

from lumenstage.models.performance import Performance
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class PerformanceService(EntityService[Performance]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, Performance, "performances", "performance")

    def record_sales(self, performance_id: str, quantity: int) -> Performance:
        performance = self.get(performance_id)
        performance.record_sales(quantity)
        return self.repo.save(performance)

    def by_production(self, production_id: str) -> list[Performance]:
        return [item for item in self.list() if item.production_id == production_id]

    def with_availability(self) -> list[Performance]:
        return [item for item in self.list(status="active") if item.available_seats() > 0]
