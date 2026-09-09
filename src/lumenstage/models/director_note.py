"""A director note addressed to a scene, cue, person, or department."""

from __future__ import annotations

from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity


class DirectorNote(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "DNT"
    LABEL: ClassVar[str] = "Director note"
    PRIORITIES: ClassVar[frozenset[str]] = frozenset({"low", "normal", "high", "urgent"})

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        priority = str(metadata.get("priority", "normal"))
        if priority not in cls.PRIORITIES:
            raise ValidationError(f"invalid note priority: {priority}")
        if not isinstance(metadata.get("resolved", False), bool):
            raise ValidationError("metadata.resolved must be a boolean")

    @property
    def priority(self) -> str:
        return self.metadata_text("priority", default="normal")

    @property
    def target_type(self) -> str:
        return self.metadata_text("target_type")

    @property
    def target_id(self) -> str:
        return self.metadata_text("target_id")

    @property
    def resolved(self) -> bool:
        return bool(self.metadata.get("resolved", False))

    def resolve(self, resolver_id: str, *, resolution: str = "") -> None:
        if self.resolved:
            return
        self.merge_metadata(
            {"resolved": True, "resolved_by": resolver_id.strip(), "resolution": resolution.strip()}
        )

    def reopen(self) -> None:
        if not self.resolved:
            return
        self.merge_metadata({"resolved": False, "resolved_by": "", "resolution": ""})

    def escalate(self) -> None:
        order = ["low", "normal", "high", "urgent"]
        current = order.index(self.priority)
        self.merge_metadata({"priority": order[min(current + 1, len(order) - 1)]})
