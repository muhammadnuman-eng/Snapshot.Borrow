from pathlib import Path

from lumenstage.domain.catalog import ProductionCatalog
from lumenstage.services.role_track import RoleTrackService
from lumenstage.storage.store import JsonDocumentStore


def test_catalog_search(tmp_path: Path) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    RoleTrackService(store).create("City Hall", "city-hall", tags=["politics"])
    assert len(ProductionCatalog(store).search("city")) == 1
