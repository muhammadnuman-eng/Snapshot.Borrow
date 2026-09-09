"""Tests for licensing service."""

from __future__ import annotations

from pathlib import Path

import pytest

from lumenstage.errors import NotFoundError, ValidationError
from lumenstage.services.licensing import LicensingService
from lumenstage.storage.store import JsonDocumentStore


@pytest.fixture()
def service(tmp_path: Path) -> LicensingService:
    return LicensingService(JsonDocumentStore(tmp_path / "store.json"))


def test_create_and_get(service: LicensingService) -> None:
    item = service.create("Licensing", "licensing", tags=["core"])
    loaded = service.get(item.id)
    assert loaded.name == "Licensing"
    assert loaded.slug == "licensing"
    assert "core" in loaded.tags


def test_duplicate_slug_rejected(service: LicensingService) -> None:
    service.create("Alpha", "dup")
    with pytest.raises(ValidationError):
        service.create("Beta", "dup")


def test_list_filters(service: LicensingService) -> None:
    a = service.create("North Licensing", "north")
    service.create("South Licensing", "south", tags=["remote"])
    service.update(a.id, status="inactive")
    assert len(service.list(query="south")) == 1
    assert len(service.list(status="inactive")) == 1


def test_update_metadata_and_notes(service: LicensingService) -> None:
    item = service.create("Tools", "tools")
    updated = service.update(item.id, metadata={"zone": "A"}, note="checked")
    assert updated.metadata["zone"] == "A"
    assert updated.notes == ["checked"]
    assert updated.version >= 2


def test_delete(service: LicensingService) -> None:
    item = service.create("Temp", "temp")
    service.delete(item.id)
    with pytest.raises(NotFoundError):
        service.get(item.id)


def test_summary_and_archive_flags(service: LicensingService) -> None:
    item = service.create("Summary Check", "summary-check", tags=["a", "b"])
    assert "Summary Check" in item.summary_line()
    service.update(item.id, status="archived")
    loaded = service.get(item.id)
    assert loaded.is_archived()
