"""Persisted production day pack snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Self

from lumenstage.errors import ConflictError, ValidationError
from lumenstage.models.base import require_non_negative_int, require_text
from lumenstage.utils.ids import generate_id
from lumenstage.utils.timeutil import parse_iso, to_iso, utc_now


@dataclass(slots=True)
class DayPack:
    """Versioned operational snapshot for one production on one calendar day."""

    ID_PREFIX: ClassVar[str] = "DPK"
    ALLOWED_STATUSES: ClassVar[frozenset[str]] = frozenset({"draft", "published"})

    id: str
    production_id: str
    date: str
    timezone: str
    status: str = "draft"
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    published_at: datetime | None = None
    production: dict[str, Any] = field(default_factory=dict)
    performances: list[dict[str, Any]] = field(default_factory=list)
    rehearsals: list[dict[str, Any]] = field(default_factory=list)
    sound_cues: list[dict[str, Any]] = field(default_factory=list)
    role_tracks: list[dict[str, Any]] = field(default_factory=list)
    prop_assets: list[dict[str, Any]] = field(default_factory=list)
    call_timeline: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        production_id: str,
        date: str,
        timezone: str,
        *,
        snapshot: dict[str, Any],
    ) -> Self:
        now = utc_now()
        payload = dict(snapshot)
        payload.setdefault("timezone", require_text(timezone, "timezone"))
        return cls(
            id=generate_id(cls.ID_PREFIX),
            production_id=require_text(production_id, "production_id"),
            date=require_text(date, "date"),
            created_at=now,
            updated_at=now,
            **payload,
        )

    def apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        if self.status == "published":
            raise ConflictError("published day packs cannot be modified")
        for key in (
            "production",
            "performances",
            "rehearsals",
            "sound_cues",
            "role_tracks",
            "prop_assets",
            "call_timeline",
            "gaps",
            "warnings",
            "timezone",
        ):
            if key in snapshot:
                setattr(self, key, snapshot[key])
        self.version += 1
        self.updated_at = utc_now()

    def publish(self) -> None:
        if self.status == "published":
            raise ConflictError("day pack is already published")
        self.status = "published"
        self.published_at = utc_now()
        self.updated_at = self.published_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "production_id": self.production_id,
            "date": self.date,
            "timezone": self.timezone,
            "status": self.status,
            "version": self.version,
            "created_at": to_iso(self.created_at),
            "updated_at": to_iso(self.updated_at),
            "published_at": to_iso(self.published_at) if self.published_at else None,
            "production": dict(self.production),
            "performances": [dict(item) for item in self.performances],
            "rehearsals": [dict(item) for item in self.rehearsals],
            "sound_cues": [dict(item) for item in self.sound_cues],
            "role_tracks": [dict(item) for item in self.role_tracks],
            "prop_assets": [dict(item) for item in self.prop_assets],
            "call_timeline": [dict(item) for item in self.call_timeline],
            "gaps": [dict(item) for item in self.gaps],
            "warnings": [dict(item) for item in self.warnings],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        if not isinstance(data, dict):
            raise ValidationError("day pack data must be an object")
        status = require_text(data.get("status", "draft"), "status").lower()
        if status not in cls.ALLOWED_STATUSES:
            raise ValidationError(f"invalid day pack status: {status}")
        published_raw = data.get("published_at")
        return cls(
            id=require_text(data.get("id", ""), "id"),
            production_id=require_text(data.get("production_id", ""), "production_id"),
            date=require_text(data.get("date", ""), "date"),
            timezone=require_text(data.get("timezone", "UTC"), "timezone"),
            status=status,
            version=require_non_negative_int(data.get("version", 1), "version"),
            created_at=parse_iso(str(data["created_at"])) if data.get("created_at") else utc_now(),
            updated_at=parse_iso(str(data["updated_at"])) if data.get("updated_at") else utc_now(),
            published_at=parse_iso(str(published_raw)) if published_raw else None,
            production=dict(data.get("production") or {}),
            performances=[dict(item) for item in data.get("performances") or []],
            rehearsals=[dict(item) for item in data.get("rehearsals") or []],
            sound_cues=[dict(item) for item in data.get("sound_cues") or []],
            role_tracks=[dict(item) for item in data.get("role_tracks") or []],
            prop_assets=[dict(item) for item in data.get("prop_assets") or []],
            call_timeline=[dict(item) for item in data.get("call_timeline") or []],
            gaps=[dict(item) for item in data.get("gaps") or []],
            warnings=[dict(item) for item in data.get("warnings") or []],
        )
