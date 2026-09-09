"""Text normalization helpers."""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize_whitespace(value: str) -> str:
    return _WS.sub(" ", value.strip())


def truncate(value: str, limit: int, *, suffix: str = "...") -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - len(suffix))] + suffix


def ascii_fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")
