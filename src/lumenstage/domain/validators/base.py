"""Composable validation primitives for serialized LumenStage records."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from lumenstage.utils.timeutil import parse_iso

Record = dict[str, Any]
Rule = Callable[[Record], list[str]]


@dataclass(frozen=True, slots=True)
class FieldRule:
    """Describe an optional or required field in a record's metadata."""

    key: str
    expected: type | tuple[type, ...]
    required: bool = False
    allow_blank: bool = True
    choices: frozenset[Any] | None = None


def validate_common(payload: object) -> tuple[list[str], Record | None, Record | None]:
    """Validate the envelope shared by every persisted catalog entity."""
    if not isinstance(payload, dict):
        return ["payload must be an object"], None, None
    issues: list[str] = []
    name = payload.get("name")
    slug = payload.get("slug")
    tags = payload.get("tags", [])
    metadata = payload.get("metadata", {})
    if not isinstance(name, str) or not name.strip():
        issues.append("name is required")
    if not isinstance(slug, str) or not slug.strip():
        issues.append("slug is required")
    elif slug != slug.strip().lower() or " " in slug:
        issues.append("slug must be lowercase and contain no spaces")
    if not isinstance(tags, list):
        issues.append("tags must be a list")
    elif any(not isinstance(tag, str) or not tag.strip() for tag in tags):
        issues.append("tags must contain non-empty strings")
    elif len(tags) != len(set(tags)):
        issues.append("tags must be unique")
    if not isinstance(metadata, dict):
        issues.append("metadata must be an object")
        return issues, payload, None
    record = {**payload, "metadata": metadata}
    return issues, record, metadata


def validate_fields(metadata: Record, schema: tuple[FieldRule, ...]) -> list[str]:
    issues: list[str] = []
    for field in schema:
        if field.key not in metadata:
            if field.required:
                issues.append(f"metadata.{field.key} is required")
            continue
        value = metadata[field.key]
        if isinstance(value, bool) and field.expected is int:
            issues.append(f"metadata.{field.key} must be an int")
            continue
        if not isinstance(value, field.expected):
            expected = (
                field.expected.__name__
                if isinstance(field.expected, type)
                else " or ".join(item.__name__ for item in field.expected)
            )
            issues.append(f"metadata.{field.key} must be {expected}")
            continue
        if not field.allow_blank and isinstance(value, str) and not value.strip():
            issues.append(f"metadata.{field.key} must not be blank")
        if field.choices is not None and value not in field.choices:
            allowed = ", ".join(sorted(str(choice) for choice in field.choices))
            issues.append(f"metadata.{field.key} must be one of: {allowed}")
    return issues


def validate_record_with(
    payload: object,
    schema: tuple[FieldRule, ...],
    *rules: Rule,
) -> list[str]:
    issues, record, metadata = validate_common(payload)
    if record is None or metadata is None:
        return issues
    issues.extend(validate_fields(metadata, schema))
    for rule in rules:
        issues.extend(rule(record))
    return issues


def require_non_negative(metadata: Record, *keys: str) -> list[str]:
    issues: list[str] = []
    for key in keys:
        if key not in metadata:
            continue
        value = metadata[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            issues.append(f"metadata.{key} must be a non-negative int")
    return issues


def require_positive(metadata: Record, *keys: str) -> list[str]:
    issues: list[str] = []
    for key in keys:
        if key not in metadata:
            continue
        value = metadata[key]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            issues.append(f"metadata.{key} must be a positive int")
    return issues


def validate_iso_fields(metadata: Record, *keys: str) -> list[str]:
    issues: list[str] = []
    for key in keys:
        value = metadata.get(key)
        if not value:
            continue
        if not isinstance(value, str):
            issues.append(f"metadata.{key} must be an ISO datetime string")
            continue
        try:
            parse_iso(value)
        except (TypeError, ValueError):
            issues.append(f"metadata.{key} must be an ISO datetime string")
    return issues


def parsed_datetime(metadata: Record, key: str) -> datetime | None:
    value = metadata.get(key)
    if not isinstance(value, str) or not value:
        return None
    try:
        return parse_iso(value)
    except (TypeError, ValueError):
        return None


def require_unique_string_list(metadata: Record, key: str) -> list[str]:
    value = metadata.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        return [f"metadata.{key} must be a list"]
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return [f"metadata.{key} must contain non-empty strings"]
    if len(value) != len(set(value)):
        return [f"metadata.{key} must contain unique values"]
    return []


def validate_decimal(metadata: Record, key: str, *, minimum: Decimal = Decimal("0")) -> list[str]:
    if key not in metadata:
        return []
    try:
        value = Decimal(str(metadata[key]))
    except (InvalidOperation, ValueError):
        return [f"metadata.{key} must be a decimal"]
    return [] if value >= minimum else [f"metadata.{key} must be at least {minimum}"]


def validate_hex_color(metadata: Record, key: str = "color") -> list[str]:
    value = metadata.get(key)
    if value is None:
        return []
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return [f"metadata.{key} must be a six-digit hex color"]
    return []
