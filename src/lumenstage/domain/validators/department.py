"""Validation rules for production departments."""

from __future__ import annotations

from typing import Any

from lumenstage.domain.validators.base import (
    FieldRule,
    require_unique_string_list,
    validate_record_with,
)

SCHEMA = (
    FieldRule("head_id", str),
    FieldRule("member_ids", list),
    FieldRule("production_id", str),
    FieldRule("contact_channel", str),
)


def validate_membership(payload: dict[str, Any]) -> list[str]:
    metadata = payload["metadata"]
    issues = require_unique_string_list(metadata, "member_ids")
    members = metadata.get("member_ids", [])
    head = metadata.get("head_id")
    if head and isinstance(members, list) and head not in members:
        issues.append("metadata.head_id must also appear in metadata.member_ids")
    return issues


def validate_record(payload: object) -> list[str]:
    return validate_record_with(payload, SCHEMA, validate_membership)
