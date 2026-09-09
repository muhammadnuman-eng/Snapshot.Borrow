"""Safety incident intake, response coordination, and closure controls."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from lumenstage.errors import ConflictError, NotFoundError, ValidationError, WorkflowError


class IncidentSeverity(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentCategory(StrEnum):
    INJURY = "injury"
    NEAR_MISS = "near_miss"
    EQUIPMENT = "equipment"
    FIRE = "fire"
    SECURITY = "security"
    SAFEGUARDING = "safeguarding"
    PROPERTY = "property"
    OTHER = "other"


class IncidentStatus(StrEnum):
    REPORTED = "reported"
    TRIAGED = "triaged"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class ActionStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class IncidentEventKind(StrEnum):
    REPORTED = "reported"
    TRIAGED = "triaged"
    SEVERITY_CHANGED = "severity_changed"
    ASSIGNED = "assigned"
    UPDATE = "update"
    WITNESS_ADDED = "witness_added"
    ATTACHMENT_ADDED = "attachment_added"
    ACTION_ADDED = "action_added"
    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    ACTION_CANCELLED = "action_cancelled"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"


TRIAGE_SLA = {
    IncidentSeverity.LOW: timedelta(hours=24),
    IncidentSeverity.MODERATE: timedelta(hours=8),
    IncidentSeverity.HIGH: timedelta(hours=1),
    IncidentSeverity.CRITICAL: timedelta(minutes=15),
}


RESOLUTION_SLA = {
    IncidentSeverity.LOW: timedelta(days=14),
    IncidentSeverity.MODERATE: timedelta(days=7),
    IncidentSeverity.HIGH: timedelta(days=3),
    IncidentSeverity.CRITICAL: timedelta(days=1),
}


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValidationError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class Witness:
    id: str
    name: str
    contact: str = ""
    statement: str = ""
    statement_at: datetime | None = None

    def __post_init__(self) -> None:
        _text(self.id, "witness id")
        _text(self.name, "witness name")
        if self.statement_at is not None:
            _aware(self.statement_at, "statement_at")
        if self.statement and self.statement_at is None:
            raise ValidationError("statement_at is required when a statement is recorded")


@dataclass(frozen=True, slots=True)
class IncidentAttachment:
    id: str
    label: str
    reference: str
    media_type: str
    uploaded_by: str
    uploaded_at: datetime
    checksum: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.id, "attachment id"),
            (self.label, "attachment label"),
            (self.reference, "attachment reference"),
            (self.media_type, "media_type"),
            (self.uploaded_by, "uploaded_by"),
        ):
            _text(value, name)
        _aware(self.uploaded_at, "uploaded_at")
        if self.checksum and (
            len(self.checksum) != 64
            or any(character not in "0123456789abcdef" for character in self.checksum)
        ):
            raise ValidationError("attachment checksum must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class CorrectiveAction:
    id: str
    title: str
    owner: str
    due_at: datetime
    blocking: bool = True
    requires: tuple[str, ...] = ()
    status: ActionStatus = ActionStatus.OPEN
    completion_note: str = ""
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        _text(self.id, "action id")
        _text(self.title, "action title")
        _text(self.owner, "action owner")
        _aware(self.due_at, "action due_at")
        if len(self.requires) != len(set(self.requires)):
            raise ValidationError("action dependencies must be unique")
        if self.id in self.requires:
            raise ValidationError("an action cannot depend on itself")


@dataclass(frozen=True, slots=True)
class Incident:
    id: str
    production_id: str
    title: str
    description: str
    category: IncidentCategory
    severity: IncidentSeverity
    occurred_at: datetime
    reported_at: datetime
    reported_by: str
    location: str
    status: IncidentStatus = IncidentStatus.REPORTED
    lead: str = ""
    triaged_at: datetime | None = None
    triage_due_at: datetime | None = None
    resolution_due_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    root_cause: str = ""
    resolution: str = ""
    regulatory_reference: str = ""
    witnesses: tuple[Witness, ...] = ()
    attachments: tuple[IncidentAttachment, ...] = ()
    actions: tuple[CorrectiveAction, ...] = ()

    def __post_init__(self) -> None:
        for value, name in (
            (self.id, "incident id"),
            (self.production_id, "production_id"),
            (self.title, "incident title"),
            (self.description, "incident description"),
            (self.reported_by, "reported_by"),
            (self.location, "location"),
        ):
            _text(value, name)
        _aware(self.occurred_at, "occurred_at")
        _aware(self.reported_at, "reported_at")
        if self.occurred_at > self.reported_at:
            raise ValidationError("incident occurrence cannot follow report time")
        for value, name in (
            (self.triaged_at, "triaged_at"),
            (self.triage_due_at, "triage_due_at"),
            (self.resolution_due_at, "resolution_due_at"),
            (self.resolved_at, "resolved_at"),
            (self.closed_at, "closed_at"),
        ):
            if value is not None:
                _aware(value, name)

    @property
    def open(self) -> bool:
        return self.status not in {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}

    def blocking_actions(self) -> tuple[CorrectiveAction, ...]:
        return tuple(
            action
            for action in self.actions
            if action.blocking and action.status not in {ActionStatus.DONE, ActionStatus.CANCELLED}
        )

    def overdue_actions(self, moment: datetime) -> tuple[CorrectiveAction, ...]:
        return tuple(
            action
            for action in self.actions
            if action.due_at < moment
            and action.status not in {ActionStatus.DONE, ActionStatus.CANCELLED}
        )


@dataclass(frozen=True, slots=True)
class IncidentEvent:
    sequence: int
    incident_id: str
    kind: IncidentEventKind
    occurred_at: datetime
    actor: str
    detail: str = ""
    action_id: str = ""


@dataclass(frozen=True, slots=True)
class IncidentQuery:
    production_id: str = ""
    statuses: frozenset[IncidentStatus] = frozenset()
    severities: frozenset[IncidentSeverity] = frozenset()
    categories: frozenset[IncidentCategory] = frozenset()
    lead: str = ""
    location: str = ""
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    text: str = ""

    def __post_init__(self) -> None:
        if self.starts_at is not None:
            _aware(self.starts_at, "starts_at")
        if self.ends_at is not None:
            _aware(self.ends_at, "ends_at")
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at:
            raise ValidationError("incident query end must not precede start")

    def matches(self, incident: Incident) -> bool:
        if self.production_id and incident.production_id != self.production_id:
            return False
        if self.statuses and incident.status not in self.statuses:
            return False
        if self.severities and incident.severity not in self.severities:
            return False
        if self.categories and incident.category not in self.categories:
            return False
        if self.lead and incident.lead.casefold() != self.lead.strip().casefold():
            return False
        if self.location and self.location.strip().casefold() not in incident.location.casefold():
            return False
        if self.starts_at and incident.occurred_at < self.starts_at:
            return False
        if self.ends_at and incident.occurred_at > self.ends_at:
            return False
        if self.text:
            haystack = " ".join(
                (
                    incident.id,
                    incident.title,
                    incident.description,
                    incident.location,
                    incident.root_cause,
                    incident.resolution,
                )
            ).casefold()
            if self.text.strip().casefold() not in haystack:
                return False
        return True


@dataclass(frozen=True, slots=True)
class Escalation:
    incident_id: str
    reason: str
    recipients: tuple[str, ...]
    overdue_by: timedelta


@dataclass(frozen=True, slots=True)
class IncidentMetrics:
    total: int
    open: int
    overdue_triage: int
    overdue_resolution: int
    overdue_actions: int
    by_severity: dict[str, int]
    by_category: dict[str, int]
    by_status: dict[str, int]
    average_triage_minutes: float | None
    average_resolution_minutes: float | None


class IncidentDesk:
    """Enforce a traceable incident response from report through closure."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._incidents: dict[str, Incident] = {}
        self._events: list[IncidentEvent] = []

    @property
    def incidents(self) -> tuple[Incident, ...]:
        return tuple(sorted(self._incidents.values(), key=lambda item: (item.reported_at, item.id)))

    @property
    def events(self) -> tuple[IncidentEvent, ...]:
        return tuple(self._events)

    def report(
        self,
        incident_id: str,
        production_id: str,
        title: str,
        description: str,
        category: IncidentCategory,
        severity: IncidentSeverity,
        occurred_at: datetime,
        reported_by: str,
        location: str,
        *,
        reported_at: datetime | None = None,
    ) -> Incident:
        if incident_id in self._incidents:
            raise ConflictError(f"incident already exists: {incident_id}")
        moment = reported_at or self._now()
        incident = Incident(
            id=incident_id,
            production_id=production_id,
            title=title,
            description=description,
            category=category,
            severity=severity,
            occurred_at=occurred_at,
            reported_at=moment,
            reported_by=reported_by,
            location=location,
            triage_due_at=moment + TRIAGE_SLA[severity],
            resolution_due_at=moment + RESOLUTION_SLA[severity],
        )
        self._incidents[incident.id] = incident
        self._record(incident.id, IncidentEventKind.REPORTED, reported_by, title)
        return incident

    def require(self, incident_id: str) -> Incident:
        try:
            return self._incidents[incident_id]
        except KeyError as exc:
            raise NotFoundError(f"incident not found: {incident_id}") from exc

    def triage(
        self,
        incident_id: str,
        lead: str,
        actor: str,
        *,
        severity: IncidentSeverity | None = None,
        at: datetime | None = None,
    ) -> Incident:
        incident = self.require(incident_id)
        if incident.status != IncidentStatus.REPORTED:
            raise WorkflowError(f"cannot triage incident from {incident.status} state")
        moment = at or self._now()
        selected_severity = severity or incident.severity
        updated = replace(
            incident,
            severity=selected_severity,
            status=IncidentStatus.TRIAGED,
            lead=_text(lead, "incident lead"),
            triaged_at=moment,
            resolution_due_at=incident.reported_at + RESOLUTION_SLA[selected_severity],
        )
        self._save(updated, IncidentEventKind.TRIAGED, actor, selected_severity.value)
        return updated

    def assign(self, incident_id: str, lead: str, actor: str) -> Incident:
        incident = self.require(incident_id)
        self._require_active(incident)
        updated = replace(incident, lead=_text(lead, "incident lead"))
        return self._save(updated, IncidentEventKind.ASSIGNED, actor, lead)

    def change_severity(
        self,
        incident_id: str,
        severity: IncidentSeverity,
        actor: str,
        reason: str,
    ) -> Incident:
        incident = self.require(incident_id)
        self._require_active(incident)
        reason = _text(reason, "severity change reason")
        updated = replace(
            incident,
            severity=severity,
            triage_due_at=incident.reported_at + TRIAGE_SLA[severity],
            resolution_due_at=incident.reported_at + RESOLUTION_SLA[severity],
        )
        return self._save(
            updated,
            IncidentEventKind.SEVERITY_CHANGED,
            actor,
            f"{incident.severity.value} -> {severity.value}: {reason}",
        )

    def add_update(self, incident_id: str, actor: str, detail: str) -> IncidentEvent:
        incident = self.require(incident_id)
        self._require_active(incident)
        return self._record(
            incident_id,
            IncidentEventKind.UPDATE,
            actor,
            _text(detail, "update detail"),
        )

    def add_witness(self, incident_id: str, witness: Witness, actor: str) -> Incident:
        incident = self.require(incident_id)
        self._require_active(incident)
        if any(existing.id == witness.id for existing in incident.witnesses):
            raise ConflictError(f"witness already exists: {witness.id}")
        updated = replace(incident, witnesses=(*incident.witnesses, witness))
        return self._save(updated, IncidentEventKind.WITNESS_ADDED, actor, witness.name)

    def add_attachment(
        self,
        incident_id: str,
        attachment: IncidentAttachment,
        actor: str,
    ) -> Incident:
        incident = self.require(incident_id)
        self._require_active(incident)
        if any(existing.id == attachment.id for existing in incident.attachments):
            raise ConflictError(f"attachment already exists: {attachment.id}")
        updated = replace(incident, attachments=(*incident.attachments, attachment))
        return self._save(
            updated,
            IncidentEventKind.ATTACHMENT_ADDED,
            actor,
            attachment.reference,
        )

    def add_action(self, incident_id: str, action: CorrectiveAction, actor: str) -> Incident:
        incident = self.require(incident_id)
        self._require_active(incident)
        if any(existing.id == action.id for existing in incident.actions):
            raise ConflictError(f"corrective action already exists: {action.id}")
        missing = set(action.requires) - {existing.id for existing in incident.actions}
        if missing:
            raise ValidationError(f"missing corrective action dependencies: {sorted(missing)}")
        updated = replace(incident, actions=(*incident.actions, action))
        self._validate_action_cycles(updated)
        return self._save(updated, IncidentEventKind.ACTION_ADDED, actor, action.title, action.id)

    def start_action(self, incident_id: str, action_id: str, actor: str) -> CorrectiveAction:
        incident = self.require(incident_id)
        action = self._require_action(incident, action_id)
        if action.status != ActionStatus.OPEN:
            raise WorkflowError(f"cannot start action from {action.status} state")
        blockers = self._action_blockers(incident, action)
        if blockers:
            raise WorkflowError(f"corrective action is blocked by: {blockers}")
        updated = replace(action, status=ActionStatus.IN_PROGRESS)
        self._replace_action(incident, updated)
        self._record(incident_id, IncidentEventKind.ACTION_STARTED, actor, action.title, action.id)
        return updated

    def complete_action(
        self,
        incident_id: str,
        action_id: str,
        actor: str,
        note: str,
        *,
        at: datetime | None = None,
    ) -> CorrectiveAction:
        incident = self.require(incident_id)
        action = self._require_action(incident, action_id)
        if action.status not in {ActionStatus.OPEN, ActionStatus.IN_PROGRESS}:
            raise WorkflowError(f"cannot complete action from {action.status} state")
        blockers = self._action_blockers(incident, action)
        if blockers:
            raise WorkflowError(f"corrective action is blocked by: {blockers}")
        note = _text(note, "completion note")
        updated = replace(
            action,
            status=ActionStatus.DONE,
            completion_note=note,
            completed_at=at or self._now(),
        )
        self._replace_action(incident, updated)
        self._record(incident_id, IncidentEventKind.ACTION_COMPLETED, actor, note, action.id)
        return updated

    def cancel_action(
        self,
        incident_id: str,
        action_id: str,
        actor: str,
        reason: str,
        *,
        authorized: bool = False,
    ) -> CorrectiveAction:
        incident = self.require(incident_id)
        action = self._require_action(incident, action_id)
        if action.status == ActionStatus.DONE:
            raise WorkflowError("completed corrective action cannot be cancelled")
        if action.blocking and not authorized:
            raise WorkflowError("blocking action cancellation requires authorization")
        updated = replace(
            action,
            status=ActionStatus.CANCELLED,
            completion_note=_text(reason, "cancellation reason"),
            completed_at=self._now(),
        )
        self._replace_action(incident, updated)
        self._record(
            incident_id,
            IncidentEventKind.ACTION_CANCELLED,
            actor,
            reason,
            action.id,
        )
        return updated

    def begin_investigation(self, incident_id: str, actor: str) -> Incident:
        incident = self.require(incident_id)
        if incident.status != IncidentStatus.TRIAGED:
            raise WorkflowError(f"cannot investigate incident from {incident.status} state")
        updated = replace(incident, status=IncidentStatus.INVESTIGATING)
        return self._save(updated, IncidentEventKind.UPDATE, actor, "investigation started")

    def resolve(
        self,
        incident_id: str,
        actor: str,
        resolution: str,
        *,
        root_cause: str = "",
        regulatory_reference: str = "",
        at: datetime | None = None,
    ) -> Incident:
        incident = self.require(incident_id)
        if incident.status not in {IncidentStatus.TRIAGED, IncidentStatus.INVESTIGATING}:
            raise WorkflowError(f"cannot resolve incident from {incident.status} state")
        blockers = incident.blocking_actions()
        if blockers:
            raise WorkflowError(
                f"blocking corrective actions remain open: {[action.id for action in blockers]}"
            )
        if incident.severity in {IncidentSeverity.HIGH, IncidentSeverity.CRITICAL}:
            root_cause = _text(root_cause, "root_cause")
        updated = replace(
            incident,
            status=IncidentStatus.RESOLVED,
            resolution=_text(resolution, "resolution"),
            root_cause=root_cause.strip(),
            regulatory_reference=regulatory_reference.strip(),
            resolved_at=at or self._now(),
        )
        return self._save(updated, IncidentEventKind.RESOLVED, actor, resolution)

    def close(self, incident_id: str, actor: str, *, at: datetime | None = None) -> Incident:
        incident = self.require(incident_id)
        if incident.status != IncidentStatus.RESOLVED:
            raise WorkflowError("only a resolved incident can be closed")
        if incident.category == IncidentCategory.INJURY and not incident.regulatory_reference:
            raise WorkflowError("injury incident requires a regulatory reference before closure")
        updated = replace(incident, status=IncidentStatus.CLOSED, closed_at=at or self._now())
        return self._save(updated, IncidentEventKind.CLOSED, actor)

    def reopen(self, incident_id: str, actor: str, reason: str) -> Incident:
        incident = self.require(incident_id)
        if incident.status not in {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}:
            raise WorkflowError(f"cannot reopen incident from {incident.status} state")
        updated = replace(
            incident,
            status=IncidentStatus.INVESTIGATING,
            resolved_at=None,
            closed_at=None,
        )
        return self._save(
            updated,
            IncidentEventKind.REOPENED,
            actor,
            _text(reason, "reopen reason"),
        )

    def escalations(self, *, at: datetime | None = None) -> list[Escalation]:
        moment = at or self._now()
        result = []
        for incident in self.incidents:
            if not incident.open:
                continue
            recipients = self.notification_roles(incident.id)
            if incident.status == IncidentStatus.REPORTED and incident.triage_due_at < moment:
                result.append(
                    Escalation(
                        incident.id,
                        "triage overdue",
                        recipients,
                        moment - incident.triage_due_at,
                    )
                )
            elif incident.resolution_due_at < moment:
                result.append(
                    Escalation(
                        incident.id,
                        "resolution overdue",
                        recipients,
                        moment - incident.resolution_due_at,
                    )
                )
            for action in incident.overdue_actions(moment):
                result.append(
                    Escalation(
                        incident.id,
                        f"corrective action overdue: {action.id}",
                        tuple(dict.fromkeys((action.owner, *recipients))),
                        moment - action.due_at,
                    )
                )
        return sorted(result, key=lambda item: item.overdue_by, reverse=True)

    def record_escalations(self, actor: str, *, at: datetime | None = None) -> list[Escalation]:
        result = self.escalations(at=at)
        for escalation in result:
            self._record(
                escalation.incident_id,
                IncidentEventKind.ESCALATED,
                actor,
                escalation.reason,
            )
        return result

    def notification_roles(self, incident_id: str) -> tuple[str, ...]:
        incident = self.require(incident_id)
        roles = ["stage_manager", "production_manager"]
        if incident.severity in {IncidentSeverity.HIGH, IncidentSeverity.CRITICAL}:
            roles.extend(("executive_producer", "health_and_safety"))
        if incident.severity == IncidentSeverity.CRITICAL:
            roles.append("emergency_response")
        if incident.category == IncidentCategory.SAFEGUARDING:
            roles.append("safeguarding_lead")
        if incident.category == IncidentCategory.SECURITY:
            roles.append("security_lead")
        return tuple(dict.fromkeys(roles))

    def search(self, query: IncidentQuery | None = None) -> list[Incident]:
        selected = query or IncidentQuery()
        return [incident for incident in self.incidents if selected.matches(incident)]

    def timeline(self, incident_id: str) -> list[IncidentEvent]:
        self.require(incident_id)
        return [event for event in self._events if event.incident_id == incident_id]

    def metrics(self, *, at: datetime | None = None) -> IncidentMetrics:
        moment = at or self._now()
        incidents = list(self._incidents.values())
        triage_samples = [
            (incident.triaged_at - incident.reported_at).total_seconds() / 60
            for incident in incidents
            if incident.triaged_at is not None
        ]
        resolution_samples = [
            (incident.resolved_at - incident.reported_at).total_seconds() / 60
            for incident in incidents
            if incident.resolved_at is not None
        ]
        return IncidentMetrics(
            total=len(incidents),
            open=sum(incident.open for incident in incidents),
            overdue_triage=sum(
                incident.status == IncidentStatus.REPORTED
                and incident.triage_due_at is not None
                and incident.triage_due_at < moment
                for incident in incidents
            ),
            overdue_resolution=sum(
                incident.open
                and incident.resolution_due_at is not None
                and incident.resolution_due_at < moment
                for incident in incidents
            ),
            overdue_actions=sum(len(incident.overdue_actions(moment)) for incident in incidents),
            by_severity=dict(Counter(incident.severity.value for incident in incidents)),
            by_category=dict(Counter(incident.category.value for incident in incidents)),
            by_status=dict(Counter(incident.status.value for incident in incidents)),
            average_triage_minutes=(
                sum(triage_samples) / len(triage_samples) if triage_samples else None
            ),
            average_resolution_minutes=(
                sum(resolution_samples) / len(resolution_samples) if resolution_samples else None
            ),
        )

    def _require_action(self, incident: Incident, action_id: str) -> CorrectiveAction:
        for action in incident.actions:
            if action.id == action_id:
                return action
        raise NotFoundError(f"corrective action not found: {action_id}")

    def _replace_action(self, incident: Incident, action: CorrectiveAction) -> Incident:
        updated = replace(
            incident,
            actions=tuple(action if item.id == action.id else item for item in incident.actions),
        )
        self._incidents[incident.id] = updated
        return updated

    def _action_blockers(
        self,
        incident: Incident,
        action: CorrectiveAction,
    ) -> list[str]:
        return [
            required
            for required in action.requires
            if self._require_action(incident, required).status != ActionStatus.DONE
        ]

    def _validate_action_cycles(self, incident: Incident) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(action_id: str) -> None:
            if action_id in visiting:
                raise ValidationError("corrective action dependency cycle detected")
            if action_id in visited:
                return
            visiting.add(action_id)
            for required in self._require_action(incident, action_id).requires:
                visit(required)
            visiting.remove(action_id)
            visited.add(action_id)

        for action in incident.actions:
            visit(action.id)

    def _save(
        self,
        incident: Incident,
        kind: IncidentEventKind,
        actor: str,
        detail: str = "",
        action_id: str = "",
    ) -> Incident:
        self._incidents[incident.id] = incident
        self._record(incident.id, kind, actor, detail, action_id)
        return incident

    def _record(
        self,
        incident_id: str,
        kind: IncidentEventKind,
        actor: str,
        detail: str = "",
        action_id: str = "",
    ) -> IncidentEvent:
        event = IncidentEvent(
            sequence=len(self._events) + 1,
            incident_id=incident_id,
            kind=kind,
            occurred_at=self._now(),
            actor=_text(actor, "actor"),
            detail=detail.strip(),
            action_id=action_id,
        )
        self._events.append(event)
        return event

    @staticmethod
    def _require_active(incident: Incident) -> None:
        if not incident.open:
            raise WorkflowError("incident is not active")

    def _now(self) -> datetime:
        return _aware(self._clock(), "incident clock")
