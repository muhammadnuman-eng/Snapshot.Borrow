"""Validation rules for staging-gate reviews."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import FieldRule, validate_record_with

SCHEMA = (
    FieldRule("stage", str, allow_blank=False),
    FieldRule("reviewer_id", str),
    FieldRule("staging_reviewer", str),
    FieldRule(
        "decision",
        str,
        choices=frozenset({"pending", "approved", "changes_requested", "rejected"}),
    ),
    FieldRule("comment", str),
)


def validate_decision(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    decision = metadata.get("decision", metadata.get("status", "pending"))
    reviewer = metadata.get("reviewer_id", metadata.get("staging_reviewer"))
    issues: list[str] = []
    if decision not in {"pending", "approved", "changes_requested", "rejected"}:
        issues.append("metadata.decision is invalid")
    if decision != "pending" and not reviewer:
        issues.append("decided staging reviews require a reviewer")
    if decision == "changes_requested" and not metadata.get("comment"):
        issues.append("changes_requested reviews require metadata.comment")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_decision)
