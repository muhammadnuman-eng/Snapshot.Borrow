"""Application service for tracked props and technical assets."""

from __future__ import annotations

from lumenstage.models.prop_asset import PropAsset
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class PropAssetService(EntityService[PropAsset]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, PropAsset, "prop_assets", "prop asset")

    def check_out(self, asset_id: str, person_id: str, checked_out_at: str) -> PropAsset:
        asset = self.get(asset_id)
        asset.check_out(person_id, checked_out_at)
        return self.repo.save(asset)

    def return_to(self, asset_id: str, location: str) -> PropAsset:
        asset = self.get(asset_id)
        asset.return_to(location)
        return self.repo.save(asset)

    def checked_out(self) -> list[PropAsset]:
        return [asset for asset in self.list() if asset.checked_out_to]

    def requiring_repair(self) -> list[PropAsset]:
        return [asset for asset in self.list() if asset.condition == "repair"]
