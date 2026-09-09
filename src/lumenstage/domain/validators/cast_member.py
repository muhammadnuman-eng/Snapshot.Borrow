"""Validation rules for cast and crew records."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import (
    FieldRule,
    require_unique_string_list,
    validate_record_with,
)
from lumenstage.utils.timeutil import parse_iso

SCHEMA = (
    FieldRule("roles", list),
    FieldRule("unavailable", list),
    FieldRule("email", str),
    FieldRule("phone", str),
)


def validate_availability(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = require_unique_string_list(metadata, "roles")
    windows = metadata.get("unavailable", [])
    if not isinstance(windows, list):
        return [*issues, "metadata.unavailable must be a list"]
    for index, window in enumerate(windows):
        if not isinstance(window, dict) or not window.get("start") or not window.get("end"):
            issues.append(f"metadata.unavailable[{index}] requires start and end")
            continue
        try:
            if parse_iso(str(window["end"])) <= parse_iso(str(window["start"])):
                issues.append(f"metadata.unavailable[{index}] end must follow start")
        except (TypeError, ValueError):
            issues.append(f"metadata.unavailable[{index}] must contain ISO datetimes")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_availability)
