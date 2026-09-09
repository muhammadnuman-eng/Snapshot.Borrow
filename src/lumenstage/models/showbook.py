"""The controlled production bible used by every department."""

from __future__ import annotations

from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity, require_non_negative_int


class Showbook(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "SHB"
    LABEL: ClassVar[str] = "Showbook"

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        sections = metadata.get("sections", [])
        if not isinstance(sections, list):
            raise ValidationError("metadata.sections must be a list")
        require_non_negative_int(metadata.get("revision", 0), "metadata.revision")
        if not isinstance(metadata.get("locked", False), bool):
            raise ValidationError("metadata.locked must be a boolean")

    @property
    def sections(self) -> list[str]:
        return self.metadata_list("sections")

    @property
    def revision(self) -> int:
        return self.metadata_int("revision")

    @property
    def locked(self) -> bool:
        return bool(self.metadata.get("locked", False))

    def add_section(self, section: str) -> None:
        if self.locked:
            raise ValidationError("showbook is locked")
        normalized = section.strip()
        if not normalized:
            raise ValidationError("section is required")
        if normalized in self.sections:
            raise ValidationError(f"duplicate section: {normalized}")
        self.merge_metadata(
            {"sections": [*self.sections, normalized], "revision": self.revision + 1}
        )

    def lock(self) -> None:
        self.merge_metadata({"locked": True})

    def unlock(self) -> None:
        self.merge_metadata({"locked": False})
