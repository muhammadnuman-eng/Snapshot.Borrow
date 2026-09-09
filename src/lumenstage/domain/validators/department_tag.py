"""Validation rules for controlled department tags."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import (
    FieldRule,
    require_unique_string_list,
    validate_hex_color,
    validate_record_with,
)

SCHEMA = (
    FieldRule("color", str),
    FieldRule("applies_to", list),
    FieldRule("description", str),
)


def validate_tag(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = validate_hex_color(metadata)
    issues.extend(require_unique_string_list(metadata, "applies_to"))
    applies_to = metadata.get("applies_to", [])
    if isinstance(applies_to, list) and any(
        isinstance(item, str) and item != item.strip().lower() for item in applies_to
    ):
        issues.append("metadata.applies_to values must be lowercase slugs")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_tag)
