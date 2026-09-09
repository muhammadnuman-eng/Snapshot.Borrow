"""Identifier helpers."""

from __future__ import annotations

import secrets
import string

_ALPHABET = string.ascii_lowercase + string.digits


def generate_id(prefix: str) -> str:
    token = "".join(secrets.choice(_ALPHABET) for _ in range(10))
    return f"{prefix.lower()}_{token}"


def is_valid_id(value: str, prefix: str | None = None) -> bool:
    if not value or "_" not in value:
        return False
    head, tail = value.split("_", 1)
    if prefix and head != prefix.lower():
        return False
    return len(tail) == 10 and tail.isalnum() and tail.islower()
