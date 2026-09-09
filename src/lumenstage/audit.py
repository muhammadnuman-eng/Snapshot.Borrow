"""Tamper-evident audit records for production and administrative actions."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Self

from lumenstage.errors import ConflictError, NotFoundError, ValidationError

GENESIS_HASH = "0" * 64
REDACTED = "[REDACTED]"


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    READ = "read"
    EXPORT = "export"
    LOGIN = "login"
    LOGOUT = "logout"
    STATE_CHANGE = "state_change"
    APPROVE = "approve"
    DENY = "deny"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    ERROR = "error"


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValidationError(f"{field_name} must be timezone-aware")
    return value


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class AuditActor:
    id: str
    display_name: str
    role: str = ""
    ip_address: str = ""
    user_agent: str = ""

    def __post_init__(self) -> None:
        _text(self.id, "actor id")
        _text(self.display_name, "actor display_name")

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "role": self.role,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            id=str(value.get("id", "")),
            display_name=str(value.get("display_name", "")),
            role=str(value.get("role", "")),
            ip_address=str(value.get("ip_address", "")),
            user_agent=str(value.get("user_agent", "")),
        )


@dataclass(frozen=True, slots=True)
class AuditPolicy:
    """Controls privacy filtering without weakening chain verification."""

    sensitive_fields: frozenset[str] = frozenset(
        {
            "password",
            "password_hash",
            "token",
            "access_token",
            "refresh_token",
            "secret",
            "api_key",
            "card_number",
            "cvv",
        }
    )
    max_string_length: int = 2000
    capture_reads: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.max_string_length, bool) or self.max_string_length < 16:
            raise ValidationError("max_string_length must be at least 16")
        object.__setattr__(
            self,
            "sensitive_fields",
            frozenset(field.strip().casefold() for field in self.sensitive_fields),
        )

    def sanitize(self, value: Any, *, key: str = "") -> Any:
        if key.casefold() in self.sensitive_fields:
            return REDACTED
        if isinstance(value, Mapping):
            return {
                str(child_key): self.sanitize(child_value, key=str(child_key))
                for child_key, child_value in value.items()
            }
        if isinstance(value, list | tuple | set | frozenset):
            return [self.sanitize(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, bytes):
            return f"[BYTES:{len(value)}]"
        if isinstance(value, str) and len(value) > self.max_string_length:
            omitted = len(value) - self.max_string_length
            return f"{value[: self.max_string_length]}...[{omitted} chars omitted]"
        if value is None or isinstance(value, str | int | float | bool):
            return value
        return str(value)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    sequence: int
    id: str
    occurred_at: datetime
    actor: AuditActor
    action: AuditAction
    outcome: AuditOutcome
    resource_type: str
    resource_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str
    correlation_id: str
    metadata: dict[str, Any]
    previous_hash: str
    digest: str

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValidationError("audit sequence must be a positive integer")
        _text(self.id, "event id")
        _aware(self.occurred_at, "occurred_at")
        _text(self.resource_type, "resource_type")
        _text(self.resource_id, "resource_id")
        for value, name in ((self.previous_hash, "previous_hash"), (self.digest, "digest")):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValidationError(f"{name} must be a lowercase SHA-256 digest")

    def hash_payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "id": self.id,
            "occurred_at": self.occurred_at.isoformat(),
            "actor": self.actor.to_dict(),
            "action": self.action.value,
            "outcome": self.outcome.value,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "before": self.before,
            "after": self.after,
            "reason": self.reason,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
            "previous_hash": self.previous_hash,
        }

    def expected_digest(self) -> str:
        return hashlib.sha256(_canonical(self.hash_payload())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self.hash_payload(), "digest": self.digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        try:
            return cls(
                sequence=int(value["sequence"]),
                id=str(value["id"]),
                occurred_at=datetime.fromisoformat(str(value["occurred_at"])),
                actor=AuditActor.from_dict(value["actor"]),
                action=AuditAction(str(value["action"])),
                outcome=AuditOutcome(str(value["outcome"])),
                resource_type=str(value["resource_type"]),
                resource_id=str(value["resource_id"]),
                before=deepcopy(value.get("before")),
                after=deepcopy(value.get("after")),
                reason=str(value.get("reason", "")),
                correlation_id=str(value.get("correlation_id", "")),
                metadata=deepcopy(value.get("metadata") or {}),
                previous_hash=str(value["previous_hash"]),
                digest=str(value["digest"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"invalid audit event: {exc}") from exc


@dataclass(frozen=True, slots=True)
class AuditEntry:
    actor: AuditActor
    action: AuditAction
    resource_type: str
    resource_id: str
    before: Mapping[str, Any] | None = None
    after: Mapping[str, Any] | None = None
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    reason: str = ""
    correlation_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuditQuery:
    actor_ids: frozenset[str] = frozenset()
    actions: frozenset[AuditAction] = frozenset()
    outcomes: frozenset[AuditOutcome] = frozenset()
    resource_types: frozenset[str] = frozenset()
    resource_id: str = ""
    correlation_id: str = ""
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    text: str = ""

    def __post_init__(self) -> None:
        if self.starts_at is not None:
            _aware(self.starts_at, "starts_at")
        if self.ends_at is not None:
            _aware(self.ends_at, "ends_at")
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at:
            raise ValidationError("audit query end must not precede start")

    def matches(self, event: AuditEvent) -> bool:
        if self.actor_ids and event.actor.id not in self.actor_ids:
            return False
        if self.actions and event.action not in self.actions:
            return False
        if self.outcomes and event.outcome not in self.outcomes:
            return False
        if self.resource_types and event.resource_type not in self.resource_types:
            return False
        if self.resource_id and event.resource_id != self.resource_id:
            return False
        if self.correlation_id and event.correlation_id != self.correlation_id:
            return False
        if self.starts_at and event.occurred_at < self.starts_at:
            return False
        if self.ends_at and event.occurred_at > self.ends_at:
            return False
        if self.text:
            haystack = " ".join(
                (
                    event.actor.display_name,
                    event.resource_type,
                    event.resource_id,
                    event.reason,
                    str(event.metadata),
                )
            ).casefold()
            if self.text.strip().casefold() not in haystack:
                return False
        return True


@dataclass(frozen=True, slots=True)
class AuditChange:
    path: str
    before: Any
    after: Any


@dataclass(frozen=True, slots=True)
class AuditVerification:
    valid: bool
    checked: int
    issues: tuple[str, ...]
    head_digest: str


@dataclass(frozen=True, slots=True)
class AuditPage:
    events: tuple[AuditEvent, ...]
    next_sequence: int | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class AuditSummary:
    total: int
    by_action: dict[str, int]
    by_outcome: dict[str, int]
    by_resource: dict[str, int]
    by_actor: dict[str, int]
    by_day: dict[str, int]


class AuditTrail:
    """Append-only hash chain with query, replay, and portable verification."""

    def __init__(
        self,
        scope: str,
        *,
        policy: AuditPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.scope = _text(scope, "audit scope")
        self.policy = policy or AuditPolicy()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._events: list[AuditEvent] = []

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)

    @property
    def head_digest(self) -> str:
        return self._events[-1].digest if self._events else GENESIS_HASH

    def require(self, event_id: str) -> AuditEvent:
        for event in self._events:
            if event.id == event_id:
                return event
        raise NotFoundError(f"audit event not found: {event_id}")

    def record(self, entry: AuditEntry) -> AuditEvent:
        occurred_at = entry.occurred_at or self._now()
        _aware(occurred_at, "occurred_at")
        if self._events and occurred_at < self._events[-1].occurred_at:
            raise ConflictError("audit events must be recorded in chronological order")
        resource_type = _text(entry.resource_type, "resource_type").strip().lower()
        resource_id = _text(entry.resource_id, "resource_id")
        before = self._mapping(entry.before, "before")
        after = self._mapping(entry.after, "after")
        self._validate_shape(entry.action, before, after)
        sequence = len(self._events) + 1
        event_id = f"AUD-{sequence:08d}"
        payload = {
            "sequence": sequence,
            "id": event_id,
            "occurred_at": occurred_at.isoformat(),
            "actor": entry.actor.to_dict(),
            "action": entry.action.value,
            "outcome": entry.outcome.value,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "before": before,
            "after": after,
            "reason": entry.reason.strip(),
            "correlation_id": entry.correlation_id.strip(),
            "metadata": self.policy.sanitize(dict(entry.metadata)),
            "previous_hash": self.head_digest,
        }
        digest = hashlib.sha256(_canonical(payload)).hexdigest()
        event = AuditEvent(
            sequence=sequence,
            id=event_id,
            occurred_at=occurred_at,
            actor=entry.actor,
            action=entry.action,
            outcome=entry.outcome,
            resource_type=resource_type,
            resource_id=resource_id,
            before=before,
            after=after,
            reason=entry.reason.strip(),
            correlation_id=entry.correlation_id.strip(),
            metadata=self.policy.sanitize(dict(entry.metadata)),
            previous_hash=self.head_digest,
            digest=digest,
        )
        self._events.append(event)
        return event

    def record_many(self, entries: Iterable[AuditEntry]) -> tuple[AuditEvent, ...]:
        starting_length = len(self._events)
        result = []
        try:
            for entry in entries:
                result.append(self.record(entry))
        except Exception:
            del self._events[starting_length:]
            raise
        return tuple(result)

    def record_read(
        self,
        actor: AuditActor,
        resource_type: str,
        resource_id: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> AuditEvent | None:
        if not self.policy.capture_reads:
            return None
        return self.record(
            AuditEntry(
                actor,
                AuditAction.READ,
                resource_type,
                resource_id,
                metadata=metadata or {},
            )
        )

    def query(self, query: AuditQuery | None = None) -> list[AuditEvent]:
        selected = query or AuditQuery()
        return [event for event in self._events if selected.matches(event)]

    def page(
        self,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        query: AuditQuery | None = None,
    ) -> AuditPage:
        if isinstance(after_sequence, bool) or after_sequence < 0:
            raise ValidationError("after_sequence must be non-negative")
        if isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValidationError("audit page limit must be between 1 and 1000")
        selected = [event for event in self.query(query) if event.sequence > after_sequence]
        page = selected[:limit]
        has_more = len(selected) > limit
        next_sequence = page[-1].sequence if has_more and page else None
        return AuditPage(tuple(page), next_sequence, has_more)

    def changes(self, event_id: str) -> list[AuditChange]:
        event = self.require(event_id)
        return self._diff(event.before or {}, event.after or {})

    def state_at(
        self,
        resource_type: str,
        resource_id: str,
        *,
        sequence: int | None = None,
    ) -> dict[str, Any] | None:
        state: dict[str, Any] | None = None
        normalized_type = resource_type.strip().lower()
        for event in self._events:
            if sequence is not None and event.sequence > sequence:
                break
            if event.resource_type != normalized_type or event.resource_id != resource_id:
                continue
            if event.outcome != AuditOutcome.SUCCESS:
                continue
            if event.action == AuditAction.DELETE:
                state = None
            elif event.after is not None:
                state = deepcopy(event.after)
        return state

    def lineage(self, resource_type: str, resource_id: str) -> list[AuditEvent]:
        normalized_type = resource_type.strip().lower()
        return [
            event
            for event in self._events
            if event.resource_type == normalized_type and event.resource_id == resource_id
        ]

    def verify(self) -> AuditVerification:
        issues: list[str] = []
        previous = GENESIS_HASH
        previous_time: datetime | None = None
        for expected_sequence, event in enumerate(self._events, start=1):
            if event.sequence != expected_sequence:
                issues.append(
                    f"sequence {expected_sequence}: found event sequence {event.sequence}"
                )
            if event.id != f"AUD-{expected_sequence:08d}":
                issues.append(f"sequence {expected_sequence}: invalid event id {event.id}")
            if event.previous_hash != previous:
                issues.append(f"sequence {expected_sequence}: previous hash mismatch")
            if event.digest != event.expected_digest():
                issues.append(f"sequence {expected_sequence}: digest mismatch")
            if previous_time is not None and event.occurred_at < previous_time:
                issues.append(f"sequence {expected_sequence}: timestamp moved backwards")
            previous = event.digest
            previous_time = event.occurred_at
        return AuditVerification(not issues, len(self._events), tuple(issues), self.head_digest)

    def summary(self, query: AuditQuery | None = None) -> AuditSummary:
        events = self.query(query)
        return AuditSummary(
            total=len(events),
            by_action=dict(Counter(event.action.value for event in events)),
            by_outcome=dict(Counter(event.outcome.value for event in events)),
            by_resource=dict(Counter(event.resource_type for event in events)),
            by_actor=dict(Counter(event.actor.id for event in events)),
            by_day=dict(Counter(event.occurred_at.date().isoformat() for event in events)),
        )

    def export_ndjson(self, query: AuditQuery | None = None) -> str:
        header = {
            "format": "lumenstage-audit-v1",
            "scope": self.scope,
            "count": len(self.query(query)),
        }
        lines = [json.dumps(header, ensure_ascii=False, sort_keys=True)]
        lines.extend(
            json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
            for event in self.query(query)
        )
        return "\n".join(lines) + "\n"

    @classmethod
    def import_ndjson(
        cls,
        content: str,
        *,
        policy: AuditPolicy | None = None,
    ) -> Self:
        lines = [line for line in content.splitlines() if line.strip()]
        if not lines:
            raise ValidationError("audit export is empty")
        try:
            header = json.loads(lines[0])
        except json.JSONDecodeError as exc:
            raise ValidationError("invalid audit export header") from exc
        if header.get("format") != "lumenstage-audit-v1":
            raise ValidationError("unsupported audit export format")
        trail = cls(str(header.get("scope", "")), policy=policy)
        for line in lines[1:]:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError("invalid audit event JSON") from exc
            trail._events.append(AuditEvent.from_dict(raw))
        if header.get("count") != len(trail._events):
            raise ValidationError("audit export count mismatch")
        verification = trail.verify()
        if not verification.valid:
            raise ConflictError(f"audit export integrity failure: {verification.issues[0]}")
        return trail

    def _mapping(
        self,
        value: Mapping[str, Any] | None,
        field_name: str,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise ValidationError(f"{field_name} must be an object")
        return self.policy.sanitize(dict(value))

    @staticmethod
    def _validate_shape(
        action: AuditAction,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        if action == AuditAction.CREATE and after is None:
            raise ValidationError("create audit event requires after state")
        if action == AuditAction.UPDATE:
            if before is None or after is None:
                raise ValidationError("update audit event requires before and after states")
            if before == after:
                raise ValidationError("update audit event must contain an observable change")
        if action == AuditAction.DELETE and before is None:
            raise ValidationError("delete audit event requires before state")

    @classmethod
    def _diff(
        cls,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        *,
        prefix: str = "",
    ) -> list[AuditChange]:
        changes = []
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else str(key)
            old = before.get(key)
            new = after.get(key)
            if isinstance(old, Mapping) and isinstance(new, Mapping):
                changes.extend(cls._diff(old, new, prefix=path))
            elif old != new:
                changes.append(AuditChange(path, deepcopy(old), deepcopy(new)))
        return changes

    def _now(self) -> datetime:
        return _aware(self._clock(), "audit clock")
