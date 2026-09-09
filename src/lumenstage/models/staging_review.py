"""An approval decision at a production-readiness gate."""

from __future__ import annotations

from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity


class StagingReview(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "REV"
    LABEL: ClassVar[str] = "Staging review"
    DECISIONS: ClassVar[frozenset[str]] = frozenset(
        {"pending", "approved", "changes_requested", "rejected"}
    )

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        decision = str(metadata.get("decision", metadata.get("status", "pending")))
        if decision not in cls.DECISIONS:
            raise ValidationError(f"invalid staging-review decision: {decision}")

    @property
    def stage(self) -> str:
        return self.metadata_text("stage")

    @property
    def reviewer_id(self) -> str:
        return self.metadata_text("reviewer_id", default=self.metadata_text("staging_reviewer"))

    @property
    def decision(self) -> str:
        return self.metadata_text(
            "decision", default=self.metadata_text("status", default="pending")
        )

    @property
    def approved(self) -> bool:
        return self.decision == "approved"

    def decide(self, decision: str, *, comment: str = "") -> None:
        if decision not in self.DECISIONS - {"pending"}:
            raise ValidationError(f"invalid staging-review decision: {decision}")
        if not self.reviewer_id:
            raise ValidationError("reviewer_id is required before a decision")
        self.merge_metadata({"decision": decision, "comment": comment.strip()})

    def reset(self) -> None:
        self.merge_metadata({"decision": "pending", "comment": ""})
