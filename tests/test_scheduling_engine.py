from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from lumenstage.domain.scheduling import (
    Booking,
    BookingStatus,
    ConflictKind,
    Frequency,
    RecurrenceRule,
    Resource,
    ResourceKind,
    SchedulingEngine,
    TimeRange,
)
from lumenstage.errors import ConflictError, NotFoundError, ValidationError

UTC = UTC


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=UTC)


def slot(day: int, start: int, end: int) -> TimeRange:
    return TimeRange(at(day, start), at(day, end))


@pytest.fixture()
def engine() -> SchedulingEngine:
    scheduler = SchedulingEngine(turnaround_minutes=15)
    scheduler.register_resource(
        Resource(
            "room-main", "Main Stage", ResourceKind.ROOM, capacity=300, tags=frozenset({"stage"})
        )
    )
    scheduler.register_resource(
        Resource("room-studio", "Studio", ResourceKind.ROOM, capacity=60, tags=frozenset({"piano"}))
    )
    scheduler.register_resource(Resource("piano", "Grand Piano", ResourceKind.EQUIPMENT))
    scheduler.register_resource(Resource("actor-a", "Actor A", ResourceKind.PERSON))
    scheduler.set_availability(
        "room-main", [TimeRange(at(day, 8), at(day, 22)) for day in (1, 2, 3)]
    )
    scheduler.set_availability(
        "room-studio", [TimeRange(at(day, 9), at(day, 18)) for day in (1, 2, 3)]
    )
    return scheduler


def test_time_range_rejects_invalid_endpoints() -> None:
    with pytest.raises(ValidationError, match="end must follow start"):
        TimeRange(at(1, 10), at(1, 10))
    with pytest.raises(ValidationError, match="timezone"):
        TimeRange(at(1, 10), datetime(2026, 9, 1, 11))


def test_time_range_supports_overlap_shift_expansion_and_intersection() -> None:
    first = slot(1, 10, 12)
    second = slot(1, 12, 14)
    assert not first.overlaps(second)
    assert first.overlaps(second, touching=True)
    assert first.shift(timedelta(hours=2)) == second
    expanded = first.expand(timedelta(minutes=15))
    assert expanded.start == at(1, 9, 45)
    assert expanded.end == at(1, 12, 15)
    assert expanded.intersection(second) == TimeRange(at(1, 12), at(1, 12, 15))


def test_resource_validates_capacity_rules() -> None:
    with pytest.raises(ValidationError, match="positive"):
        Resource("room", "Room", ResourceKind.ROOM, capacity=0)
    with pytest.raises(ValidationError, match="only room"):
        Resource("person", "Person", ResourceKind.PERSON, capacity=2)


def test_booking_validates_identity_and_uniqueness() -> None:
    with pytest.raises(ValidationError, match="resource_ids must be unique"):
        Booking("b1", "Read through", slot(1, 10, 11), resource_ids=("room", "room"))
    with pytest.raises(ValidationError, match="attendee_count"):
        Booking("b1", "Read through", slot(1, 10, 11), attendee_count=-1)


def test_schedule_detects_resource_and_participant_conflicts(engine: SchedulingEngine) -> None:
    engine.schedule(
        Booking(
            "b1",
            "Act one",
            slot(1, 10, 12),
            resource_ids=("room-main",),
            participant_ids=("actor-a",),
        )
    )
    candidate = Booking(
        "b2",
        "Act two",
        slot(1, 11, 13),
        resource_ids=("room-main",),
        participant_ids=("actor-a",),
    )
    conflicts = engine.find_conflicts(candidate)
    assert {conflict.kind for conflict in conflicts} == {
        ConflictKind.RESOURCE,
        ConflictKind.PARTICIPANT,
    }
    with pytest.raises(ConflictError, match="already booked"):
        engine.schedule(candidate)


def test_turnaround_buffer_blocks_nearby_bookings(engine: SchedulingEngine) -> None:
    engine.schedule(Booking("b1", "First", slot(1, 10, 11), resource_ids=("room-main",)))
    candidate = Booking(
        "b2",
        "Second",
        TimeRange(at(1, 11, 10), at(1, 12)),
        resource_ids=("room-main",),
    )
    assert engine.find_conflicts(candidate)[0].kind == ConflictKind.RESOURCE


def test_capacity_and_availability_conflicts(engine: SchedulingEngine) -> None:
    too_large = Booking(
        "large",
        "Full company",
        slot(1, 10, 11),
        resource_ids=("room-studio",),
        attendee_count=61,
    )
    assert {issue.kind for issue in engine.find_conflicts(too_large)} == {ConflictKind.CAPACITY}
    too_early = Booking(
        "early",
        "Warm up",
        slot(1, 8, 9),
        resource_ids=("room-studio",),
        attendee_count=10,
    )
    assert {issue.kind for issue in engine.find_conflicts(too_early)} == {ConflictKind.AVAILABILITY}


def test_inactive_resource_is_unavailable(engine: SchedulingEngine) -> None:
    engine.replace_resource(Resource("piano", "Grand Piano", ResourceKind.EQUIPMENT, active=False))
    candidate = Booking("music", "Music call", slot(1, 10, 11), resource_ids=("piano",))
    assert engine.find_conflicts(candidate)[0].kind == ConflictKind.AVAILABILITY


def test_unknown_resources_and_bookings_raise_not_found(engine: SchedulingEngine) -> None:
    with pytest.raises(NotFoundError, match="resource not found"):
        engine.find_conflicts(Booking("b1", "Unknown", slot(1, 10, 11), resource_ids=("x",)))
    with pytest.raises(NotFoundError, match="booking not found"):
        engine.cancel("missing")


