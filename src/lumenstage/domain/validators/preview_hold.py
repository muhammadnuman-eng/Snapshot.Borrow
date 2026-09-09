"""Validation rules for preview holds."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import FieldRule, validate_iso_fields, validate_record_with

SCHEMA = (
    FieldRule("reason", str),
    FieldRule("lift_at", str),
    FieldRule("manually_lifted", bool),
    FieldRule("lift_reason", str),
    FieldRule("production_id", str),
)


def validate_hold(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = validate_iso_fields(metadata, "lift_at")
    if metadata.get("manually_lifted") and not metadata.get("lift_reason"):
        issues.append("manually lifted holds require metadata.lift_reason")
    if metadata.get("lift_reason") and not metadata.get("manually_lifted"):
        issues.append("metadata.lift_reason requires metadata.manually_lifted")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_hold)
