"""Cue sheet authoring and deterministic show-control execution."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from lumenstage.errors import ConflictError, NotFoundError, ValidationError, WorkflowError


class CueKind(StrEnum):
    """Technical department or mechanism responsible for a cue."""

    LIGHT = "light"
    SOUND = "sound"
    VIDEO = "video"
    AUTOMATION = "automation"
    FLY = "fly"
    CALL = "call"
    OTHER = "other"


class CueState(StrEnum):
    """Lifecycle state of a cue during one run."""

    PENDING = "pending"
    STANDBY = "standby"
    FIRED = "fired"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CueEventKind(StrEnum):
    RUN_STARTED = "run_started"
    ARMED = "armed"
    DISARMED = "disarmed"
    STANDBY = "standby"
    GO = "go"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RESET = "reset"
    NOTE = "note"
    RUN_ENDED = "run_ended"


TERMINAL_STATES = frozenset({CueState.COMPLETED, CueState.FAILED, CueState.SKIPPED})


def _clean_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


@dataclass(slots=True)
class Cue:
    """One ordered action in a production's technical cue stack."""

    number: int
    department: str
    action: str
    page: str = ""
    notes: str = ""
    kind: CueKind = CueKind.OTHER
    trigger: str = ""
    duration_ms: int = 0
    requires: tuple[int, ...] = ()
    critical: bool = False
    auto_follow_ms: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.number, bool) or not isinstance(self.number, int) or self.number < 1:
            raise ValidationError("cue number must be a positive int")
        self.department = _clean_text(self.department, "department").lower()
        self.action = _clean_text(self.action, "action")
        if not isinstance(self.kind, CueKind):
            try:
                self.kind = CueKind(self.kind)
            except ValueError as exc:
                raise ValidationError(f"unknown cue kind: {self.kind}") from exc
        if isinstance(self.duration_ms, bool) or self.duration_ms < 0:
            raise ValidationError("duration_ms must be a non-negative integer")
        if self.auto_follow_ms is not None and (
            isinstance(self.auto_follow_ms, bool) or self.auto_follow_ms < 0
        ):
            raise ValidationError("auto_follow_ms must be non-negative")
        if len(self.requires) != len(set(self.requires)):
            raise ValidationError("cue dependencies must be unique")
        if self.number in self.requires:
            raise ValidationError("a cue cannot depend on itself")

    @property
    def label(self) -> str:
        return f"{self.department.upper()} {self.number}"


@dataclass(frozen=True, slots=True)
class CueEvent:
    """Immutable operator action emitted by a cue run."""

    sequence: int
    occurred_at: datetime
    kind: CueEventKind
    cue_number: int | None = None
    operator: str = ""
    detail: str = ""
    elapsed_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "occurred_at": self.occurred_at.isoformat(),
            "kind": self.kind.value,
            "cue_number": self.cue_number,
            "operator": self.operator,
            "detail": self.detail,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True, slots=True)
class CueRunSnapshot:
    """Serializable point-in-time state used for recovery after a restart."""

    production_id: str
    started_at: datetime | None
    ended_at: datetime | None
    states: tuple[tuple[int, CueState], ...]
    armed: tuple[int, ...]
    fired_at: tuple[tuple[int, datetime], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "states": {str(number): state.value for number, state in self.states},
            "armed": list(self.armed),
            "fired_at": {str(number): moment.isoformat() for number, moment in self.fired_at},
        }


@dataclass(frozen=True, slots=True)
class CueRunReport:
    production_id: str
    started_at: datetime | None
    ended_at: datetime | None
    total_cues: int
    completed: int
    failed: int
    skipped: int
    pending: int
    event_count: int
    critical_failures: tuple[int, ...]

    @property
    def completion_ratio(self) -> float:
        if self.total_cues == 0:
            return 1.0
        return (self.completed + self.skipped) / self.total_cues

    @property
    def successful(self) -> bool:
        return self.failed == 0 and self.pending == 0 and not self.critical_failures


