"""Validation rules for performance licenses."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import (
    FieldRule,
    parsed_datetime,
    require_unique_string_list,
    validate_iso_fields,
    validate_record_with,
)

SCHEMA = (
    FieldRule("rightsholder", str, allow_blank=False),
    FieldRule("territories", list),
    FieldRule("valid_from", str),
    FieldRule("valid_until", str),
    FieldRule("agreement_id", str),
)


def validate_rights(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = require_unique_string_list(metadata, "territories")
    territories = metadata.get("territories", [])
    if isinstance(territories, list):
        for territory in territories:
            if isinstance(territory, str) and len(territory.strip()) not in {2, 3}:
                issues.append("metadata.territories must contain 2 or 3 letter codes")
                break
    issues.extend(validate_iso_fields(metadata, "valid_from", "valid_until"))
    starts = parsed_datetime(metadata, "valid_from")
    ends = parsed_datetime(metadata, "valid_until")
    if starts and ends and ends < starts:
        issues.append("metadata.valid_until must not precede metadata.valid_from")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_rights)
