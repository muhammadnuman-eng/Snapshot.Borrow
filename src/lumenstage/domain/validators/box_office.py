"""Validation rules for box-office snapshots."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import (
    FieldRule,
    require_non_negative,
    validate_decimal,
    validate_record_with,
)

SCHEMA = (
    FieldRule("performance_id", str, allow_blank=False),
    FieldRule("sold", int),
    FieldRule("refunded", int),
    FieldRule("complimentary", int),
    FieldRule("gross", (str, int, float)),
    FieldRule("currency", str),
)


def validate_snapshot(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = require_non_negative(metadata, "sold", "refunded", "complimentary")
    issues.extend(validate_decimal(metadata, "gross"))
    sold = metadata.get("sold", 0)
    refunded = metadata.get("refunded", 0)
    complimentary = metadata.get("complimentary", 0)
    if all(
        isinstance(value, int) and not isinstance(value, bool)
        for value in (sold, refunded, complimentary)
    ):
        if refunded > sold:
            issues.append("metadata.refunded cannot exceed metadata.sold")
        if complimentary > sold - refunded:
            issues.append("metadata.complimentary cannot exceed net tickets")
    currency = metadata.get("currency")
    if isinstance(currency, str) and currency and len(currency.strip()) != 3:
        issues.append("metadata.currency must be a three-letter code")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_snapshot)
