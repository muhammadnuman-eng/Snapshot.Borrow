"""Validation rules for props and technical assets."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import FieldRule, validate_iso_fields, validate_record_with

SCHEMA = (
    FieldRule("condition", str, choices=frozenset({"excellent", "good", "repair", "retired"})),
    FieldRule("location", str),
    FieldRule("checked_out_to", str),
    FieldRule("checked_out_at", str),
    FieldRule("replacement_cost", (int, float)),
)


def validate_checkout(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = validate_iso_fields(metadata, "checked_out_at")
    assignee = bool(metadata.get("checked_out_to"))
    timestamp = bool(metadata.get("checked_out_at"))
    if assignee != timestamp:
        issues.append("metadata.checked_out_to and metadata.checked_out_at must appear together")
    cost = metadata.get("replacement_cost")
    if isinstance(cost, int | float) and not isinstance(cost, bool) and cost < 0:
        issues.append("metadata.replacement_cost must be non-negative")
    if metadata.get("condition") == "retired" and assignee:
        issues.append("retired assets cannot be checked out")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_checkout)
