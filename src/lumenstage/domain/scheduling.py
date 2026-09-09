"""Resource-aware rehearsal and performance scheduling."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Any

from lumenstage.errors import ConflictError, NotFoundError, ValidationError


class ResourceKind(StrEnum):
    ROOM = "room"
    PERSON = "person"
    EQUIPMENT = "equipment"


class BookingStatus(StrEnum):
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class ConflictKind(StrEnum):
    RESOURCE = "resource"
    PARTICIPANT = "participant"
    AVAILABILITY = "availability"
    CAPACITY = "capacity"


class Frequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


@dataclass(frozen=True, slots=True, order=True)
class TimeRange:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if (self.start.tzinfo is None) != (self.end.tzinfo is None):
            raise ValidationError("time range endpoints must use compatible timezone awareness")
        if self.end <= self.start:
            raise ValidationError("time range end must follow start")

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    @property
    def duration_minutes(self) -> int:
        return int(self.duration.total_seconds() // 60)

    def overlaps(self, other: TimeRange, *, touching: bool = False) -> bool:
        if touching:
            return self.start <= other.end and other.start <= self.end
        return self.start < other.end and other.start < self.end

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def contains_range(self, other: TimeRange) -> bool:
        return self.start <= other.start and other.end <= self.end

    def shift(self, delta: timedelta) -> TimeRange:
        return TimeRange(self.start + delta, self.end + delta)

    def expand(self, before: timedelta, after: timedelta | None = None) -> TimeRange:
        following = before if after is None else after
        return TimeRange(self.start - before, self.end + following)

    def intersection(self, other: TimeRange) -> TimeRange | None:
        start = max(self.start, other.start)
        end = min(self.end, other.end)
        return None if end <= start else TimeRange(start, end)


@dataclass(frozen=True, slots=True)
class Resource:
    id: str
    name: str
    kind: ResourceKind
    capacity: int = 1
    tags: frozenset[str] = frozenset()
    active: bool = True

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise ValidationError("resource id and name are required")
        if isinstance(self.capacity, bool) or self.capacity < 1:
            raise ValidationError("resource capacity must be a positive integer")
        if self.kind != ResourceKind.ROOM and self.capacity != 1:
            raise ValidationError("only room resources may have capacity above one")


@dataclass(frozen=True, slots=True)
class Booking:
    id: str
    label: str
    slot: TimeRange
    resource_ids: tuple[str, ...] = ()
    participant_ids: tuple[str, ...] = ()
    attendee_count: int = 0
    status: BookingStatus = BookingStatus.TENTATIVE
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.label.strip():
            raise ValidationError("booking id and label are required")
        if len(self.resource_ids) != len(set(self.resource_ids)):
            raise ValidationError("booking resource_ids must be unique")
        if len(self.participant_ids) != len(set(self.participant_ids)):
            raise ValidationError("booking participant_ids must be unique")
        if isinstance(self.attendee_count, bool) or self.attendee_count < 0:
            raise ValidationError("attendee_count must be a non-negative integer")

    @property
    def active(self) -> bool:
        return self.status != BookingStatus.CANCELLED


@dataclass(frozen=True, slots=True)
class SchedulingConflict:
    kind: ConflictKind
    message: str
    booking_id: str | None = None
    resource_id: str | None = None
    participant_id: str | None = None


@dataclass(frozen=True, slots=True)
class RecurrenceRule:
    frequency: Frequency
    interval: int = 1
    count: int | None = None
    until: datetime | None = None
    weekdays: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if isinstance(self.interval, bool) or self.interval < 1:
            raise ValidationError("recurrence interval must be a positive integer")
        if self.count is not None and (
            isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 1
        ):
            raise ValidationError("recurrence count must be a positive integer")
        if self.count is None and self.until is None:
            raise ValidationError("recurrence requires count or until")
        if any(day < 0 or day > 6 for day in self.weekdays):
            raise ValidationError("recurrence weekdays must be between 0 and 6")

    def occurrences(self, initial: TimeRange) -> Iterator[TimeRange]:
        yielded = 0
        cursor = initial
        while self.count is None or yielded < self.count:
            if self.until is not None and cursor.start > self.until:
                break
            if not self.weekdays or cursor.start.weekday() in self.weekdays:
                yield cursor
                yielded += 1
            if self.frequency == Frequency.DAILY:
                cursor = cursor.shift(timedelta(days=self.interval))
            else:
                step = timedelta(days=1 if self.weekdays else 7 * self.interval)
                cursor = cursor.shift(step)
                if self.weekdays and cursor.start.weekday() == min(self.weekdays):
                    cursor = cursor.shift(timedelta(weeks=self.interval - 1))


@dataclass(slots=True)
class UtilizationReport:
    resource_id: str
    window: TimeRange
    booked_minutes: int
    available_minutes: int
    booking_count: int

    @property
    def ratio(self) -> float:
        if self.available_minutes <= 0:
            return 0.0
        return min(1.0, self.booked_minutes / self.available_minutes)


class SchedulingEngine:
    """Coordinate resources and participants with deterministic conflict checks."""

    def __init__(self, *, turnaround_minutes: int = 0) -> None:
        if isinstance(turnaround_minutes, bool) or turnaround_minutes < 0:
            raise ValidationError("turnaround_minutes must be non-negative")
        self.turnaround = timedelta(minutes=turnaround_minutes)
        self.resources: dict[str, Resource] = {}
        self.bookings: dict[str, Booking] = {}
        self.availability: dict[str, list[TimeRange]] = defaultdict(list)

    def register_resource(self, resource: Resource) -> None:
        if resource.id in self.resources:
            raise ConflictError(f"resource already exists: {resource.id}")
        self.resources[resource.id] = resource

    def replace_resource(self, resource: Resource) -> None:
        if resource.id not in self.resources:
            raise NotFoundError(f"resource not found: {resource.id}")
        self.resources[resource.id] = resource

    def set_availability(self, resource_id: str, windows: Iterable[TimeRange]) -> None:
        self.require_resource(resource_id)
        ordered = sorted(windows)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.overlaps(current):
                raise ValidationError(f"availability windows overlap for {resource_id}")
        self.availability[resource_id] = ordered

    def add_availability(self, resource_id: str, window: TimeRange) -> None:
        self.set_availability(resource_id, [*self.availability[resource_id], window])

    def require_resource(self, resource_id: str) -> Resource:
        try:
            return self.resources[resource_id]
        except KeyError as exc:
            raise NotFoundError(f"resource not found: {resource_id}") from exc

    def require_booking(self, booking_id: str) -> Booking:
        try:
            return self.bookings[booking_id]
        except KeyError as exc:
            raise NotFoundError(f"booking not found: {booking_id}") from exc

    def find_conflicts(
        self,
        candidate: Booking,
        *,
        ignore_booking_id: str | None = None,
    ) -> list[SchedulingConflict]:
        conflicts: list[SchedulingConflict] = []
        requested_resources = [self.require_resource(item) for item in candidate.resource_ids]
        for resource in requested_resources:
            if not resource.active:
                conflicts.append(
                    SchedulingConflict(
                        ConflictKind.AVAILABILITY,
                        f"resource is inactive: {resource.name}",
                        resource_id=resource.id,
                    )
                )
                continue
            windows = self.availability.get(resource.id, [])
            if windows and not any(window.contains_range(candidate.slot) for window in windows):
                conflicts.append(
                    SchedulingConflict(
                        ConflictKind.AVAILABILITY,
                        f"resource is unavailable: {resource.name}",
                        resource_id=resource.id,
                    )
                )
            if resource.kind == ResourceKind.ROOM and candidate.attendee_count > resource.capacity:
                conflicts.append(
                    SchedulingConflict(
                        ConflictKind.CAPACITY,
                        f"{candidate.attendee_count} attendees exceed {resource.name} capacity "
                        f"of {resource.capacity}",
                        resource_id=resource.id,
                    )
                )

        occupied_slot = candidate.slot.expand(self.turnaround)
        for existing in self.bookings.values():
            if not existing.active or existing.id == ignore_booking_id:
                continue
            if not occupied_slot.overlaps(existing.slot.expand(self.turnaround)):
                continue
            shared_resources = sorted(
                set(candidate.resource_ids).intersection(existing.resource_ids)
            )
            for resource_id in shared_resources:
                conflicts.append(
                    SchedulingConflict(
                        ConflictKind.RESOURCE,
                        f"resource {resource_id} is already booked by {existing.id}",
                        booking_id=existing.id,
                        resource_id=resource_id,
                    )
                )
            shared_people = sorted(
                set(candidate.participant_ids).intersection(existing.participant_ids)
            )
            for participant_id in shared_people:
                conflicts.append(
                    SchedulingConflict(
                        ConflictKind.PARTICIPANT,
                        f"participant {participant_id} is already booked by {existing.id}",
                        booking_id=existing.id,
                        participant_id=participant_id,
                    )
                )
        return self._deduplicate_conflicts(conflicts)

    def schedule(self, booking: Booking, *, allow_conflicts: bool = False) -> Booking:
        if booking.id in self.bookings:
            raise ConflictError(f"booking already exists: {booking.id}")
        conflicts = self.find_conflicts(booking)
        if conflicts and not allow_conflicts:
            raise ConflictError("; ".join(conflict.message for conflict in conflicts))
        self.bookings[booking.id] = booking
        return booking

    def schedule_series(
        self,
        template: Booking,
        recurrence: RecurrenceRule,
        *,
        id_prefix: str | None = None,
        all_or_nothing: bool = True,
    ) -> list[Booking]:
        prefix = template.id if id_prefix is None else id_prefix
        proposed = [
            replace(template, id=f"{prefix}-{index + 1}", slot=slot)
            for index, slot in enumerate(recurrence.occurrences(template.slot))
        ]
        staged: list[Booking] = []
        for booking in proposed:
            conflicts = self.find_conflicts(booking)
            if conflicts:
                if all_or_nothing:
                    raise ConflictError("; ".join(conflict.message for conflict in conflicts))
                continue
            staged.append(booking)
        for booking in staged:
            self.bookings[booking.id] = booking
        return staged

    def reschedule(self, booking_id: str, new_slot: TimeRange) -> Booking:
        current = self.require_booking(booking_id)
        candidate = replace(current, slot=new_slot)
        conflicts = self.find_conflicts(candidate, ignore_booking_id=booking_id)
        if conflicts:
            raise ConflictError("; ".join(conflict.message for conflict in conflicts))
        self.bookings[booking_id] = candidate
        return candidate

    def set_status(self, booking_id: str, status: BookingStatus) -> Booking:
        current = self.require_booking(booking_id)
        updated = replace(current, status=status)
        self.bookings[booking_id] = updated
        return updated

    def cancel(self, booking_id: str) -> Booking:
        return self.set_status(booking_id, BookingStatus.CANCELLED)

    def remove(self, booking_id: str) -> Booking:
        booking = self.require_booking(booking_id)
        del self.bookings[booking_id]
        return booking

    def between(
        self,
        window: TimeRange,
        *,
        resource_id: str | None = None,
        participant_id: str | None = None,
        include_cancelled: bool = False,
    ) -> list[Booking]:
        result: list[Booking] = []
        for booking in self.bookings.values():
            if not include_cancelled and not booking.active:
                continue
            if not booking.slot.overlaps(window):
                continue
            if resource_id is not None and resource_id not in booking.resource_ids:
                continue
            if participant_id is not None and participant_id not in booking.participant_ids:
                continue
            result.append(booking)
        return sorted(result, key=lambda item: (item.slot.start, item.slot.end, item.id))

    def available_resources(
        self,
        kind: ResourceKind,
        slot: TimeRange,
        *,
        attendee_count: int = 0,
        required_tags: Iterable[str] = (),
    ) -> list[Resource]:
        required = set(required_tags)
        result: list[Resource] = []
        for resource in self.resources.values():
            if resource.kind != kind or not resource.active:
                continue
            if attendee_count > resource.capacity:
                continue
            if not required.issubset(resource.tags):
                continue
            probe = Booking(
                id="__availability_probe__",
                label="availability probe",
                slot=slot,
                resource_ids=(resource.id,),
                attendee_count=attendee_count,
            )
            if not self.find_conflicts(probe):
                result.append(resource)
        return sorted(result, key=lambda item: (item.capacity, item.name.lower(), item.id))

    def free_intervals(self, resource_id: str, window: TimeRange) -> list[TimeRange]:
        self.require_resource(resource_id)
        availability = self.availability.get(resource_id, [window])
        available_segments = [segment.intersection(window) for segment in availability]
        segments = [segment for segment in available_segments if segment is not None]
        occupied = [
            booking.slot.expand(self.turnaround).intersection(window)
            for booking in self.between(window, resource_id=resource_id)
        ]
        occupied = sorted(segment for segment in occupied if segment is not None)
        free: list[TimeRange] = []
        for segment in segments:
            cursor = segment.start
            for busy in occupied:
                overlap = segment.intersection(busy)
                if overlap is None:
                    continue
                if cursor < overlap.start:
                    free.append(TimeRange(cursor, overlap.start))
                cursor = max(cursor, overlap.end)
            if cursor < segment.end:
                free.append(TimeRange(cursor, segment.end))
        return free

    def utilization(self, resource_id: str, window: TimeRange) -> UtilizationReport:
        self.require_resource(resource_id)
        free = self.free_intervals(resource_id, window)
        available_windows = self.availability.get(resource_id, [window])
        available_minutes = sum(
            intersection.duration_minutes
            for segment in available_windows
            if (intersection := segment.intersection(window)) is not None
        )
        free_minutes = sum(segment.duration_minutes for segment in free)
        bookings = self.between(window, resource_id=resource_id)
        return UtilizationReport(
            resource_id,
            window,
            max(0, available_minutes - free_minutes),
            available_minutes,
            len(bookings),
        )

    def daily_timeline(self, day: date) -> dict[str, list[Booking]]:
        starts = datetime.combine(day, time.min)
        if any(booking.slot.start.tzinfo for booking in self.bookings.values()):
            timezone = next(
                booking.slot.start.tzinfo
                for booking in self.bookings.values()
                if booking.slot.start.tzinfo
            )
            starts = starts.replace(tzinfo=timezone)
        window = TimeRange(starts, starts + timedelta(days=1))
        timeline: dict[str, list[Booking]] = defaultdict(list)
        for booking in self.between(window):
            for resource_id in booking.resource_ids:
                timeline[resource_id].append(booking)
        return dict(sorted(timeline.items()))

    def conflict_matrix(self, window: TimeRange) -> dict[str, set[str]]:
        matrix: dict[str, set[str]] = defaultdict(set)
        bookings = self.between(window)
        for index, left in enumerate(bookings):
            for right in bookings[index + 1 :]:
                if not left.slot.expand(self.turnaround).overlaps(
                    right.slot.expand(self.turnaround)
                ):
                    continue
                shares_resource = bool(set(left.resource_ids).intersection(right.resource_ids))
                shares_person = bool(set(left.participant_ids).intersection(right.participant_ids))
                if shares_resource or shares_person:
                    matrix[left.id].add(right.id)
                    matrix[right.id].add(left.id)
        return dict(matrix)

    @staticmethod
    def _deduplicate_conflicts(
        conflicts: Iterable[SchedulingConflict],
    ) -> list[SchedulingConflict]:
        unique: dict[tuple[object, ...], SchedulingConflict] = {}
        for conflict in conflicts:
            key = (
                conflict.kind,
                conflict.booking_id,
                conflict.resource_id,
                conflict.participant_id,
            )
            unique[key] = conflict
        return sorted(
            unique.values(),
            key=lambda item: (
                item.kind,
                item.booking_id or "",
                item.resource_id or "",
                item.participant_id or "",
            ),
        )
