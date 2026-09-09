"""Application service for production departments."""

from __future__ import annotations

from lumenstage.models.department import Department
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class DepartmentService(EntityService[Department]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, Department, "departments", "department")

    def add_member(
        self, department_id: str, member_id: str, *, as_head: bool = False
    ) -> Department:
        department = self.get(department_id)
        department.add_member(member_id, as_head=as_head)
        return self.repo.save(department)

    def for_member(self, member_id: str) -> list[Department]:
        return [department for department in self.list() if department.has_member(member_id)]

    def without_heads(self) -> list[Department]:
        return [department for department in self.list(status="active") if not department.head_id]