def test_reschedule_is_atomic_when_target_conflicts(engine: SchedulingEngine) -> None:
    original = engine.schedule(Booking("b1", "First", slot(1, 10, 11), resource_ids=("room-main",)))
    engine.schedule(Booking("b2", "Second", slot(1, 12, 13), resource_ids=("room-main",)))
    with pytest.raises(ConflictError):
        engine.reschedule("b1", slot(1, 12, 13))
    assert engine.require_booking("b1") == original


def test_cancelled_bookings_release_resources(engine: SchedulingEngine) -> None:
    engine.schedule(Booking("b1", "First", slot(1, 10, 11), resource_ids=("room-main",)))
    cancelled = engine.cancel("b1")
    assert cancelled.status == BookingStatus.CANCELLED
    replacement = Booking("b2", "Replacement", slot(1, 10, 11), resource_ids=("room-main",))
    assert engine.find_conflicts(replacement) == []


def test_schedule_daily_series(engine: SchedulingEngine) -> None:
    template = Booking("warmup", "Company warm-up", slot(1, 9, 10), resource_ids=("room-main",))
    rule = RecurrenceRule(Frequency.DAILY, count=3)
    series = engine.schedule_series(template, rule)
    assert [booking.id for booking in series] == ["warmup-1", "warmup-2", "warmup-3"]
    assert [booking.slot.start.day for booking in series] == [1, 2, 3]


def test_schedule_series_can_skip_conflicting_occurrences(engine: SchedulingEngine) -> None:
    engine.schedule(Booking("blocked", "Blocked", slot(2, 10, 11), resource_ids=("room-main",)))
    template = Booking("series", "Series", slot(1, 10, 11), resource_ids=("room-main",))
    rule = RecurrenceRule(Frequency.DAILY, count=3)
    scheduled = engine.schedule_series(template, rule, all_or_nothing=False)
    assert [booking.slot.start.day for booking in scheduled] == [1, 3]


def test_weekly_recurrence_respects_selected_weekdays() -> None:
    monday = TimeRange(
        datetime(2026, 9, 7, 10, tzinfo=UTC),
        datetime(2026, 9, 7, 11, tzinfo=UTC),
    )
    rule = RecurrenceRule(Frequency.WEEKLY, count=4, weekdays=frozenset({0, 2}))
    occurrences = list(rule.occurrences(monday))
    assert [item.start.weekday() for item in occurrences] == [0, 2, 0, 2]


def test_recurrence_requires_a_bound() -> None:
    with pytest.raises(ValidationError, match="count or until"):
        RecurrenceRule(Frequency.DAILY)


def test_available_resources_honor_tags_capacity_and_conflicts(engine: SchedulingEngine) -> None:
    engine.schedule(Booking("busy", "Busy", slot(1, 10, 11), resource_ids=("room-main",)))
    rooms = engine.available_resources(
        ResourceKind.ROOM,
        slot(1, 10, 11),
        attendee_count=40,
        required_tags={"piano"},
    )
    assert [room.id for room in rooms] == ["room-studio"]
    assert engine.available_resources(ResourceKind.ROOM, slot(1, 10, 11), attendee_count=100) == []


def test_free_intervals_and_utilization(engine: SchedulingEngine) -> None:
    engine.schedule(Booking("b1", "Morning", slot(1, 10, 12), resource_ids=("room-main",)))
    engine.schedule(Booking("b2", "Evening", slot(1, 14, 16), resource_ids=("room-main",)))
    window = TimeRange(at(1, 8), at(1, 18))
    free = engine.free_intervals("room-main", window)
    assert free[0] == TimeRange(at(1, 8), at(1, 9, 45))
    assert free[-1] == TimeRange(at(1, 16, 15), at(1, 18))
    report = engine.utilization("room-main", window)
    assert report.available_minutes == 600
    assert report.booked_minutes == 300
    assert report.booking_count == 2
    assert report.ratio == pytest.approx(0.5)


def test_between_filters_resource_participant_and_cancelled(engine: SchedulingEngine) -> None:
    engine.schedule(
        Booking(
            "b1",
            "Scene",
            slot(1, 10, 11),
            resource_ids=("room-main",),
            participant_ids=("actor-a",),
        )
    )
    engine.schedule(Booking("b2", "Other", slot(1, 12, 13), resource_ids=("room-studio",)))
    engine.cancel("b2")
    window = slot(1, 8, 18)
    assert [item.id for item in engine.between(window, participant_id="actor-a")] == ["b1"]
    assert [item.id for item in engine.between(window, resource_id="room-main")] == ["b1"]
    assert {item.id for item in engine.between(window, include_cancelled=True)} == {"b1", "b2"}


def test_daily_timeline_and_conflict_matrix(engine: SchedulingEngine) -> None:
    first = Booking(
        "b1",
        "First",
        slot(1, 10, 12),
        resource_ids=("room-main",),
        participant_ids=("actor-a",),
    )
    second = Booking(
        "b2",
        "Second",
        slot(1, 11, 13),
        resource_ids=("room-studio",),
        participant_ids=("actor-a",),
    )
    engine.schedule(first)
    engine.schedule(second, allow_conflicts=True)
    timeline = engine.daily_timeline(date(2026, 9, 1))
    assert [item.id for item in timeline["room-main"]] == ["b1"]
    assert [item.id for item in timeline["room-studio"]] == ["b2"]
    matrix = engine.conflict_matrix(slot(1, 8, 18))
    assert matrix == {"b1": {"b2"}, "b2": {"b1"}}


def test_remove_returns_booking_and_releases_identifier(engine: SchedulingEngine) -> None:
    booking = engine.schedule(Booking("b1", "One-off", slot(1, 10, 11)))
    assert engine.remove("b1") == booking
    engine.schedule(booking)
