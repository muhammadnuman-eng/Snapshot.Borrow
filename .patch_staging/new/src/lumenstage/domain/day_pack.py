"""Assemble deterministic production day packs from catalog records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lumenstage.errors import ValidationError
from lumenstage.models.performance import Performance
from lumenstage.models.production import Production
from lumenstage.models.prop_asset import PropAsset
from lumenstage.models.rehearsal_slot import RehearsalSlot
from lumenstage.models.role_track import RoleTrack
from lumenstage.models.sound_cue import SoundCue
from lumenstage.utils.timeutil import to_iso

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CALL_OFFSET_MINUTES = 60


@dataclass(frozen=True, slots=True)
class DayWindow:
    date: str
    timezone: str
    start: datetime
    end: datetime


def parse_calendar_date(value: str) -> str:
    text = value.strip()
    if not _DATE_RE.fullmatch(text):
        raise ValidationError("date must use YYYY-MM-DD format")
    year, month, day = (int(part) for part in text.split("-"))
    try:
        datetime(year, month, day)
    except ValueError as exc:
        raise ValidationError("date must be a valid calendar day") from exc
    return text


def resolve_timezone_name(raw: object) -> str:
    text = str(raw or "").strip()
    if not text or text == "UTC":
        return "UTC"
    try:
        ZoneInfo(text)
    except ZoneInfoNotFoundError:
        return "UTC"
    return text


def day_window(date: str, timezone_name: str) -> DayWindow:
    parsed = parse_calendar_date(date)
    year, month, day = (int(part) for part in parsed.split("-"))
    if timezone_name == "UTC":
        start = datetime(year, month, day, tzinfo=UTC)
        end = start + timedelta(days=1)
        return DayWindow(date=parsed, timezone="UTC", start=start, end=end)
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        start = datetime(year, month, day, tzinfo=UTC)
        end = start + timedelta(days=1)
        return DayWindow(date=parsed, timezone="UTC", start=start, end=end)
    start_local = datetime(year, month, day, tzinfo=zone)
    end_local = start_local + timedelta(days=1)
    return DayWindow(
        date=parsed,
        timezone=timezone_name,
        start=start_local.astimezone(UTC),
        end=end_local.astimezone(UTC),
    )


def _in_half_open(moment: datetime, window: DayWindow) -> bool:
    return window.start <= moment < window.end


def _intersects(start: datetime, end: datetime, window: DayWindow) -> bool:
    return start < window.end and end > window.start


def _matches_production(metadata: dict[str, Any], production_id: str) -> bool:
    return str(metadata.get("production_id", "")).strip() == production_id


def _production_summary(production: Production) -> dict[str, Any]:
    return {
        "id": production.id,
        "name": production.name,
        "slug": production.slug,
        "stage": production.stage,
        "venue_id": production.venue_id,
    }


def _performance_row(performance: Performance) -> dict[str, Any]:
    return {
        "id": performance.id,
        "name": performance.name,
        "starts_at": to_iso(performance.starts_at) if performance.starts_at else "",
        "capacity": performance.capacity,
        "available_seats": performance.available_seats(),
    }


def _rehearsal_row(slot: RehearsalSlot) -> dict[str, Any]:
    return {
        "id": slot.id,
        "name": slot.name,
        "room_id": slot.room_id,
        "starts_at": to_iso(slot.starts_at) if slot.starts_at else "",
        "ends_at": to_iso(slot.ends_at) if slot.ends_at else "",
        "participant_ids": list(slot.participant_ids),
    }


def _sound_cue_row(cue: SoundCue) -> dict[str, Any]:
    return {
        "id": cue.id,
        "cue_number": cue.cue_number,
        "name": cue.name,
        "trigger": cue.trigger,
        "ready": cue.ready,
    }


def _role_track_row(track: RoleTrack) -> dict[str, Any]:
    return {
        "id": track.id,
        "role_name": track.role_name,
        "primary_cast_id": track.primary_cast_id,
        "understudy_ids": list(track.understudy_ids),
        "covered": track.is_covered(),
    }


def _prop_asset_row(asset: PropAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "name": asset.name,
        "condition": asset.condition,
        "location": asset.location,
        "checked_out_to": asset.checked_out_to,
    }


def _build_call_timeline(
    performances: list[Performance],
    role_tracks: list[RoleTrack],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordered = sorted(
        performances,
        key=lambda item: (item.starts_at or datetime.min.replace(tzinfo=UTC), item.id),
    )
    for performance in ordered:
        if performance.starts_at is None:
            continue
        call_at = performance.starts_at - timedelta(minutes=_CALL_OFFSET_MINUTES)
        for track in sorted(role_tracks, key=lambda item: (item.role_name.lower(), item.id)):
            if not track.primary_cast_id:
                continue
            rows.append(
                {
                    "performance_id": performance.id,
                    "role_name": track.role_name,
                    "cast_member_id": track.primary_cast_id,
                    "call_at": to_iso(call_at),
                    "offset_minutes": -_CALL_OFFSET_MINUTES,
                }
            )
    return rows


def _rehearsal_conflicts(slots: list[RehearsalSlot]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    ordered = sorted(
        slots, key=lambda item: (item.starts_at or datetime.min.replace(tzinfo=UTC), item.id)
    )
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            if not left.overlaps(right):
                continue
            pair = tuple(sorted((left.id, right.id)))
            if pair in seen:
                continue
            seen.add(pair)  # type: ignore[arg-type]
            if left.room_id and left.room_id == right.room_id:
                warnings.append(
                    {
                        "code": "rehearsal_conflict",
                        "message": f"Room {left.room_id} has overlapping bookings",
                        "refs": [left.id, right.id],
                    }
                )
            shared = left.shared_participants(right)
            if shared:
                warnings.append(
                    {
                        "code": "rehearsal_conflict",
                        "message": f"Participants already booked: {', '.join(shared)}",
                        "refs": [left.id, right.id],
                    }
                )
    return warnings


class DayPackAssembler:
    """Build the content sections for one production day pack."""

    def assemble(
        self,
        production: Production,
        *,
        date: str,
        performances: list[Performance],
        rehearsal_slots: list[RehearsalSlot],
        sound_cues: list[SoundCue],
        role_tracks: list[RoleTrack],
        prop_assets: list[PropAsset],
    ) -> dict[str, Any]:
        timezone_name = resolve_timezone_name(production.metadata.get("timezone"))
        window = day_window(date, timezone_name)

        day_performances = [
            item
            for item in performances
            if item.status == "active"
            and _matches_production(item.metadata, production.id)
            and item.starts_at is not None
            and _in_half_open(item.starts_at, window)
        ]
        day_performances.sort(key=lambda item: (item.starts_at, item.id))  # type: ignore[arg-type]

        day_rehearsals = [
            item
            for item in rehearsal_slots
            if item.status == "active"
            and _matches_production(item.metadata, production.id)
            and item.starts_at is not None
            and item.ends_at is not None
            and _intersects(item.starts_at, item.ends_at, window)
        ]
        day_rehearsals.sort(key=lambda item: (item.starts_at, item.id))  # type: ignore[arg-type]

        linked_sound_cues = [
            item
            for item in sound_cues
            if item.status == "active" and _matches_production(item.metadata, production.id)
        ]
        linked_sound_cues.sort(key=lambda item: (item.cue_number, item.name.lower(), item.id))

        linked_role_tracks = [
            item
            for item in role_tracks
            if item.status == "active" and _matches_production(item.metadata, production.id)
        ]
        linked_role_tracks.sort(key=lambda item: (item.role_name.lower(), item.id))

        linked_props = [
            item
            for item in prop_assets
            if item.status == "active" and _matches_production(item.metadata, production.id)
        ]
        linked_props.sort(key=lambda item: (item.name.lower(), item.id))

        gaps: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        if not day_performances and not day_rehearsals:
            gaps.append(
                {
                    "code": "empty_schedule",
                    "message": "No performances or rehearsals intersect the requested day",
                    "ref": production.id,
                }
            )

        for track in linked_role_tracks:
            if not track.primary_cast_id:
                gaps.append(
                    {
                        "code": "uncovered_role",
                        "message": f"Role {track.role_name} has no primary cast assignment",
                        "ref": track.id,
                    }
                )

        for asset in linked_props:
            if asset.checked_out_to and not asset.metadata.get("checked_out_at"):
                gaps.append(
                    {
                        "code": "invalid_prop_checkout",
                        "message": f"Prop {asset.name} is checked out without a timestamp",
                        "ref": asset.id,
                    }
                )
            if asset.condition == "repair":
                warnings.append(
                    {
                        "code": "prop_repair",
                        "message": f"Prop {asset.name} requires repair",
                        "refs": [asset.id],
                    }
                )

        for cue in linked_sound_cues:
            if not cue.ready:
                warnings.append(
                    {
                        "code": "unready_sound_cue",
                        "message": f"Sound cue {cue.cue_number} is not ready",
                        "refs": [cue.id],
                    }
                )

        warnings.extend(_rehearsal_conflicts(day_rehearsals))

        return {
            "timezone": window.timezone,
            "production": _production_summary(production),
            "performances": [_performance_row(item) for item in day_performances],
            "rehearsals": [_rehearsal_row(item) for item in day_rehearsals],
            "sound_cues": [_sound_cue_row(item) for item in linked_sound_cues],
            "role_tracks": [_role_track_row(item) for item in linked_role_tracks],
            "prop_assets": [_prop_asset_row(item) for item in linked_props],
            "call_timeline": _build_call_timeline(day_performances, linked_role_tracks),
            "gaps": gaps,
            "warnings": warnings,
        }
