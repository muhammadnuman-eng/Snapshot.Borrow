"""A production department and its assigned members."""

from __future__ import annotations

from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity


class Department(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "DPT"
    LABEL: ClassVar[str] = "Department"

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        members = metadata.get("member_ids", [])
        if not isinstance(members, list):
            raise ValidationError("metadata.member_ids must be a list")
        if len(members) != len(set(str(item) for item in members)):
            raise ValidationError("department member_ids must be unique")
        head = str(metadata.get("head_id", ""))
        if head and head not in {str(item) for item in members}:
            raise ValidationError("department head must also be a member")

    @property
    def head_id(self) -> str:
        return self.metadata_text("head_id")

    @property
    def member_ids(self) -> list[str]:
        return self.metadata_list("member_ids")

    def add_member(self, member_id: str, *, as_head: bool = False) -> None:
        normalized = member_id.strip()
        if not normalized:
            raise ValidationError("member_id is required")
        members = [*self.member_ids]
        if normalized not in members:
            members.append(normalized)
        changes: dict[str, Any] = {"member_ids": members}
        if as_head:
            changes["head_id"] = normalized
        self.merge_metadata(changes)

    def remove_member(self, member_id: str) -> bool:
        if member_id not in self.member_ids:
            return False
        changes: dict[str, Any] = {
            "member_ids": [item for item in self.member_ids if item != member_id]
        }
        if self.head_id == member_id:
            changes["head_id"] = ""
        self.merge_metadata(changes)
        return True

    def has_member(self, member_id: str) -> bool:
        return member_id in self.member_ids
