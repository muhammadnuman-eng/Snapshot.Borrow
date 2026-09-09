"""A theatrical production and its readiness state."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity
from lumenstage.utils.timeutil import parse_iso


class Production(CatalogEntity):
    """Top-level production record shared by casts, schedules, and performances."""

    ID_PREFIX: ClassVar[str] = "PRD"
    LABEL: ClassVar[str] = "Production"
    ALLOWED_STAGES: ClassVar[tuple[str, ...]] = (
        "planning",
        "rehearsal",
        "preview",
        "running",
        "closed",
    )

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        stage = str(metadata.get("stage", "planning"))
        if stage not in cls.ALLOWED_STAGES:
            raise ValidationError(f"invalid production stage: {stage}")
        for key in ("opens_at", "closes_at"):
            if metadata.get(key):
                parse_iso(str(metadata[key]))
        if (
            metadata.get("opens_at")
            and metadata.get("closes_at")
            and parse_iso(str(metadata["closes_at"])) < parse_iso(str(metadata["opens_at"]))
        ):
            raise ValidationError("closes_at must not precede opens_at")

    @property
    def stage(self) -> str:
        return self.metadata_text("stage", default="planning")

    @property
    def venue_id(self) -> str:
        return self.metadata_text("venue_id")

    def set_stage(self, stage: str) -> None:
        if stage not in self.ALLOWED_STAGES:
            raise ValidationError(f"invalid production stage: {stage}")
        current_index = self.ALLOWED_STAGES.index(self.stage)
        target_index = self.ALLOWED_STAGES.index(stage)
        if target_index < current_index:
            raise ValidationError("production stage cannot move backwards")
        self.merge_metadata({"stage": stage})

    def performance_window(self) -> tuple[datetime | None, datetime | None]:
        opens = self.metadata.get("opens_at")
        closes = self.metadata.get("closes_at")
        return (
            parse_iso(str(opens)) if opens else None,
            parse_iso(str(closes)) if closes else None,
        )

    def readiness_gaps(self) -> list[str]:
        required = {
            "venue_id": "venue assignment",
            "director_id": "director assignment",
            "opens_at": "opening date",
            "closes_at": "closing date",
        }
        return [label for key, label in required.items() if not self.metadata.get(key)]

    def is_ready_for_rehearsal(self) -> bool:
        return self.status == "active" and not self.readiness_gaps()
