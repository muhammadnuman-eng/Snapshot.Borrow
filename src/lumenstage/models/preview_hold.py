"""A temporary hold preventing a production from entering preview."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity
from lumenstage.utils.timeutil import parse_iso, to_iso


class PreviewHold(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "HLD"
    LABEL: ClassVar[str] = "Preview hold"

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        if metadata.get("lift_at"):
            parse_iso(str(metadata["lift_at"]))
        if not isinstance(metadata.get("manually_lifted", False), bool):
            raise ValidationError("metadata.manually_lifted must be a boolean")

    @property
    def reason(self) -> str:
        return self.metadata_text("reason")

    @property
    def lift_at(self) -> datetime | None:
        value = self.metadata.get("lift_at")
        return parse_iso(str(value)) if value else None

    @property
    def manually_lifted(self) -> bool:
        return bool(self.metadata.get("manually_lifted", False))

    def is_lifted(self, *, now: datetime) -> bool:
        return self.manually_lifted or bool(self.lift_at and now >= self.lift_at)

    def extend_until(self, moment: datetime) -> None:
        if self.lift_at and moment <= self.lift_at:
            raise ValidationError("new lift time must be later than the current lift time")
        self.merge_metadata({"lift_at": to_iso(moment), "manually_lifted": False})

    def lift(self, *, reason: str = "") -> None:
        self.merge_metadata({"manually_lifted": True, "lift_reason": reason.strip()})
