"""Validation rules for rehearsal bookings."""

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
    FieldRule("room_id", str, allow_blank=False),
    FieldRule("participant_ids", list),
    FieldRule("starts_at", str),
    FieldRule("ends_at", str),
    FieldRule("scene_ids", list),
)


def validate_booking(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = require_unique_string_list(metadata, "participant_ids")
    issues.extend(require_unique_string_list(metadata, "scene_ids"))
    starts_present = bool(metadata.get("starts_at"))
    ends_present = bool(metadata.get("ends_at"))
    if starts_present != ends_present:
        issues.append("metadata.starts_at and metadata.ends_at must be supplied together")
    issues.extend(validate_iso_fields(metadata, "starts_at", "ends_at"))
    starts = parsed_datetime(metadata, "starts_at")
    ends = parsed_datetime(metadata, "ends_at")
    if starts and ends and ends <= starts:
        issues.append("metadata.ends_at must follow metadata.starts_at")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_booking)
