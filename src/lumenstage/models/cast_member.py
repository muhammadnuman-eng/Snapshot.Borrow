"""A performer or crew member attached to a production."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity
from lumenstage.utils.timeutil import parse_iso


class CastMember(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "CST"
    LABEL: ClassVar[str] = "Cast member"

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        roles = metadata.get("roles", [])
        if not isinstance(roles, list):
            raise ValidationError("metadata.roles must be a list")
        availability = metadata.get("unavailable", [])
        if not isinstance(availability, list):
            raise ValidationError("metadata.unavailable must be a list")
        for window in availability:
            if not isinstance(window, dict) or not window.get("start") or not window.get("end"):
                raise ValidationError("unavailable windows require start and end")
            if parse_iso(str(window["end"])) <= parse_iso(str(window["start"])):
                raise ValidationError("unavailable window end must follow start")

    @property
    def roles(self) -> list[str]:
        return self.metadata_list("roles")

    def assign_role(self, role: str) -> None:
        normalized = role.strip()
        if not normalized:
            raise ValidationError("role is required")
        if normalized not in self.roles:
            self.merge_metadata({"roles": [*self.roles, normalized]})

    def unassign_role(self, role: str) -> bool:
        if role not in self.roles:
            return False
        self.merge_metadata({"roles": [item for item in self.roles if item != role]})
        return True

    def is_available(self, start: datetime, end: datetime) -> bool:
        if end <= start:
            raise ValidationError("end must be after start")
        for window in self.metadata.get("unavailable", []):
            blocked_start = parse_iso(str(window["start"]))
            blocked_end = parse_iso(str(window["end"]))
            if start < blocked_end and blocked_start < end:
                return False
        return True
