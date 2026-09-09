"""Validation rules for performance programs."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import (
    FieldRule,
    require_unique_string_list,
    validate_record_with,
)

SCHEMA = (
    FieldRule("sections", list),
    FieldRule("credits", list),
    FieldRule("published", bool),
    FieldRule("production_id", str),
)


def validate_publication(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = require_unique_string_list(metadata, "sections")
    issues.extend(require_unique_string_list(metadata, "credits"))
    if metadata.get("published"):
        if not metadata.get("sections"):
            issues.append("published programs require metadata.sections")
        if not metadata.get("credits"):
            issues.append("published programs require metadata.credits")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_publication)
