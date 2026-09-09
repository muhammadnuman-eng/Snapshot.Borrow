"""LumenStage domain-specific tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lumenstage.domain.cue_engine import CueSheet
from lumenstage.domain.rehearsal_conflicts import (
    Booking,
    assert_no_person_conflict,
    assert_no_room_conflict,
    call_sheet_rows,
)
from lumenstage.errors import ConflictError


def test_room_and_person_conflicts():
    a = Booking(
        "1",
        "room-a",
        ["p1"],
        datetime(2026, 1, 1, 10, tzinfo=UTC),
        datetime(2026, 1, 1, 12, tzinfo=UTC),
    )
    b = Booking(
        "2",
        "room-a",
        ["p2"],
        datetime(2026, 1, 1, 11, tzinfo=UTC),
        datetime(2026, 1, 1, 13, tzinfo=UTC),
    )
    with pytest.raises(ConflictError):
        assert_no_room_conflict([a], b)
    c = Booking(
        "3",
        "room-b",
        ["p1"],
        datetime(2026, 1, 1, 11, tzinfo=UTC),
        datetime(2026, 1, 1, 13, tzinfo=UTC),
    )
    with pytest.raises(ConflictError):
        assert_no_person_conflict([a], c)


def test_cue_sheet_and_call_sheet():
    sheet = CueSheet("prod1")
    sheet.add(1, "lights", "LX1 GO")
    sheet.add(2, "sound", "SQ sting")
    assert sheet.next_number() == 3
    assert len(sheet.by_department("lights")) == 1
    day = datetime(2026, 1, 1, tzinfo=UTC)
    bookings = [
        Booking(
            "1",
            "r1",
            ["p1"],
            datetime(2026, 1, 1, 10, tzinfo=UTC),
            datetime(2026, 1, 1, 11, tzinfo=UTC),
            label="Act1",
        )
    ]
    assert call_sheet_rows(bookings, day)
