"""Application service for box-office snapshots."""

from __future__ import annotations

from decimal import Decimal

from lumenstage.models.box_office import BoxOffice
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class BoxOfficeService(EntityService[BoxOffice]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, BoxOffice, "box_office", "box office snapshot")

    def for_performance(self, performance_id: str) -> list[BoxOffice]:
        return [item for item in self.list() if item.performance_id == performance_id]

    def gross_total(self, performance_id: str | None = None) -> Decimal:
        snapshots = self.list() if performance_id is None else self.for_performance(performance_id)
        return sum((item.gross for item in snapshots), start=Decimal("0"))

    def net_tickets(self, performance_id: str | None = None) -> int:
        snapshots = self.list() if performance_id is None else self.for_performance(performance_id)
        return sum(item.net_tickets() for item in snapshots)

    def latest_for(self, performance_id: str) -> BoxOffice | None:
        snapshots = self.for_performance(performance_id)
        return max(snapshots, key=lambda item: item.created_at, default=None)
