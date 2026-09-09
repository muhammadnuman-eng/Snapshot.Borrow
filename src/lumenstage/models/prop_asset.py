"""A tracked prop, costume, set piece, or technical asset."""

from __future__ import annotations

from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity


class PropAsset(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "AST"
    LABEL: ClassVar[str] = "Prop asset"
    CONDITIONS: ClassVar[frozenset[str]] = frozenset({"excellent", "good", "repair", "retired"})

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        condition = str(metadata.get("condition", "good"))
        if condition not in cls.CONDITIONS:
            raise ValidationError(f"invalid asset condition: {condition}")
        if metadata.get("checked_out_to") and not metadata.get("checked_out_at"):
            raise ValidationError("checked_out_at is required for checked-out assets")

    @property
    def condition(self) -> str:
        return self.metadata_text("condition", default="good")

    @property
    def location(self) -> str:
        return self.metadata_text("location")

    @property
    def checked_out_to(self) -> str:
        return self.metadata_text("checked_out_to")

    def set_condition(self, condition: str) -> None:
        if condition not in self.CONDITIONS:
            raise ValidationError(f"invalid asset condition: {condition}")
        self.merge_metadata({"condition": condition})

    def check_out(self, person_id: str, checked_out_at: str) -> None:
        if self.condition == "retired":
            raise ValidationError("retired assets cannot be checked out")
        if self.checked_out_to:
            raise ValidationError(f"asset already checked out to {self.checked_out_to}")
        self.merge_metadata({"checked_out_to": person_id.strip(), "checked_out_at": checked_out_at})

    def return_to(self, location: str) -> None:
        self.merge_metadata(
            {"checked_out_to": "", "checked_out_at": "", "location": location.strip()}
        )
