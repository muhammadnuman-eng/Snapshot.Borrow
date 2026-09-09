"""A controlled classification tag for production departments."""

from __future__ import annotations

import re
from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class DepartmentTag(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "TAG"
    LABEL: ClassVar[str] = "Department tag"

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        color = str(metadata.get("color", "#808080"))
        if not _COLOR.fullmatch(color):
            raise ValidationError("metadata.color must be a six-digit hex color")
        applies_to = metadata.get("applies_to", [])
        if not isinstance(applies_to, list):
            raise ValidationError("metadata.applies_to must be a list")

    @property
    def color(self) -> str:
        return self.metadata_text("color", default="#808080")

    @property
    def applicable_departments(self) -> list[str]:
        return self.metadata_list("applies_to")

    def applies_to(self, department_slug: str) -> bool:
        allowed = self.applicable_departments
        return not allowed or department_slug in allowed

    def set_color(self, color: str) -> None:
        if not _COLOR.fullmatch(color):
            raise ValidationError("color must be a six-digit hex color")
        self.merge_metadata({"color": color.lower()})

    def limit_to(self, department_slugs: list[str]) -> None:
        normalized = sorted({item.strip().lower() for item in department_slugs if item.strip()})
        self.merge_metadata({"applies_to": normalized})
