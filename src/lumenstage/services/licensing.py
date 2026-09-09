"""Application service for production licenses."""

from __future__ import annotations

from datetime import datetime

from lumenstage.models.licensing import Licensing
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class LicensingService(EntityService[Licensing]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, Licensing, "licenses", "license")

    def covering(self, territory: str, moment: datetime) -> list[Licensing]:
        return [item for item in self.list(status="active") if item.covers(territory, moment)]

    def expired_at(self, moment: datetime) -> list[Licensing]:
        return [item for item in self.list() if not item.is_valid_at(moment)]

    def add_territory(self, license_id: str, territory: str) -> Licensing:
        license_record = self.get(license_id)
        license_record.add_territory(territory)
        return self.repo.save(license_record)
