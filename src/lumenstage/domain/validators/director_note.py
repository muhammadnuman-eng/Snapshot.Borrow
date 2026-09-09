"""Validation rules for director notes."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import FieldRule, validate_record_with

SCHEMA = (
    FieldRule("priority", str, choices=frozenset({"low", "normal", "high", "urgent"})),
    FieldRule("target_type", str),
    FieldRule("target_id", str),
    FieldRule("resolved", bool),
    FieldRule("resolved_by", str),
    FieldRule("resolution", str),
)


def validate_resolution(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues: list[str] = []
    target_type = bool(metadata.get("target_type"))
    target_id = bool(metadata.get("target_id"))
    if target_type != target_id:
        issues.append("metadata.target_type and metadata.target_id must appear together")
    if metadata.get("resolved") and not metadata.get("resolved_by"):
        issues.append("resolved notes require metadata.resolved_by")
    if not metadata.get("resolved") and metadata.get("resolved_by"):
        issues.append("unresolved notes cannot have metadata.resolved_by")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_resolution)
