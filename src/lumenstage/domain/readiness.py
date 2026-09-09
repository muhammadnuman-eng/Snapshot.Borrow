"""Evidence-backed production readiness gates and sign-off history."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum

from lumenstage.errors import ConflictError, NotFoundError, ValidationError, WorkflowError


class ReadinessState(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    WAIVED = "waived"


class ReadinessEventKind(StrEnum):
    ADDED = "added"
    STARTED = "started"
    EVIDENCE_ADDED = "evidence_added"
    PASSED = "passed"
    FAILED = "failed"
    WAIVED = "waived"
    REOPENED = "reopened"
    OWNER_CHANGED = "owner_changed"


SATISFIED_STATES = frozenset({ReadinessState.PASSED, ReadinessState.WAIVED})


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    label: str
    reference: str
    submitted_by: str
    submitted_at: datetime
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.id, "evidence id"),
            (self.label, "evidence label"),
            (self.reference, "evidence reference"),
            (self.submitted_by, "submitted_by"),
        ):
            _required(value, name)
        if self.submitted_at.tzinfo is None:
            raise ValidationError("submitted_at must be timezone-aware")
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None:
                raise ValidationError("expires_at must be timezone-aware")
            if self.expires_at <= self.submitted_at:
                raise ValidationError("evidence expiry must follow submission")

    def valid_at(self, moment: datetime) -> bool:
        return self.expires_at is None or moment < self.expires_at


@dataclass(frozen=True, slots=True)
class ReadinessItem:
    id: str
    category: str
    title: str
    owner: str
    blocking: bool = True
    weight: int = 1
    due_at: datetime | None = None
    requires: tuple[str, ...] = ()
    minimum_evidence: int = 0
    state: ReadinessState = ReadinessState.NOT_STARTED
    evidence: tuple[Evidence, ...] = ()
    decision_note: str = ""
    decided_by: str = ""
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.id, "item id"),
            (self.category, "category"),
            (self.title, "title"),
            (self.owner, "owner"),
        ):
            _required(value, name)
        if isinstance(self.weight, bool) or self.weight < 1:
            raise ValidationError("weight must be a positive integer")
        if isinstance(self.minimum_evidence, bool) or self.minimum_evidence < 0:
            raise ValidationError("minimum_evidence must be non-negative")
        if len(self.requires) != len(set(self.requires)):
            raise ValidationError("readiness dependencies must be unique")
        if self.id in self.requires:
            raise ValidationError("a readiness item cannot depend on itself")
        if self.due_at is not None and self.due_at.tzinfo is None:
            raise ValidationError("due_at must be timezone-aware")

    def valid_evidence(self, moment: datetime) -> tuple[Evidence, ...]:
        return tuple(item for item in self.evidence if item.valid_at(moment))


@dataclass(frozen=True, slots=True)
class ReadinessEvent:
    sequence: int
    occurred_at: datetime
    kind: ReadinessEventKind
    item_id: str
    actor: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class CategoryReadiness:
    category: str
    total: int
    satisfied: int
    failed: int
    blocking_open: int
    score: float


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    production_id: str
    generated_at: datetime
    score: float
    gate_open: bool
    blockers: tuple[str, ...]
    overdue: tuple[str, ...]
    expired_evidence: tuple[str, ...]
    categories: tuple[CategoryReadiness, ...]


class ReadinessBoard:
    """Coordinate safety, creative, rights, venue, and commercial sign-offs."""

    def __init__(self, production_id: str) -> None:
        self.production_id = _required(production_id, "production_id")
        self._items: dict[str, ReadinessItem] = {}
        self._events: list[ReadinessEvent] = []

    @property
    def items(self) -> tuple[ReadinessItem, ...]:
        return tuple(sorted(self._items.values(), key=lambda item: (item.category, item.id)))

    @property
    def events(self) -> tuple[ReadinessEvent, ...]:
        return tuple(self._events)

    def add(self, item: ReadinessItem, actor: str = "system") -> None:
        if item.id in self._items:
            raise ConflictError(f"readiness item already exists: {item.id}")
        missing = set(item.requires) - set(self._items)
        if missing:
            raise ValidationError(f"missing readiness dependencies: {sorted(missing)}")
        self._items[item.id] = item
        self._validate_cycles()
        self._record(ReadinessEventKind.ADDED, item.id, actor)

    def add_all(self, items: Iterable[ReadinessItem], actor: str = "system") -> None:
        added: list[str] = []
        try:
            for item in items:
                self.add(item, actor)
                added.append(item.id)
        except Exception:
            for item_id in added:
                self._items.pop(item_id, None)
            self._events = [event for event in self._events if event.item_id not in added]
            raise

    def require(self, item_id: str) -> ReadinessItem:
        try:
            return self._items[item_id]
        except KeyError as exc:
            raise NotFoundError(f"readiness item not found: {item_id}") from exc

    def start(self, item_id: str, actor: str) -> ReadinessItem:
        item = self.require(item_id)
        if item.state != ReadinessState.NOT_STARTED:
            raise WorkflowError(f"cannot start item from {item.state} state")
        updated = replace(item, state=ReadinessState.IN_PROGRESS)
        return self._save(updated, ReadinessEventKind.STARTED, actor)

    def add_evidence(self, item_id: str, evidence: Evidence, actor: str) -> ReadinessItem:
        item = self.require(item_id)
        if item.state in SATISFIED_STATES:
            raise WorkflowError("reopen a satisfied item before adding evidence")
        if any(existing.id == evidence.id for existing in item.evidence):
            raise ConflictError(f"evidence already exists: {evidence.id}")
        updated = replace(
            item,
            state=ReadinessState.IN_PROGRESS,
            evidence=(*item.evidence, evidence),
        )
        return self._save(
            updated,
            ReadinessEventKind.EVIDENCE_ADDED,
            actor,
            evidence.reference,
        )

    def pass_item(
        self,
        item_id: str,
        actor: str,
        *,
        note: str = "",
        decided_at: datetime | None = None,
    ) -> ReadinessItem:
        item = self.require(item_id)
        moment = decided_at or datetime.now(UTC)
        blockers = self.blocking_dependencies(item_id)
        if blockers:
            raise WorkflowError(f"readiness dependencies are not satisfied: {blockers}")
        if len(item.valid_evidence(moment)) < item.minimum_evidence:
            raise WorkflowError(f"item requires {item.minimum_evidence} valid evidence record(s)")
        updated = replace(
            item,
            state=ReadinessState.PASSED,
            decision_note=note.strip(),
            decided_by=_required(actor, "actor"),
            decided_at=moment,
        )
        return self._save(updated, ReadinessEventKind.PASSED, actor, note)

    def fail_item(self, item_id: str, actor: str, reason: str) -> ReadinessItem:
        item = self.require(item_id)
        reason = _required(reason, "failure reason")
        updated = replace(
            item,
            state=ReadinessState.FAILED,
            decision_note=reason,
            decided_by=_required(actor, "actor"),
            decided_at=datetime.now(UTC),
        )
        return self._save(updated, ReadinessEventKind.FAILED, actor, reason)

    def waive(
        self,
        item_id: str,
        actor: str,
        reason: str,
        *,
        authorized: bool = False,
    ) -> ReadinessItem:
        item = self.require(item_id)
        reason = _required(reason, "waiver reason")
        if item.blocking and not authorized:
            raise WorkflowError("blocking item waiver requires explicit authorization")
        updated = replace(
            item,
            state=ReadinessState.WAIVED,
            decision_note=reason,
            decided_by=_required(actor, "actor"),
            decided_at=datetime.now(UTC),
        )
        return self._save(updated, ReadinessEventKind.WAIVED, actor, reason)

    def reopen(self, item_id: str, actor: str, reason: str) -> ReadinessItem:
        item = self.require(item_id)
        if item.state not in {ReadinessState.PASSED, ReadinessState.FAILED, ReadinessState.WAIVED}:
            raise WorkflowError(f"cannot reopen item from {item.state} state")
        progressed = [
            dependant.id
            for dependant in self._items.values()
            if item_id in dependant.requires and dependant.state in SATISFIED_STATES
        ]
        if progressed:
            raise ConflictError(f"satisfied dependent items must be reopened first: {progressed}")
        updated = replace(
            item,
            state=ReadinessState.IN_PROGRESS,
            decision_note="",
            decided_by="",
            decided_at=None,
        )
        return self._save(updated, ReadinessEventKind.REOPENED, actor, _required(reason, "reason"))

    def assign(self, item_id: str, owner: str, actor: str) -> ReadinessItem:
        item = self.require(item_id)
        owner = _required(owner, "owner")
        updated = replace(item, owner=owner)
        return self._save(updated, ReadinessEventKind.OWNER_CHANGED, actor, owner)

    def blocking_dependencies(self, item_id: str) -> list[str]:
        item = self.require(item_id)
        return [
            required
            for required in item.requires
            if self.require(required).state not in SATISFIED_STATES
        ]

    def actionable_for(self, owner: str) -> list[ReadinessItem]:
        normalized = owner.strip().casefold()
        return [
            item
            for item in self.items
            if item.owner.casefold() == normalized
            and item.state not in SATISFIED_STATES
            and not self.blocking_dependencies(item.id)
        ]

    def report(self, *, at: datetime | None = None) -> ReadinessReport:
        moment = at or datetime.now(UTC)
        if moment.tzinfo is None:
            raise ValidationError("report time must be timezone-aware")
        total_weight = sum(item.weight for item in self._items.values())
        earned_weight = sum(
            item.weight for item in self._items.values() if item.state in SATISFIED_STATES
        )
        score = 1.0 if total_weight == 0 else earned_weight / total_weight
        blockers = tuple(
            item.id for item in self.items if item.blocking and item.state not in SATISFIED_STATES
        )
        overdue = tuple(
            item.id
            for item in self.items
            if item.due_at is not None
            and item.due_at < moment
            and item.state not in SATISFIED_STATES
        )
        expired = tuple(
            f"{item.id}:{evidence.id}"
            for item in self.items
            for evidence in item.evidence
            if not evidence.valid_at(moment)
        )
        categories = self._category_reports()
        return ReadinessReport(
            self.production_id,
            moment,
            score,
            not blockers,
            blockers,
            overdue,
            expired,
            tuple(categories),
        )

    def _category_reports(self) -> list[CategoryReadiness]:
        groups: defaultdict[str, list[ReadinessItem]] = defaultdict(list)
        for item in self.items:
            groups[item.category].append(item)
        result = []
        for category, items in sorted(groups.items()):
            total_weight = sum(item.weight for item in items)
            earned = sum(item.weight for item in items if item.state in SATISFIED_STATES)
            result.append(
                CategoryReadiness(
                    category=category,
                    total=len(items),
                    satisfied=sum(item.state in SATISFIED_STATES for item in items),
                    failed=sum(item.state == ReadinessState.FAILED for item in items),
                    blocking_open=sum(
                        item.blocking and item.state not in SATISFIED_STATES for item in items
                    ),
                    score=earned / total_weight,
                )
            )
        return result

    def _save(
        self,
        item: ReadinessItem,
        kind: ReadinessEventKind,
        actor: str,
        detail: str = "",
    ) -> ReadinessItem:
        self._items[item.id] = item
        self._record(kind, item.id, actor, detail)
        return item

    def _record(
        self,
        kind: ReadinessEventKind,
        item_id: str,
        actor: str,
        detail: str = "",
    ) -> None:
        self._events.append(
            ReadinessEvent(
                sequence=len(self._events) + 1,
                occurred_at=datetime.now(UTC),
                kind=kind,
                item_id=item_id,
                actor=_required(actor, "actor"),
                detail=detail.strip(),
            )
        )

    def _validate_cycles(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(item_id: str) -> None:
            if item_id in visiting:
                raise ValidationError("readiness dependency cycle detected")
            if item_id in visited:
                return
            visiting.add(item_id)
            for required in self.require(item_id).requires:
                visit(required)
            visiting.remove(item_id)
            visited.add(item_id)

        for item_id in self._items:
            visit(item_id)
