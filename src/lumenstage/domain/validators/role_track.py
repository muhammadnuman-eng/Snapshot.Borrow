"""Validation rules for role and understudy tracks."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import (
    FieldRule,
    require_unique_string_list,
    validate_record_with,
)

SCHEMA = (
    FieldRule("role_name", str, allow_blank=False),
    FieldRule("primary_cast_id", str),
    FieldRule("understudy_ids", list),
    FieldRule("production_id", str),
)


def validate_coverage(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = require_unique_string_list(metadata, "understudy_ids")
    primary = metadata.get("primary_cast_id")
    understudies = metadata.get("understudy_ids", [])
    if primary and isinstance(understudies, list) and primary in understudies:
        issues.append("metadata.primary_cast_id cannot also be an understudy")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_coverage)