@dataclass(slots=True)
class CueSheet:
    """Ordered cue definition with dependency validation."""

    production_id: str
    cues: list[Cue] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.production_id = _clean_text(self.production_id, "production_id")
        numbers = [cue.number for cue in self.cues]
        if len(numbers) != len(set(numbers)):
            raise ValidationError("cue numbers must be unique")
        self.cues.sort(key=lambda cue: cue.number)
        self.validate()

    def add(self, number: int, department: str, action: str, **kwargs: Any) -> Cue:
        if any(cue.number == number for cue in self.cues):
            raise ValidationError(f"duplicate cue number: {number}")
        cue = Cue(number=number, department=department, action=action, **kwargs)
        self.cues.append(cue)
        self.cues.sort(key=lambda item: item.number)
        return cue

    def require(self, number: int) -> Cue:
        for cue in self.cues:
            if cue.number == number:
                return cue
        raise NotFoundError(f"cue not found: {number}")

    def remove(self, number: int) -> Cue:
        cue = self.require(number)
        dependants = [item.number for item in self.cues if number in item.requires]
        if dependants:
            joined = ", ".join(str(item) for item in dependants)
            raise ConflictError(f"cue {number} is required by: {joined}")
        self.cues.remove(cue)
        return cue

    def next_number(self) -> int:
        return max((cue.number for cue in self.cues), default=0) + 1

    def by_department(self, department: str) -> list[Cue]:
        normalized = department.strip().lower()
        return [cue for cue in self.cues if cue.department == normalized]

    def by_kind(self, kind: CueKind) -> list[Cue]:
        return [cue for cue in self.cues if cue.kind == kind]

    def between(self, first: int, last: int) -> list[Cue]:
        if first > last:
            raise ValidationError("first cue number must not exceed last")
        return [cue for cue in self.cues if first <= cue.number <= last]

    def renumber(self, old_number: int, new_number: int) -> Cue:
        cue = self.require(old_number)
        if old_number != new_number and any(item.number == new_number for item in self.cues):
            raise ConflictError(f"cue number already exists: {new_number}")
        if new_number < 1:
            raise ValidationError("cue number must be positive")
        cue.number = new_number
        for dependant in self.cues:
            if old_number in dependant.requires:
                dependant.requires = tuple(
                    new_number if item == old_number else item for item in dependant.requires
                )
        self.cues.sort(key=lambda item: item.number)
        self.validate()
        return cue

    def validate(self) -> None:
        numbers = {cue.number for cue in self.cues}
        for cue in self.cues:
            missing = set(cue.requires) - numbers
            if missing:
                raise ValidationError(
                    f"cue {cue.number} has missing dependencies: {sorted(missing)}"
                )
        visiting: set[int] = set()
        visited: set[int] = set()

        def visit(number: int) -> None:
            if number in visiting:
                raise ValidationError("cue dependency cycle detected")
            if number in visited:
                return
            visiting.add(number)
            for required in self.require(number).requires:
                visit(required)
            visiting.remove(number)
            visited.add(number)

        for number in numbers:
            visit(number)

    def dependency_order(self) -> list[Cue]:
        self.validate()
        result: list[Cue] = []
        seen: set[int] = set()

        def collect(cue: Cue) -> None:
            if cue.number in seen:
                return
            for required in cue.requires:
                collect(self.require(required))
            seen.add(cue.number)
            result.append(cue)

        for cue in self.cues:
            collect(cue)
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "cues": [
                {
                    "number": cue.number,
                    "department": cue.department,
                    "action": cue.action,
                    "page": cue.page,
                    "notes": cue.notes,
                    "kind": cue.kind.value,
                    "trigger": cue.trigger,
                    "duration_ms": cue.duration_ms,
                    "requires": list(cue.requires),
                    "critical": cue.critical,
                    "auto_follow_ms": cue.auto_follow_ms,
                }
                for cue in self.cues
            ],
        }


