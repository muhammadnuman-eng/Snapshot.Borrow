"""Publish, acknowledge, and track production call sheets."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from lumenstage.errors import ConflictError, NotFoundError, ValidationError, WorkflowError


class CallStatus(StrEnum):
    CALLED = "called"
    ACKNOWLEDGED = "acknowledged"
    ARRIVED = "arrived"
    EXCUSED = "excused"


class ContactChannel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    PHONE = "phone"


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class Contact:
    person_id: str
    display_name: str
    email: str = ""
    phone: str = ""
    preferred_channel: ContactChannel = ContactChannel.EMAIL

    def __post_init__(self) -> None:
        _text(self.person_id, "person_id")
        _text(self.display_name, "display_name")
        if self.preferred_channel == ContactChannel.EMAIL and "@" not in self.email:
            raise ValidationError("preferred email contact requires a valid email")
        if self.preferred_channel in {ContactChannel.SMS, ContactChannel.PHONE} and not self.phone:
            raise ValidationError("preferred phone contact requires a phone number")

    @property
    def destination(self) -> str:
        return self.email if self.preferred_channel == ContactChannel.EMAIL else self.phone


@dataclass(frozen=True, slots=True)
class CallAssignment:
    id: str
    person_id: str
    role: str
    department: str
    call_at: datetime
    location: str
    notes: str = ""
    status: CallStatus = CallStatus.CALLED
    acknowledged_at: datetime | None = None
    arrived_at: datetime | None = None
    status_note: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.id, "call id"),
            (self.person_id, "person_id"),
            (self.role, "role"),
            (self.department, "department"),
            (self.location, "location"),
        ):
            _text(value, name)
        if self.call_at.tzinfo is None:
            raise ValidationError("call_at must be timezone-aware")

    def late_by(self) -> timedelta:
        if self.arrived_at is None or self.arrived_at <= self.call_at:
            return timedelta(0)
        return self.arrived_at - self.call_at


@dataclass(frozen=True, slots=True)
class CallChange:
    sequence: int
    occurred_at: datetime
    actor: str
    call_id: str
    field: str
    previous: str
    current: str


@dataclass(frozen=True, slots=True)
class Dispatch:
    person_id: str
    display_name: str
    channel: ContactChannel
    destination: str
    call_ids: tuple[str, ...]
    revision: int


@dataclass(frozen=True, slots=True)
class CallSheetSnapshot:
    revision: int
    published_at: datetime
    published_by: str
    calls: tuple[CallAssignment, ...]


@dataclass(frozen=True, slots=True)
class CallSheetReport:
    revision: int
    total: int
    acknowledged: int
    arrived: int
    excused: int
    late: tuple[str, ...]
    unacknowledged: tuple[str, ...]

    @property
    def acknowledgement_ratio(self) -> float:
        return 1.0 if self.total == 0 else self.acknowledged / self.total


class CallSheet:
    """A revisioned operational call list for one performance."""

    def __init__(
        self,
        production_id: str,
        performance_id: str,
        performance_at: datetime,
        venue: str,
        *,
        access_at: datetime | None = None,
    ) -> None:
        self.production_id = _text(production_id, "production_id")
        self.performance_id = _text(performance_id, "performance_id")
        self.venue = _text(venue, "venue")
        if performance_at.tzinfo is None:
            raise ValidationError("performance_at must be timezone-aware")
        if access_at is not None:
            if access_at.tzinfo is None:
                raise ValidationError("access_at must be timezone-aware")
            if access_at > performance_at:
                raise ValidationError("access_at must not follow performance_at")
        self.performance_at = performance_at
        self.access_at = access_at
        self._contacts: dict[str, Contact] = {}
        self._calls: dict[str, CallAssignment] = {}
        self._changes: list[CallChange] = []
        self._snapshots: list[CallSheetSnapshot] = []

    @property
    def revision(self) -> int:
        return len(self._snapshots)

    @property
    def published(self) -> bool:
        return bool(self._snapshots)

    @property
    def calls(self) -> tuple[CallAssignment, ...]:
        return tuple(sorted(self._calls.values(), key=lambda call: (call.call_at, call.id)))

    @property
    def changes(self) -> tuple[CallChange, ...]:
        return tuple(self._changes)

    def add_contact(self, contact: Contact) -> None:
        if contact.person_id in self._contacts:
            raise ConflictError(f"contact already exists: {contact.person_id}")
        self._contacts[contact.person_id] = contact

    def add_call(self, call: CallAssignment) -> None:
        if call.id in self._calls:
            raise ConflictError(f"call already exists: {call.id}")
        if call.person_id not in self._contacts:
            raise NotFoundError(f"contact not found: {call.person_id}")
        self._validate_call_time(call.call_at)
        duplicate = next(
            (
                item
                for item in self._calls.values()
                if item.person_id == call.person_id
                and item.call_at == call.call_at
                and item.location.casefold() == call.location.casefold()
            ),
            None,
        )
        if duplicate:
            raise ConflictError(f"duplicate person call: {duplicate.id}")
        self._calls[call.id] = call

    def require_call(self, call_id: str) -> CallAssignment:
        try:
            return self._calls[call_id]
        except KeyError as exc:
            raise NotFoundError(f"call not found: {call_id}") from exc

    def reschedule(self, call_id: str, call_at: datetime, actor: str) -> CallAssignment:
        call = self.require_call(call_id)
        if call.status in {CallStatus.ARRIVED, CallStatus.EXCUSED}:
            raise WorkflowError(f"cannot reschedule a {call.status} call")
        self._validate_call_time(call_at)
        updated = replace(
            call,
            call_at=call_at,
            status=CallStatus.CALLED,
            acknowledged_at=None,
        )
        self._calls[call_id] = updated
        self._change(actor, call_id, "call_at", call.call_at.isoformat(), call_at.isoformat())
        return updated

    def change_location(self, call_id: str, location: str, actor: str) -> CallAssignment:
        call = self.require_call(call_id)
        location = _text(location, "location")
        updated = replace(call, location=location, status=CallStatus.CALLED, acknowledged_at=None)
        self._calls[call_id] = updated
        self._change(actor, call_id, "location", call.location, location)
        return updated

    def acknowledge(
        self,
        call_id: str,
        person_id: str,
        *,
        at: datetime | None = None,
    ) -> CallAssignment:
        call = self.require_call(call_id)
        if call.person_id != person_id:
            raise WorkflowError("only the called person can acknowledge this call")
        if call.status != CallStatus.CALLED:
            raise WorkflowError(f"cannot acknowledge a {call.status} call")
        updated = replace(
            call,
            status=CallStatus.ACKNOWLEDGED,
            acknowledged_at=at or datetime.now(UTC),
        )
        self._calls[call_id] = updated
        return updated

    def mark_arrived(
        self,
        call_id: str,
        actor: str,
        *,
        at: datetime | None = None,
    ) -> CallAssignment:
        call = self.require_call(call_id)
        if call.status == CallStatus.EXCUSED:
            raise WorkflowError("an excused call cannot be marked arrived")
        moment = at or datetime.now(UTC)
        if moment.tzinfo is None:
            raise ValidationError("arrival time must be timezone-aware")
        updated = replace(call, status=CallStatus.ARRIVED, arrived_at=moment)
        self._calls[call_id] = updated
        self._change(actor, call_id, "status", call.status.value, CallStatus.ARRIVED.value)
        return updated

    def excuse(self, call_id: str, actor: str, reason: str) -> CallAssignment:
        call = self.require_call(call_id)
        if call.status == CallStatus.ARRIVED:
            raise WorkflowError("an arrived call cannot be excused")
        reason = _text(reason, "excuse reason")
        updated = replace(call, status=CallStatus.EXCUSED, status_note=reason)
        self._calls[call_id] = updated
        self._change(actor, call_id, "status", call.status.value, CallStatus.EXCUSED.value)
        return updated

    def publish(self, actor: str, *, at: datetime | None = None) -> CallSheetSnapshot:
        if not self._calls:
            raise WorkflowError("cannot publish an empty call sheet")
        moment = at or datetime.now(UTC)
        if moment.tzinfo is None:
            raise ValidationError("published_at must be timezone-aware")
        snapshot = CallSheetSnapshot(
            revision=self.revision + 1,
            published_at=moment,
            published_by=_text(actor, "actor"),
            calls=self.calls,
        )
        self._snapshots.append(snapshot)
        return snapshot

    def snapshot(self, revision: int | None = None) -> CallSheetSnapshot:
        if not self._snapshots:
            raise NotFoundError("call sheet has not been published")
        selected = revision or self.revision
        if selected < 1 or selected > self.revision:
            raise NotFoundError(f"call sheet revision not found: {selected}")
        return self._snapshots[selected - 1]

    def dispatches(self) -> list[Dispatch]:
        if not self.published:
            raise WorkflowError("publish the call sheet before dispatch")
        calls_by_person: defaultdict[str, list[str]] = defaultdict(list)
        for call in self.calls:
            if call.status != CallStatus.EXCUSED:
                calls_by_person[call.person_id].append(call.id)
        result = []
        for person_id, call_ids in sorted(calls_by_person.items()):
            contact = self._contacts[person_id]
            result.append(
                Dispatch(
                    person_id,
                    contact.display_name,
                    contact.preferred_channel,
                    contact.destination,
                    tuple(call_ids),
                    self.revision,
                )
            )
        return result

    def by_department(self, department: str) -> list[CallAssignment]:
        normalized = department.strip().casefold()
        return [call for call in self.calls if call.department.casefold() == normalized]

    def call_waves(self, *, minutes: int = 15) -> list[tuple[datetime, tuple[CallAssignment, ...]]]:
        if isinstance(minutes, bool) or minutes < 1:
            raise ValidationError("wave minutes must be positive")
        groups: defaultdict[datetime, list[CallAssignment]] = defaultdict(list)
        for call in self.calls:
            rounded_minute = call.call_at.minute - (call.call_at.minute % minutes)
            wave = call.call_at.replace(minute=rounded_minute, second=0, microsecond=0)
            groups[wave].append(call)
        return [
            (wave, tuple(sorted(calls, key=lambda call: call.person_id)))
            for wave, calls in sorted(groups.items())
        ]

    def report(self) -> CallSheetReport:
        acknowledged = sum(
            call.status in {CallStatus.ACKNOWLEDGED, CallStatus.ARRIVED} for call in self.calls
        )
        return CallSheetReport(
            revision=self.revision,
            total=len(self._calls),
            acknowledged=acknowledged,
            arrived=sum(call.status == CallStatus.ARRIVED for call in self.calls),
            excused=sum(call.status == CallStatus.EXCUSED for call in self.calls),
            late=tuple(call.id for call in self.calls if call.late_by() > timedelta(0)),
            unacknowledged=tuple(
                call.id for call in self.calls if call.status == CallStatus.CALLED
            ),
        )

    def _validate_call_time(self, call_at: datetime) -> None:
        if call_at.tzinfo is None:
            raise ValidationError("call_at must be timezone-aware")
        if call_at > self.performance_at:
            raise ValidationError("call time must not follow performance time")
        if self.access_at is not None and call_at < self.access_at:
            raise ValidationError("call time precedes venue access")

    def _change(
        self,
        actor: str,
        call_id: str,
        field: str,
        previous: str,
        current: str,
    ) -> None:
        self._changes.append(
            CallChange(
                sequence=len(self._changes) + 1,
                occurred_at=datetime.now(UTC),
                actor=_text(actor, "actor"),
                call_id=call_id,
                field=field,
                previous=previous,
                current=current,
            )
        )
