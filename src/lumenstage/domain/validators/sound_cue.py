"""Validation rules for audio cues."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import (
    FieldRule,
    require_non_negative,
    require_positive,
    validate_record_with,
)

SCHEMA = (
    FieldRule("cue_number", int),
    FieldRule("trigger", str, allow_blank=False),
    FieldRule("asset_id", str, allow_blank=False),
    FieldRule("duration_ms", int),
    FieldRule("level_db", (int, float)),
    FieldRule("ready", bool),
)


def validate_audio(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = require_positive(metadata, "cue_number")
    issues.extend(require_non_negative(metadata, "duration_ms"))
    level = metadata.get("level_db")
    if isinstance(level, int | float) and not isinstance(level, bool) and not -80 <= level <= 12:
        issues.append("metadata.level_db must be between -80 and 12")
    if metadata.get("ready"):
        for key in ("cue_number", "trigger", "asset_id"):
            if not metadata.get(key):
                issues.append(f"ready sound cues require metadata.{key}")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_audio)
