"""Application service for cast and crew members."""

from __future__ import annotations

from datetime import datetime

from lumenstage.models.cast_member import CastMember
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class CastMemberService(EntityService[CastMember]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, CastMember, "cast_members", "cast member")

    def available_between(self, start: datetime, end: datetime) -> list[CastMember]:
        return [item for item in self.list(status="active") if item.is_available(start, end)]

    def assigned_to_role(self, role: str) -> list[CastMember]:
        return [item for item in self.list(status="active") if role in item.roles]

    def assign_role(self, cast_member_id: str, role: str) -> CastMember:
        member = self.get(cast_member_id)
        member.assign_role(role)
        return self.repo.save(member)
