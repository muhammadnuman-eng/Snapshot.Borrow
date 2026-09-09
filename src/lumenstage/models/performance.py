"""A scheduled public performance of a production."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity, require_non_negative_int
from lumenstage.utils.timeutil import parse_iso


class Performance(CatalogEntity):
    ID_PREFIX: ClassVar[str] = "PRF"
    LABEL: ClassVar[str] = "Performance"

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        super().validate_metadata(metadata)
        if metadata.get("starts_at"):
            parse_iso(str(metadata["starts_at"]))
        capacity = require_non_negative_int(metadata.get("capacity", 0), "metadata.capacity")
        sold = require_non_negative_int(metadata.get("sold", 0), "metadata.sold")
        held = require_non_negative_int(metadata.get("held", 0), "metadata.held")
        if sold + held > capacity and capacity:
            raise ValidationError("sold and held seats exceed capacity")

    @property
    def production_id(self) -> str:
        return self.metadata_text("production_id")

    @property
    def starts_at(self) -> datetime | None:
        value = self.metadata.get("starts_at")
        return parse_iso(str(value)) if value else None

    @property
    def capacity(self) -> int:
        return self.metadata_int("capacity")

    @property
    def sold(self) -> int:
        return self.metadata_int("sold")

    @property
    def held(self) -> int:
        return self.metadata_int("held")

    def available_seats(self) -> int:
        return max(0, self.capacity - self.sold - self.held)

    def occupancy_rate(self) -> float:
        return 0.0 if self.capacity == 0 else self.sold / self.capacity

    def record_sales(self, quantity: int) -> None:
        quantity = require_non_negative_int(quantity, "quantity")
        if quantity > self.available_seats():
            raise ValidationError("not enough available seats")
        self.merge_metadata({"sold": self.sold + quantity})
