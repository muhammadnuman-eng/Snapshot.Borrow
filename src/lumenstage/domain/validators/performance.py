"""Validation rules for performance records."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import (
    FieldRule,
    require_non_negative,
    validate_iso_fields,
    validate_record_with,
)

SCHEMA = (
    FieldRule("production_id", str, allow_blank=False),
    FieldRule("starts_at", str),
    FieldRule("capacity", int),
    FieldRule("sold", int),
    FieldRule("held", int),
)


def validate_capacity(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = require_non_negative(metadata, "capacity", "sold", "held")
    capacity = metadata.get("capacity", 0)
    sold = metadata.get("sold", 0)
    held = metadata.get("held", 0)
    if (
        all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (capacity, sold, held)
        )
        and capacity
        and sold + held > capacity
    ):
        issues.append("metadata.sold and metadata.held exceed metadata.capacity")
    issues.extend(validate_iso_fields(metadata, "starts_at"))
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_capacity)
