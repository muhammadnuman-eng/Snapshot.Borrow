"""A performance program with sections and credited contributors."""

from __future__ import annotations

from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity


class Program(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "PGM"
    LABEL: ClassVar[str] = "Program"

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        for key in ("sections", "credits"):
            if not isinstance(metadata.get(key, []), list):
                raise ValidationError(f"metadata.{key} must be a list")
        if not isinstance(metadata.get("published", False), bool):
            raise ValidationError("metadata.published must be a boolean")

    @property
    def sections(self) -> list[str]:
        return self.metadata_list("sections")

    @property
    def credits(self) -> list[str]:
        return self.metadata_list("credits")

    @property
    def published(self) -> bool:
        return bool(self.metadata.get("published", False))

    def add_section(self, title: str) -> None:
        if self.published:
            raise ValidationError("published programs cannot be edited")
        normalized = title.strip()
        if not normalized:
            raise ValidationError("section title is required")
        self.merge_metadata({"sections": [*self.sections, normalized]})

    def add_credit(self, credit: str) -> None:
        if self.published:
            raise ValidationError("published programs cannot be edited")
        normalized = credit.strip()
        if not normalized:
            raise ValidationError("credit is required")
        if normalized not in self.credits:
            self.merge_metadata({"credits": [*self.credits, normalized]})

    def publish(self) -> None:
        if not self.sections:
            raise ValidationError("program requires at least one section")
        if not self.credits:
            raise ValidationError("program requires at least one credit")
        self.merge_metadata({"published": True})
