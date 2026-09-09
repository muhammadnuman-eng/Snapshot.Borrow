"""Validation rules for production records."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import (
    FieldRule,
    parsed_datetime,
    validate_iso_fields,
    validate_record_with,
)

SCHEMA = (
    FieldRule(
        "stage", str, choices=frozenset({"planning", "rehearsal", "preview", "running", "closed"})
    ),
    FieldRule("venue_id", str, allow_blank=False),
    FieldRule("director_id", str, allow_blank=False),
    FieldRule("opens_at", str),
    FieldRule("closes_at", str),
)


def validate_window(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = validate_iso_fields(metadata, "opens_at", "closes_at")
    opens = parsed_datetime(metadata, "opens_at")
    closes = parsed_datetime(metadata, "closes_at")
    if opens and closes and closes < opens:
        issues.append("metadata.closes_at must not precede metadata.opens_at")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_window)
