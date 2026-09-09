"""Tests for box_office service."""

from __future__ import annotations

from pathlib import Path

import pytest

from lumenstage.errors import NotFoundError, ValidationError
from lumenstage.services.box_office import BoxOfficeService
from lumenstage.storage.store import JsonDocumentStore


@pytest.fixture()
def service(tmp_path: Path) -> BoxOfficeService:
    return BoxOfficeService(JsonDocumentStore(tmp_path / "store.json"))


def test_create_and_get(service: BoxOfficeService) -> None:
    item = service.create("BoxOffice", "box_office", tags=["core"])
    loaded = service.get(item.id)
    assert loaded.name == "BoxOffice"
    assert loaded.slug == "box-office"
    assert "core" in loaded.tags


def test_duplicate_slug_rejected(service: BoxOfficeService) -> None:
    service.create("Alpha", "dup")
    with pytest.raises(ValidationError):
        service.create("Beta", "dup")


def test_list_filters(service: BoxOfficeService) -> None:
    a = service.create("North BoxOffice", "north")
    service.create("South BoxOffice", "south", tags=["remote"])
    service.update(a.id, status="inactive")
    assert len(service.list(query="south")) == 1
    assert len(service.list(status="inactive")) == 1


def test_update_metadata_and_notes(service: BoxOfficeService) -> None:
    item = service.create("Tools", "tools")
    updated = service.update(item.id, metadata={"zone": "A"}, note="checked")
    assert updated.metadata["zone"] == "A"
    assert updated.notes == ["checked"]
    assert updated.version >= 2


def test_delete(service: BoxOfficeService) -> None:
    item = service.create("Temp", "temp")
    service.delete(item.id)
    with pytest.raises(NotFoundError):
        service.get(item.id)


def test_summary_and_archive_flags(service: BoxOfficeService) -> None:
    item = service.create("Summary Check", "summary-check", tags=["a", "b"])
    assert "Summary Check" in item.summary_line()
    service.update(item.id, status="archived")
    loaded = service.get(item.id)
    assert loaded.is_archived()
