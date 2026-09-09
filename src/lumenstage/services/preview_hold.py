"""Application service for preview holds."""

from __future__ import annotations

from datetime import datetime

from lumenstage.models.preview_hold import PreviewHold
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class PreviewHoldService(EntityService[PreviewHold]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, PreviewHold, "preview_holds", "preview hold")

    def active_at(self, moment: datetime) -> list[PreviewHold]:
        return [hold for hold in self.list(status="active") if not hold.is_lifted(now=moment)]

    def lift(self, hold_id: str, *, reason: str = "") -> PreviewHold:
        hold = self.get(hold_id)
        hold.lift(reason=reason)
        return self.repo.save(hold)

    def extend_until(self, hold_id: str, moment: datetime) -> PreviewHold:
        hold = self.get(hold_id)
        hold.extend_until(moment)
        return self.repo.save(hold)
