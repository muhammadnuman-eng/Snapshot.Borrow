"""A performance-rights agreement and its licensed window."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity
from lumenstage.utils.timeutil import parse_iso


class Licensing(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "LIC"
    LABEL: ClassVar[str] = "License"

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        territories = metadata.get("territories", [])
        if not isinstance(territories, list):
            raise ValidationError("metadata.territories must be a list")
        starts = metadata.get("valid_from")
        ends = metadata.get("valid_until")
        if starts:
            parse_iso(str(starts))
        if ends:
            parse_iso(str(ends))
        if starts and ends and parse_iso(str(ends)) < parse_iso(str(starts)):
            raise ValidationError("valid_until must not precede valid_from")

    @property
    def territories(self) -> list[str]:
        return [item.upper() for item in self.metadata_list("territories")]

    @property
    def rightsholder(self) -> str:
        return self.metadata_text("rightsholder")

    def is_valid_at(self, moment: datetime) -> bool:
        starts = self.metadata.get("valid_from")
        ends = self.metadata.get("valid_until")
        return (not starts or moment >= parse_iso(str(starts))) and (
            not ends or moment <= parse_iso(str(ends))
        )

    def covers(self, territory: str, moment: datetime) -> bool:
        normalized = territory.strip().upper()
        return (
            self.status == "active" and normalized in self.territories and self.is_valid_at(moment)
        )

    def add_territory(self, territory: str) -> None:
        normalized = territory.strip().upper()
        if len(normalized) not in {2, 3}:
            raise ValidationError("territory must be a 2 or 3 letter code")
        self.merge_metadata({"territories": sorted({*self.territories, normalized})})
