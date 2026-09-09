"""A rehearsal booking with room and participant assignments."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity
from lumenstage.utils.timeutil import parse_iso


class RehearsalSlot(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "RHS"
    LABEL: ClassVar[str] = "Rehearsal slot"

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        participants = metadata.get("participant_ids", [])
        if not isinstance(participants, list):
            raise ValidationError("metadata.participant_ids must be a list")
        if metadata.get("starts_at") or metadata.get("ends_at"):
            if not metadata.get("starts_at") or not metadata.get("ends_at"):
                raise ValidationError("starts_at and ends_at must be supplied together")
            if parse_iso(str(metadata["ends_at"])) <= parse_iso(str(metadata["starts_at"])):
                raise ValidationError("rehearsal end must follow start")

    @property
    def room_id(self) -> str:
        return self.metadata_text("room_id")

    @property
    def participant_ids(self) -> list[str]:
        return self.metadata_list("participant_ids")

    @property
    def starts_at(self) -> datetime | None:
        value = self.metadata.get("starts_at")
        return parse_iso(str(value)) if value else None

    @property
    def ends_at(self) -> datetime | None:
        value = self.metadata.get("ends_at")
        return parse_iso(str(value)) if value else None

    def duration_minutes(self) -> int:
        if not self.starts_at or not self.ends_at:
            return 0
        return int((self.ends_at - self.starts_at).total_seconds() // 60)

    def overlaps(self, other: RehearsalSlot) -> bool:
        if not self.starts_at or not self.ends_at or not other.starts_at or not other.ends_at:
            return False
        return self.starts_at < other.ends_at and other.starts_at < self.ends_at

    def shared_participants(self, other: RehearsalSlot) -> list[str]:
        return sorted(set(self.participant_ids).intersection(other.participant_ids))
