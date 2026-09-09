"""Application service for controlled department tags."""

from __future__ import annotations

from lumenstage.models.department_tag import DepartmentTag
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class DepartmentTagService(EntityService[DepartmentTag]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, DepartmentTag, "department_tags", "department tag")

    def applicable_to(self, department_slug: str) -> list[DepartmentTag]:
        return [tag for tag in self.list(status="active") if tag.applies_to(department_slug)]

    def set_color(self, tag_id: str, color: str) -> DepartmentTag:
        tag = self.get(tag_id)
        tag.set_color(color)
        return self.repo.save(tag)

    def limit_to(self, tag_id: str, department_slugs: list[str]) -> DepartmentTag:
        tag = self.get(tag_id)
        tag.limit_to(department_slugs)
        return self.repo.save(tag)
