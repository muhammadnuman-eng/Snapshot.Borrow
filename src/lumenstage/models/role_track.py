"""A role assignment with primary and understudy coverage."""

from __future__ import annotations

from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity


class RoleTrack(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "ROL"
    LABEL: ClassVar[str] = "Role track"

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        understudies = metadata.get("understudy_ids", [])
        if not isinstance(understudies, list):
            raise ValidationError("metadata.understudy_ids must be a list")
        primary = str(metadata.get("primary_cast_id", ""))
        if primary and primary in {str(item) for item in understudies}:
            raise ValidationError("primary cast member cannot also be an understudy")

    @property
    def role_name(self) -> str:
        return self.metadata_text("role_name", default=self.name)

    @property
    def primary_cast_id(self) -> str:
        return self.metadata_text("primary_cast_id")

    @property
    def understudy_ids(self) -> list[str]:
        return self.metadata_list("understudy_ids")

    def assign_primary(self, cast_member_id: str) -> None:
        normalized = cast_member_id.strip()
        if normalized in self.understudy_ids:
            raise ValidationError("understudy cannot be assigned as primary")
        self.merge_metadata({"primary_cast_id": normalized})

    def add_understudy(self, cast_member_id: str) -> None:
        normalized = cast_member_id.strip()
        if not normalized:
            raise ValidationError("cast_member_id is required")
        if normalized == self.primary_cast_id:
            raise ValidationError("primary cast member cannot be an understudy")
        self.merge_metadata({"understudy_ids": sorted({*self.understudy_ids, normalized})})

    def is_covered(self) -> bool:
        return bool(self.primary_cast_id and self.understudy_ids)
