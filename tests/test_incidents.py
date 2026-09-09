from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lumenstage.domain.incidents import (
    ActionStatus,
    CorrectiveAction,
    IncidentAttachment,
    IncidentCategory,
    IncidentDesk,
    IncidentQuery,
    IncidentSeverity,
    IncidentStatus,
    Witness,
)
from lumenstage.errors import ConflictError, NotFoundError, ValidationError, WorkflowError

NOW = datetime(2027, 2, 1, 12, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        value = self.value
        self.value += timedelta(seconds=1)
        return value


@pytest.fixture()
def desk() -> IncidentDesk:
    return IncidentDesk(clock=Clock())


def report(desk: IncidentDesk, **overrides: object):
    values: dict[str, object] = {
        "incident_id": "inc-1",
        "production_id": "prod-1",
        "title": "Cable trip",
        "description": "Loose cable crossed stage-left access",
        "category": IncidentCategory.NEAR_MISS,
        "severity": IncidentSeverity.MODERATE,
        "occurred_at": NOW - timedelta(minutes=10),
        "reported_by": "Stage manager",
        "location": "Stage left",
        "reported_at": NOW,
    }
    values.update(overrides)
    return desk.report(**values)  # type: ignore[arg-type]


def action(identifier: str, **overrides: object) -> CorrectiveAction:
    values: dict[str, object] = {
        "id": identifier,
        "title": "Secure cable route",
        "owner": "Technical manager",
        "due_at": NOW + timedelta(hours=4),
    }
    values.update(overrides)
    return CorrectiveAction(**values)  # type: ignore[arg-type]


def test_report_sets_sla_deadlines_and_rejects_future_occurrence(desk: IncidentDesk) -> None:
    incident = report(desk)
    assert incident.status == IncidentStatus.REPORTED
    assert incident.triage_due_at == NOW + timedelta(hours=8)
    assert incident.resolution_due_at == NOW + timedelta(days=7)
    with pytest.raises(ValidationError, match="cannot follow"):
        report(desk, incident_id="future", occurred_at=NOW + timedelta(minutes=1))


def test_duplicate_and_missing_incidents_raise_domain_errors(desk: IncidentDesk) -> None:
    report(desk)
    with pytest.raises(ConflictError, match="already exists"):
        report(desk)
    with pytest.raises(NotFoundError, match="not found"):
        desk.require("missing")


def test_triage_assigns_lead_and_can_change_severity(desk: IncidentDesk) -> None:
    report(desk)
    incident = desk.triage("inc-1", "Safety lead", "Producer", severity=IncidentSeverity.HIGH)
    assert incident.lead == "Safety lead"
    assert incident.status == IncidentStatus.TRIAGED
    assert incident.resolution_due_at == NOW + timedelta(days=3)
    with pytest.raises(WorkflowError, match="cannot triage"):
        desk.triage("inc-1", "Other", "Producer")


def test_witness_attachment_and_update_are_recorded(desk: IncidentDesk) -> None:
    report(desk)
    witness = Witness("w1", "Alex", statement="I saw it", statement_at=NOW)
    desk.add_witness("inc-1", witness, "Safety")
    attachment = IncidentAttachment(
        "a1", "Photo", "evidence/photo.jpg", "image/jpeg", "Safety", NOW, "a" * 64
    )
    incident = desk.add_attachment("inc-1", attachment, "Safety")
    desk.add_update("inc-1", "Safety", "Area isolated")
    assert incident.witnesses == (witness,)
    assert incident.attachments == (attachment,)
    assert len(desk.timeline("inc-1")) == 4


def test_action_dependencies_control_start_and_completion(desk: IncidentDesk) -> None:
    report(desk)
    desk.add_action("inc-1", action("isolate"), "Safety")
    desk.add_action("inc-1", action("repair", requires=("isolate",)), "Safety")
    with pytest.raises(WorkflowError, match="blocked"):
        desk.start_action("inc-1", "repair", "Technician")
    desk.complete_action("inc-1", "isolate", "Technician", "Cable isolated", at=NOW)
    started = desk.start_action("inc-1", "repair", "Technician")
    assert started.status == ActionStatus.IN_PROGRESS


def test_action_rejects_missing_dependency_and_duplicate(desk: IncidentDesk) -> None:
    report(desk)
    with pytest.raises(ValidationError, match="missing"):
        desk.add_action("inc-1", action("repair", requires=("unknown",)), "Safety")
    desk.add_action("inc-1", action("repair"), "Safety")
    with pytest.raises(ConflictError, match="already exists"):
        desk.add_action("inc-1", action("repair"), "Safety")


def test_blocking_action_requires_completion_before_resolution(desk: IncidentDesk) -> None:
    report(desk)
    desk.triage("inc-1", "Safety", "Producer")
    desk.add_action("inc-1", action("repair"), "Safety")
    with pytest.raises(WorkflowError, match="remain open"):
        desk.resolve("inc-1", "Safety", "Cable route corrected")
    desk.complete_action("inc-1", "repair", "Tech", "Cable secured", at=NOW)
    resolved = desk.resolve("inc-1", "Safety", "Cable route corrected", at=NOW)
    assert resolved.status == IncidentStatus.RESOLVED


def test_high_severity_resolution_requires_root_cause(desk: IncidentDesk) -> None:
    report(desk, severity=IncidentSeverity.CRITICAL)
    desk.triage("inc-1", "Safety", "Producer")
    with pytest.raises(ValidationError, match="root_cause"):
        desk.resolve("inc-1", "Safety", "Risk removed")
    resolved = desk.resolve(
        "inc-1",
        "Safety",
        "Risk removed",
        root_cause="Incorrect rigging procedure",
        at=NOW,
    )
    assert resolved.root_cause == "Incorrect rigging procedure"


def test_injury_requires_regulatory_reference_before_closure(desk: IncidentDesk) -> None:
    report(desk, category=IncidentCategory.INJURY)
    desk.triage("inc-1", "Safety", "Producer")
    desk.resolve("inc-1", "Safety", "First aid complete", at=NOW)
    with pytest.raises(WorkflowError, match="regulatory"):
        desk.close("inc-1", "Producer")
    desk.reopen("inc-1", "Producer", "add regulatory filing")
    desk.resolve(
        "inc-1",
        "Safety",
        "First aid complete",
        regulatory_reference="RIDDOR-123",
        at=NOW,
    )
    assert desk.close("inc-1", "Producer", at=NOW).status == IncidentStatus.CLOSED


def test_blocking_action_cancellation_requires_authorization(desk: IncidentDesk) -> None:
    report(desk)
    desk.add_action("inc-1", action("repair"), "Safety")
    with pytest.raises(WorkflowError, match="authorization"):
        desk.cancel_action("inc-1", "repair", "Producer", "not needed")
    cancelled = desk.cancel_action(
        "inc-1", "repair", "Producer", "venue repair accepted", authorized=True
    )
    assert cancelled.status == ActionStatus.CANCELLED


def test_escalations_cover_triage_resolution_and_actions(desk: IncidentDesk) -> None:
    report(desk, severity=IncidentSeverity.CRITICAL)
    desk.add_action("inc-1", action("repair", due_at=NOW + timedelta(minutes=5)), "Safety")
    escalations = desk.escalations(at=NOW + timedelta(days=2))
    assert {item.reason for item in escalations} == {
        "triage overdue",
        "corrective action overdue: repair",
    }
    assert "emergency_response" in escalations[0].recipients


def test_search_filters_status_severity_location_and_text(desk: IncidentDesk) -> None:
    report(desk)
    report(
        desk,
        incident_id="inc-2",
        title="Smoke detector",
        description="Detector alarmed",
        category=IncidentCategory.FIRE,
        severity=IncidentSeverity.HIGH,
        location="Auditorium",
    )
    results = desk.search(
        IncidentQuery(
            severities=frozenset({IncidentSeverity.HIGH}),
            categories=frozenset({IncidentCategory.FIRE}),
            statuses=frozenset({IncidentStatus.REPORTED}),
            location="auditorium",
            text="smoke",
        )
    )
    assert [item.id for item in results] == ["inc-2"]


def test_metrics_calculate_counts_and_response_times(desk: IncidentDesk) -> None:
    report(desk)
    desk.triage("inc-1", "Safety", "Producer", at=NOW + timedelta(minutes=30))
    desk.resolve("inc-1", "Safety", "Route corrected", at=NOW + timedelta(hours=2))
    metrics = desk.metrics(at=NOW + timedelta(hours=3))
    assert metrics.total == 1
    assert metrics.open == 0
    assert metrics.average_triage_minutes == 30
    assert metrics.average_resolution_minutes == 120
    assert metrics.by_severity == {"moderate": 1}


def test_notification_roles_reflect_category_and_severity(desk: IncidentDesk) -> None:
    report(
        desk,
        severity=IncidentSeverity.CRITICAL,
        category=IncidentCategory.SAFEGUARDING,
    )
    roles = desk.notification_roles("inc-1")
    assert "health_and_safety" in roles
    assert "emergency_response" in roles
    assert "safeguarding_lead" in roles


def test_naive_incident_clock_is_rejected() -> None:
    desk = IncidentDesk(clock=lambda: datetime(2027, 1, 1))
    with pytest.raises(ValidationError, match="timezone-aware"):
        desk.report(
            "i",
            "p",
            "Title",
            "Description",
            IncidentCategory.OTHER,
            IncidentSeverity.LOW,
            NOW,
            "Reporter",
            "Stage",
        )
