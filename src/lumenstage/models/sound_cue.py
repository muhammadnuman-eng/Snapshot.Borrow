"""A numbered audio cue in a production cue stack."""

from __future__ import annotations

from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity, require_non_negative_int


class SoundCue(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "SND"
    LABEL: ClassVar[str] = "Sound cue"

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        number = require_non_negative_int(metadata.get("cue_number", 0), "metadata.cue_number")
        duration = require_non_negative_int(metadata.get("duration_ms", 0), "metadata.duration_ms")
        level = metadata.get("level_db", 0)
        if isinstance(level, bool) or not isinstance(level, int | float):
            raise ValidationError("metadata.level_db must be numeric")
        if "cue_number" in metadata and number == 0:
            raise ValidationError("cue_number must be positive")
        if duration > 86_400_000:
            raise ValidationError("duration_ms exceeds 24 hours")

    @property
    def cue_number(self) -> int:
        return self.metadata_int("cue_number")

    @property
    def trigger(self) -> str:
        return self.metadata_text("trigger")

    @property
    def asset_id(self) -> str:
        return self.metadata_text("asset_id")

    @property
    def ready(self) -> bool:
        return bool(self.metadata.get("ready", False))

    def mark_ready(self) -> None:
        if not self.trigger:
            raise ValidationError("sound cue requires a trigger")
        if not self.asset_id:
            raise ValidationError("sound cue requires an asset_id")
        self.merge_metadata({"ready": True})

    def set_level(self, decibels: float) -> None:
        if decibels < -80 or decibels > 12:
            raise ValidationError("level_db must be between -80 and 12")
        self.merge_metadata({"level_db": float(decibels)})
