"""Shared persistence behavior for LumenStage catalog entities."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Self

from lumenstage.errors import ValidationError
from lumenstage.utils.ids import generate_id
from lumenstage.utils.slugify import slugify
from lumenstage.utils.timeutil import parse_iso, to_iso, utc_now


def require_text(value: object, label: str) -> str:
    """Return a trimmed string or raise a domain validation error."""
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} is required")
    return value.strip()


def require_non_negative_int(value: object, label: str) -> int:
    """Validate integer counters without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(f"{label} must be a non-negative int")
    return value


@dataclass(slots=True)
class CatalogEntity:
    """Base record used by the JSON-backed LumenStage services.

    Specialized entities keep their domain payload in ``metadata`` while this
    class owns identity, lifecycle, serialization, search, and audit fields.
    """

    ID_PREFIX: ClassVar[str] = "ENT"
    LABEL: ClassVar[str] = "Entity"
    ALLOWED_STATUSES: ClassVar[frozenset[str]] = frozenset({"active", "inactive", "archived"})

    id: str
    name: str
    slug: str
    status: str = "active"
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    version: int = 1

    @classmethod
    def create(
        cls,
        name: str,
        slug: str,
        *,
        tags: Iterable[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Self:
        now = utc_now()
        payload = dict(metadata or {})
        cls.validate_metadata(payload)
        return cls(
            id=generate_id(cls.ID_PREFIX),
            name=require_text(name, "name"),
            slug=slugify(require_text(slug, "slug")),
            tags=cls.normalize_tags(tags or []),
            created_at=now,
            updated_at=now,
            metadata=payload,
        )

    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> None:
        """Hook for specialized entities to validate their metadata."""
        if not isinstance(metadata, dict):
            raise ValidationError("metadata must be an object")

    @staticmethod
    def normalize_tags(tags: Iterable[str]) -> list[str]:
        return sorted({require_text(tag, "tag").lower() for tag in tags})

    def rename(self, name: str) -> None:
        self.name = require_text(name, "name")
        self.touch()

    def set_status(self, status: str) -> None:
        normalized = require_text(status, "status").lower()
        if normalized not in self.ALLOWED_STATUSES:
            raise ValidationError(f"invalid status: {normalized}")
        self.status = normalized
        self.touch()

    def add_tag(self, tag: str) -> None:
        normalized = require_text(tag, "tag").lower()
        if normalized not in self.tags:
            self.tags = sorted([*self.tags, normalized])
            self.touch()

    def remove_tag(self, tag: str) -> bool:
        normalized = tag.strip().lower()
        if normalized not in self.tags:
            return False
        self.tags = [item for item in self.tags if item != normalized]
        self.touch()
        return True

    def add_note(self, note: str) -> None:
        self.notes.append(require_text(note, "note"))
        self.touch()

    def merge_metadata(self, values: dict[str, Any]) -> None:
        if not isinstance(values, dict):
            raise ValidationError("metadata must be an object")
        merged = {**self.metadata, **values}
        self.validate_metadata(merged)
        self.metadata = merged
        self.touch()

    def replace_metadata(self, values: dict[str, Any]) -> None:
        if not isinstance(values, dict):
            raise ValidationError("metadata must be an object")
        self.validate_metadata(values)
        self.metadata = dict(values)
        self.touch()

    def touch(self) -> None:
        self.updated_at = utc_now()
        self.version += 1

    def matches(self, query: str) -> bool:
        normalized = query.strip().lower()
        if not normalized:
            return True
        searchable = " ".join(
            [self.name, self.slug, self.status, *self.tags, str(self.metadata), *self.notes]
        ).lower()
        return normalized in searchable

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "status": self.status,
            "tags": list(self.tags),
            "created_at": to_iso(self.created_at),
            "updated_at": to_iso(self.updated_at),
            "metadata": dict(self.metadata),
            "notes": list(self.notes),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        if not isinstance(data, dict):
            raise ValidationError("data must be an object")
        entity_id = require_text(data.get("id", ""), "id")
        name = require_text(data.get("name", ""), "name")
        slug = slugify(require_text(data.get("slug", ""), "slug"))
        status = require_text(data.get("status", "active"), "status").lower()
        if status not in cls.ALLOWED_STATUSES:
            raise ValidationError(f"invalid status: {status}")
        tags = data.get("tags") or []
        notes = data.get("notes") or []
        metadata = data.get("metadata") or {}
        if not isinstance(tags, list):
            raise ValidationError("tags must be a list")
        if not isinstance(notes, list):
            raise ValidationError("notes must be a list")
        if not isinstance(metadata, dict):
            raise ValidationError("metadata must be an object")
        cls.validate_metadata(metadata)
        version = require_non_negative_int(data.get("version", 1), "version")
        return cls(
            id=entity_id,
            name=name,
            slug=slug,
            status=status,
            tags=cls.normalize_tags(str(item) for item in tags),
            created_at=parse_iso(str(data["created_at"])) if data.get("created_at") else utc_now(),
            updated_at=parse_iso(str(data["updated_at"])) if data.get("updated_at") else utc_now(),
            metadata=dict(metadata),
            notes=[require_text(str(item), "note") for item in notes],
            version=version,
        )

    def summary_line(self) -> str:
        tag_text = ",".join(self.tags[:5])
        return f"{self.name} ({self.slug}) [{self.status}] tags={tag_text}"

    def is_archived(self) -> bool:
        return self.status == "archived"

    def active_tags(self) -> list[str]:
        return [tag for tag in self.tags if tag and tag != "archived"]

    def production_label(self) -> str:
        return f"{self.LABEL}: {self.name}"

    def metadata_text(self, key: str, *, default: str = "") -> str:
        value = self.metadata.get(key, default)
        return str(value).strip()

    def metadata_list(self, key: str) -> list[str]:
        value = self.metadata.get(key, [])
        if not isinstance(value, list):
            raise ValidationError(f"metadata.{key} must be a list")
        return [str(item) for item in value]

    def metadata_int(self, key: str, *, default: int = 0) -> int:
        return require_non_negative_int(self.metadata.get(key, default), f"metadata.{key}")
