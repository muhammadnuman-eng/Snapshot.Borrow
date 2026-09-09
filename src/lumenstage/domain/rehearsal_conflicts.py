"""Rehearsal room and cast conflict detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from lumenstage.errors import ConflictError, ValidationError
from lumenstage.utils.timeutil import overlaps


@dataclass(slots=True)
class Booking:
    id: str
    room_id: str
    person_ids: list[str]
    start: datetime
    end: datetime
    label: str = ""


def assert_no_room_conflict(existing: list[Booking], candidate: Booking) -> None:
    if candidate.end <= candidate.start:
        raise ValidationError("end must be after start")
    for row in existing:
        if row.id == candidate.id:
            continue
        if row.room_id != candidate.room_id:
            continue
        if overlaps(row.start, row.end, candidate.start, candidate.end):
            raise ConflictError(f"room {candidate.room_id} busy with {row.id}")


def assert_no_person_conflict(existing: list[Booking], candidate: Booking) -> None:
    people = set(candidate.person_ids)
    for row in existing:
        if row.id == candidate.id:
            continue
        if people.isdisjoint(row.person_ids):
            continue
        if overlaps(row.start, row.end, candidate.start, candidate.end):
            shared = sorted(people.intersection(row.person_ids))
            raise ConflictError(f"people already booked: {', '.join(shared)}")


def call_sheet_rows(bookings: list[Booking], day: datetime) -> list[dict[str, Any]]:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(hour=23, minute=59, second=59)
    rows = []
    for b in sorted(bookings, key=lambda x: x.start):
        if b.end < start or b.start > end:
            continue
        rows.append(
            {
                "id": b.id,
                "room_id": b.room_id,
                "label": b.label,
                "people": list(b.person_ids),
                "start": b.start.isoformat(),
                "end": b.end.isoformat(),
            }
        )
    return rows
