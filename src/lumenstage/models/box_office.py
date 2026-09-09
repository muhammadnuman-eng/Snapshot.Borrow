"""A point-in-time ticket-sales and revenue snapshot."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity, require_non_negative_int


class BoxOffice(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "BOX"
    LABEL: ClassVar[str] = "Box office snapshot"

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        sold = require_non_negative_int(metadata.get("sold", 0), "metadata.sold")
        refunded = require_non_negative_int(metadata.get("refunded", 0), "metadata.refunded")
        complimentary = require_non_negative_int(
            metadata.get("complimentary", 0), "metadata.complimentary"
        )
        if refunded > sold:
            raise ValidationError("refunded tickets cannot exceed sold tickets")
        if complimentary > sold:
            raise ValidationError("complimentary tickets cannot exceed sold tickets")
        try:
            gross = Decimal(str(metadata.get("gross", "0")))
        except InvalidOperation as exc:
            raise ValidationError("metadata.gross must be a decimal") from exc
        if gross < 0:
            raise ValidationError("metadata.gross must be non-negative")

    @property
    def performance_id(self) -> str:
        return self.metadata_text("performance_id")

    @property
    def sold(self) -> int:
        return self.metadata_int("sold")

    @property
    def refunded(self) -> int:
        return self.metadata_int("refunded")

    @property
    def complimentary(self) -> int:
        return self.metadata_int("complimentary")

    @property
    def gross(self) -> Decimal:
        return Decimal(str(self.metadata.get("gross", "0")))

    def net_tickets(self) -> int:
        return self.sold - self.refunded

    def paid_tickets(self) -> int:
        return self.net_tickets() - self.complimentary

    def average_paid_price(self) -> Decimal:
        paid = self.paid_tickets()
        return Decimal("0") if paid <= 0 else self.gross / Decimal(paid)

    def record(self, *, sold: int, refunded: int, complimentary: int, gross: str) -> None:
        self.merge_metadata(
            {"sold": sold, "refunded": refunded, "complimentary": complimentary, "gross": gross}
        )