class CueRuntime:
    """Execute a cue sheet with operator checks and a complete audit log."""

    def __init__(
        self,
        sheet: CueSheet,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        sheet.validate()
        self.sheet = sheet
        self._clock = clock or (lambda: datetime.now(UTC))
        self._states = {cue.number: CueState.PENDING for cue in sheet.cues}
        self._armed: set[int] = set()
        self._fired_at: dict[int, datetime] = {}
        self._events: list[CueEvent] = []
        self.started_at: datetime | None = None
        self.ended_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self.started_at is not None and self.ended_at is None

    @property
    def events(self) -> tuple[CueEvent, ...]:
        return tuple(self._events)

    def state(self, number: int) -> CueState:
        self.sheet.require(number)
        return self._states[number]

    def start(self, operator: str) -> None:
        if self.started_at is not None:
            raise WorkflowError("cue run has already started")
        self.started_at = self._now()
        self._record(CueEventKind.RUN_STARTED, operator=operator)

    def arm(self, number: int, operator: str, *, detail: str = "") -> None:
        self._require_running()
        cue = self.sheet.require(number)
        if not cue.critical:
            raise WorkflowError(f"cue {number} does not require a safety arm")
        if self.state(number) in TERMINAL_STATES:
            raise WorkflowError(f"cannot arm cue in {self.state(number)} state")
        self._armed.add(number)
        self._record(CueEventKind.ARMED, number, operator, detail)

    def disarm(self, number: int, operator: str, *, detail: str = "") -> None:
        self._require_running()
        if number not in self._armed:
            raise WorkflowError(f"cue is not armed: {number}")
        self._armed.remove(number)
        self._record(CueEventKind.DISARMED, number, operator, detail)

    def standby(self, number: int, operator: str) -> None:
        self._require_running()
        if self.state(number) != CueState.PENDING:
            raise WorkflowError(f"cue {number} is not pending")
        blockers = self.blocking_dependencies(number)
        if blockers:
            raise WorkflowError(f"cue {number} is blocked by dependencies: {blockers}")
        self._states[number] = CueState.STANDBY
        self._record(CueEventKind.STANDBY, number, operator)

    def go(self, number: int, operator: str, *, force: bool = False) -> None:
        self._require_running()
        cue = self.sheet.require(number)
        if self.state(number) != CueState.STANDBY and not force:
            raise WorkflowError(f"cue {number} must be in standby before GO")
        blockers = self.blocking_dependencies(number)
        if blockers and not force:
            raise WorkflowError(f"cue {number} is blocked by dependencies: {blockers}")
        if cue.critical and number not in self._armed:
            raise WorkflowError(f"critical cue {number} must be armed before GO")
        self._states[number] = CueState.FIRED
        self._fired_at[number] = self._now()
        self._armed.discard(number)
        detail = "forced" if force else ""
        self._record(CueEventKind.GO, number, operator, detail)

    def complete(self, number: int, operator: str, *, detail: str = "") -> None:
        self._require_running()
        if self.state(number) != CueState.FIRED:
            raise WorkflowError(f"cue {number} has not been fired")
        self._states[number] = CueState.COMPLETED
        self._record(CueEventKind.COMPLETED, number, operator, detail)

    def fail(self, number: int, operator: str, reason: str) -> None:
        self._require_running()
        if self.state(number) not in {CueState.STANDBY, CueState.FIRED}:
            raise WorkflowError(f"cue {number} cannot fail from {self.state(number)} state")
        reason = _clean_text(reason, "reason")
        self._states[number] = CueState.FAILED
        self._armed.discard(number)
        self._record(CueEventKind.FAILED, number, operator, reason)

    def skip(self, number: int, operator: str, reason: str) -> None:
        self._require_running()
        if self.state(number) not in {CueState.PENDING, CueState.STANDBY}:
            raise WorkflowError(f"cue {number} cannot be skipped")
        reason = _clean_text(reason, "reason")
        cue = self.sheet.require(number)
        if cue.critical and len(reason) < 8:
            raise ValidationError("critical cue skip reason must be at least 8 characters")
        self._states[number] = CueState.SKIPPED
        self._armed.discard(number)
        self._record(CueEventKind.SKIPPED, number, operator, reason)

    def reset(self, number: int, operator: str, *, cascade: bool = False) -> list[int]:
        self._require_running()
        affected = {number}
        dependants = self._transitive_dependants(number)
        progressed = {item for item in dependants if self.state(item) != CueState.PENDING}
        if progressed and not cascade:
            raise ConflictError(f"dependent cues have progressed: {sorted(progressed)}")
        if cascade:
            affected.update(dependants)
        for cue_number in sorted(affected, reverse=True):
            self._states[cue_number] = CueState.PENDING
            self._armed.discard(cue_number)
            self._fired_at.pop(cue_number, None)
            self._record(CueEventKind.RESET, cue_number, operator)
        return sorted(affected)

    def blocking_dependencies(self, number: int) -> list[int]:
        cue = self.sheet.require(number)
        return [
            required
            for required in cue.requires
            if self.state(required) not in {CueState.COMPLETED, CueState.SKIPPED}
        ]

    def ready_cues(self, *, department: str | None = None) -> list[Cue]:
        result = []
        for cue in self.sheet.cues:
            if department and cue.department != department.strip().lower():
                continue
            if self.state(cue.number) == CueState.PENDING and not self.blocking_dependencies(
                cue.number
            ):
                result.append(cue)
        return result

    def next_cue(self, *, department: str | None = None) -> Cue | None:
        ready = self.ready_cues(department=department)
        return ready[0] if ready else None

    def process_auto_follows(self, operator: str, *, now: datetime | None = None) -> list[int]:
        self._require_running()
        moment = now or self._now()
        fired: list[int] = []
        for cue in self.sheet.cues:
            if cue.auto_follow_ms is None or self.state(cue.number) != CueState.FIRED:
                continue
            due = self._fired_at[cue.number] + timedelta(milliseconds=cue.auto_follow_ms)
            if moment < due:
                continue
            self._states[cue.number] = CueState.COMPLETED
            self._record(CueEventKind.COMPLETED, cue.number, operator, "auto-follow elapsed")
            next_cue = self._cue_after(cue.number)
            if next_cue is None or self.state(next_cue.number) != CueState.PENDING:
                continue
            if self.blocking_dependencies(next_cue.number):
                continue
            self.standby(next_cue.number, operator)
            self.go(next_cue.number, operator)
            fired.append(next_cue.number)
        return fired

    def note(self, operator: str, detail: str, *, cue_number: int | None = None) -> CueEvent:
        self._require_running()
        if cue_number is not None:
            self.sheet.require(cue_number)
        detail = _clean_text(detail, "detail")
        return self._record(CueEventKind.NOTE, cue_number, operator, detail)

    def end(self, operator: str, *, allow_incomplete: bool = False) -> CueRunReport:
        self._require_running()
        unfinished = [
            number for number, state in self._states.items() if state not in TERMINAL_STATES
        ]
        if unfinished and not allow_incomplete:
            raise WorkflowError(f"cannot end run with unfinished cues: {unfinished}")
        self.ended_at = self._now()
        self._record(CueEventKind.RUN_ENDED, operator=operator)
        return self.report()

    def report(self) -> CueRunReport:
        counts = {state: list(self._states.values()).count(state) for state in CueState}
        critical_failures = tuple(
            cue.number
            for cue in self.sheet.cues
            if cue.critical and self.state(cue.number) == CueState.FAILED
        )
        pending = counts[CueState.PENDING] + counts[CueState.STANDBY] + counts[CueState.FIRED]
        return CueRunReport(
            production_id=self.sheet.production_id,
            started_at=self.started_at,
            ended_at=self.ended_at,
            total_cues=len(self.sheet.cues),
            completed=counts[CueState.COMPLETED],
            failed=counts[CueState.FAILED],
            skipped=counts[CueState.SKIPPED],
            pending=pending,
            event_count=len(self._events),
            critical_failures=critical_failures,
        )

    def snapshot(self) -> CueRunSnapshot:
        return CueRunSnapshot(
            production_id=self.sheet.production_id,
            started_at=self.started_at,
            ended_at=self.ended_at,
            states=tuple(sorted(self._states.items())),
            armed=tuple(sorted(self._armed)),
            fired_at=tuple(sorted(self._fired_at.items())),
        )

    def restore(self, snapshot: CueRunSnapshot) -> None:
        if snapshot.production_id != self.sheet.production_id:
            raise ValidationError("snapshot belongs to a different production")
        restored = dict(snapshot.states)
        expected = {cue.number for cue in self.sheet.cues}
        if set(restored) != expected:
            raise ValidationError("snapshot cue set does not match cue sheet")
        self.started_at = snapshot.started_at
        self.ended_at = snapshot.ended_at
        self._states = restored
        self._armed = set(snapshot.armed)
        self._fired_at = dict(snapshot.fired_at)

    def event_log(
        self,
        *,
        cue_number: int | None = None,
        kinds: Iterable[CueEventKind] | None = None,
        operator: str | None = None,
    ) -> list[CueEvent]:
        selected_kinds = set(kinds) if kinds is not None else None
        return [
            event
            for event in self._events
            if (cue_number is None or event.cue_number == cue_number)
            and (selected_kinds is None or event.kind in selected_kinds)
            and (operator is None or event.operator == operator)
        ]

    def _record(
        self,
        kind: CueEventKind,
        cue_number: int | None = None,
        operator: str = "",
        detail: str = "",
    ) -> CueEvent:
        occurred_at = self._now()
        elapsed_ms = None
        if cue_number is not None and cue_number in self._fired_at:
            elapsed_ms = int((occurred_at - self._fired_at[cue_number]).total_seconds() * 1000)
        event = CueEvent(
            sequence=len(self._events) + 1,
            occurred_at=occurred_at,
            kind=kind,
            cue_number=cue_number,
            operator=operator.strip(),
            detail=detail.strip(),
            elapsed_ms=elapsed_ms,
        )
        self._events.append(event)
        return event

    def _require_running(self) -> None:
        if not self.running:
            raise WorkflowError("cue run is not active")

    def _now(self) -> datetime:
        moment = self._clock()
        if moment.tzinfo is None:
            raise ValidationError("cue runtime clock must return a timezone-aware datetime")
        return moment

    def _cue_after(self, number: int) -> Cue | None:
        for cue in self.sheet.cues:
            if cue.number > number:
                return cue
        return None

    def _transitive_dependants(self, number: int) -> set[int]:
        result: set[int] = set()
        pending = [number]
        while pending:
            required = pending.pop()
            for cue in self.sheet.cues:
                if required in cue.requires and cue.number not in result:
                    result.add(cue.number)
                    pending.append(cue.number)
        return result
