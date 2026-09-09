"""Validation rules for production showbooks."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import (
    FieldRule,
    require_non_negative,
    require_unique_string_list,
    validate_record_with,
)

SCHEMA = (
    FieldRule("sections", list),
    FieldRule("revision", int),
    FieldRule("locked", bool),
    FieldRule("production_id", str, allow_blank=False),
)


def validate_showbook(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = require_unique_string_list(metadata, "sections")
    issues.extend(require_non_negative(metadata, "revision"))
    if metadata.get("locked") and not metadata.get("sections"):
        issues.append("locked showbooks require at least one section")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_showbook)
