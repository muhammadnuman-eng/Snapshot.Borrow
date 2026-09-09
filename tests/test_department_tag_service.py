"""Tests for department_tag service."""

from __future__ import annotations

from pathlib import Path

import pytest

from lumenstage.errors import NotFoundError, ValidationError
from lumenstage.services.department_tag import DepartmentTagService
from lumenstage.storage.store import JsonDocumentStore


@pytest.fixture()
def service(tmp_path: Path) -> DepartmentTagService:
    return DepartmentTagService(JsonDocumentStore(tmp_path / "store.json"))


def test_create_and_get(service: DepartmentTagService) -> None:
    item = service.create("DepartmentTag", "department_tag", tags=["core"])
    loaded = service.get(item.id)
    assert loaded.name == "DepartmentTag"
    assert loaded.slug == "department-tag"
    assert "core" in loaded.tags


def test_duplicate_slug_rejected(service: DepartmentTagService) -> None:
    service.create("Alpha", "dup")
    with pytest.raises(ValidationError):
        service.create("Beta", "dup")


def test_list_filters(service: DepartmentTagService) -> None:
    a = service.create("North DepartmentTag", "north")
    service.create("South DepartmentTag", "south", tags=["remote"])
    service.update(a.id, status="inactive")
    assert len(service.list(query="south")) == 1
    assert len(service.list(status="inactive")) == 1


def test_update_metadata_and_notes(service: DepartmentTagService) -> None:
    item = service.create("Tools", "tools")
    updated = service.update(item.id, metadata={"zone": "A"}, note="checked")
    assert updated.metadata["zone"] == "A"
    assert updated.notes == ["checked"]
    assert updated.version >= 2


def test_delete(service: DepartmentTagService) -> None:
    item = service.create("Temp", "temp")
    service.delete(item.id)
    with pytest.raises(NotFoundError):
        service.get(item.id)


def test_summary_and_archive_flags(service: DepartmentTagService) -> None:
    item = service.create("Summary Check", "summary-check", tags=["a", "b"])
    assert "Summary Check" in item.summary_line()
    service.update(item.id, status="archived")
    loaded = service.get(item.id)
    assert loaded.is_archived()
