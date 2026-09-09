"""Slug generation."""

from __future__ import annotations

import re

from lumenstage.utils.text import ascii_fold, normalize_whitespace

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    folded = ascii_fold(normalize_whitespace(value)).lower()
    slug = _NON_SLUG.sub("-", folded).strip("-")
    return slug or "item"
