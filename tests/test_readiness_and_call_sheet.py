from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lumenstage.domain.call_sheet import (
    CallAssignment,
    CallSheet,
    CallStatus,
    Contact,
    ContactChannel,
)
from lumenstage.domain.readiness import Evidence, ReadinessBoard, ReadinessItem, ReadinessState
from lumenstage.errors import ConflictError, NotFoundError, ValidationError, WorkflowError

NOW = datetime(2026, 12, 10, 12, tzinfo=UTC)


def evidence(identifier: str = "ev-1", **overrides: object) -> Evidence:
    values: dict[str, object] = {
        "id": identifier,
        "label": "Signed inspection",
        "reference": "docs/inspection.pdf",
        "submitted_by": "Safety officer",
        "submitted_at": NOW,
    }
    values.update(overrides)
    return Evidence(**values)  # type: ignore[arg-type]


@pytest.fixture()
def board() -> ReadinessBoard:
    result = ReadinessBoard("prod-1")
    result.add(
        ReadinessItem(
            "rigging",
            "safety",
            "Rigging inspection",
            "Technical director",
            weight=3,
            due_at=NOW + timedelta(days=1),
            minimum_evidence=1,
        )
    )
    result.add(
        ReadinessItem(
            "automation",
            "safety",
            "Automation sign-off",
            "Automation lead",
            requires=("rigging",),
            weight=2,
        )
    )
    result.add(
        ReadinessItem(
            "programme",
            "creative",
            "Programme proof",
            "Producer",
            blocking=False,
        )
    )
    return result


def test_evidence_validity_and_timezone_rules() -> None:
    item = evidence(expires_at=NOW + timedelta(days=1))
    assert item.valid_at(NOW)
    assert not item.valid_at(NOW + timedelta(days=2))
    with pytest.raises(ValidationError, match="follow submission"):
        evidence(expires_at=NOW)


def test_board_rejects_duplicates_and_missing_dependencies(board: ReadinessBoard) -> None:
    with pytest.raises(ConflictError, match="already exists"):
        board.add(ReadinessItem("rigging", "safety", "Again", "Owner"))
    with pytest.raises(ValidationError, match="missing"):
        board.add(ReadinessItem("x", "safety", "X", "Owner", requires=("unknown",)))


def test_add_all_rolls_back_if_a_later_item_is_invalid() -> None:
    board = ReadinessBoard("prod")
    with pytest.raises(ValidationError):
        board.add_all(
            [
                ReadinessItem("one", "ops", "One", "Owner"),
                ReadinessItem("two", "ops", "Two", "Owner", requires=("missing",)),
            ]
        )
    assert board.items == ()
    assert board.events == ()


def test_pass_requires_dependencies_and_evidence(board: ReadinessBoard) -> None:
    with pytest.raises(WorkflowError, match="evidence"):
        board.pass_item("rigging", "Director", decided_at=NOW)
    board.add_evidence("rigging", evidence(), "Safety officer")
    board.pass_item("rigging", "Director", decided_at=NOW)
    assert board.require("rigging").state == ReadinessState.PASSED
    board.pass_item("automation", "Director", decided_at=NOW)
    assert board.report(at=NOW).score == pytest.approx(5 / 6)


def test_expired_evidence_cannot_satisfy_item(board: ReadinessBoard) -> None:
    board.add_evidence(
        "rigging",
        evidence(expires_at=NOW + timedelta(hours=1)),
        "Safety officer",
    )
    with pytest.raises(WorkflowError, match="valid evidence"):
        board.pass_item("rigging", "Director", decided_at=NOW + timedelta(hours=2))


def test_dependencies_block_passing_and_filter_actionable(board: ReadinessBoard) -> None:
    with pytest.raises(WorkflowError, match="dependencies"):
        board.pass_item("automation", "Director", decided_at=NOW)
    assert board.actionable_for("Automation lead") == []
    assert [item.id for item in board.actionable_for("Technical Director")] == ["rigging"]


def test_blocking_waiver_requires_authorization(board: ReadinessBoard) -> None:
    with pytest.raises(WorkflowError, match="authorization"):
        board.waive("rigging", "Producer", "inspection unavailable")
    waived = board.waive(
        "rigging",
        "Producer",
        "inspection accepted under venue certificate",
        authorized=True,
    )
    assert waived.state == ReadinessState.WAIVED
    board.waive("programme", "Producer", "late copy")


def test_reopen_prevents_invalidating_satisfied_dependants(board: ReadinessBoard) -> None:
    board.add_evidence("rigging", evidence(), "Safety")
    board.pass_item("rigging", "Director", decided_at=NOW)
    board.pass_item("automation", "Director", decided_at=NOW)
    with pytest.raises(ConflictError, match="dependent"):
        board.reopen("rigging", "Director", "new inspection")
    board.reopen("automation", "Director", "new configuration")
    reopened = board.reopen("rigging", "Director", "new inspection")
    assert reopened.state == ReadinessState.IN_PROGRESS


def test_failure_assignment_and_event_history(board: ReadinessBoard) -> None:
    failed = board.fail_item("programme", "Producer", "printer missed deadline")
    assert failed.state == ReadinessState.FAILED
    assigned = board.assign("programme", "Marketing", "Producer")
    assert assigned.owner == "Marketing"
    assert [event.sequence for event in board.events] == list(range(1, len(board.events) + 1))


def test_report_lists_blockers_overdue_and_expired_evidence(board: ReadinessBoard) -> None:
    board.add_evidence(
        "rigging",
        evidence(expires_at=NOW + timedelta(hours=1)),
        "Safety",
    )
    report = board.report(at=NOW + timedelta(days=2))
    assert not report.gate_open
    assert report.blockers == ("automation", "rigging")
    assert report.overdue == ("rigging",)
    assert report.expired_evidence == ("rigging:ev-1",)
    safety = next(item for item in report.categories if item.category == "safety")
    assert safety.blocking_open == 2


def test_empty_board_is_ready() -> None:
    report = ReadinessBoard("prod").report(at=NOW)
    assert report.gate_open
    assert report.score == 1.0


PERFORMANCE = datetime(2026, 12, 20, 19, 30, tzinfo=UTC)


@pytest.fixture()
def call_sheet() -> CallSheet:
    sheet = CallSheet(
        "prod-1",
        "perf-1",
        PERFORMANCE,
        "Main Theatre",
        access_at=PERFORMANCE - timedelta(hours=6),
    )
    sheet.add_contact(Contact("actor", "Alex Actor", "alex@example.com"))
    sheet.add_contact(
        Contact(
            "lx",
            "Lee Lighting",
            phone="+44123456789",
            preferred_channel=ContactChannel.SMS,
        )
    )
    sheet.add_call(
        CallAssignment(
            "call-actor",
            "actor",
            "Hamlet",
            "cast",
            PERFORMANCE - timedelta(hours=2),
            "Dressing Room 1",
        )
    )
    sheet.add_call(
        CallAssignment(
            "call-lx",
            "lx",
            "Board operator",
            "lighting",
            PERFORMANCE - timedelta(hours=3),
            "Control room",
        )
    )
    return sheet


def test_contact_requires_destination_for_preferred_channel() -> None:
    with pytest.raises(ValidationError, match="email"):
        Contact("p", "Person")
    with pytest.raises(ValidationError, match="phone"):
        Contact("p", "Person", "p@example.com", preferred_channel=ContactChannel.SMS)


def test_call_sheet_validates_access_and_call_window() -> None:
    with pytest.raises(ValidationError, match="access_at"):
        CallSheet("p", "x", PERFORMANCE, "Venue", access_at=PERFORMANCE + timedelta(hours=1))
    sheet = CallSheet("p", "x", PERFORMANCE, "Venue")
    sheet.add_contact(Contact("p", "Person", "p@example.com"))
    with pytest.raises(ValidationError, match="follow performance"):
        sheet.add_call(CallAssignment("c", "p", "Role", "cast", PERFORMANCE + timedelta(1), "X"))


def test_calls_require_contacts_and_unique_identity(call_sheet: CallSheet) -> None:
    with pytest.raises(NotFoundError, match="contact"):
        call_sheet.add_call(
            CallAssignment("missing", "nobody", "Role", "cast", PERFORMANCE, "Stage")
        )
    with pytest.raises(ConflictError, match="already exists"):
        call_sheet.add_call(call_sheet.require_call("call-actor"))


def test_publish_creates_immutable_revision_and_dispatches(call_sheet: CallSheet) -> None:
    first = call_sheet.publish("Company manager", at=NOW)
    assert first.revision == 1
    call_sheet.change_location("call-actor", "Stage Door", "Company manager")
    second = call_sheet.publish("Company manager", at=NOW + timedelta(minutes=5))
    assert second.revision == 2
    assert first.calls[1].location == "Dressing Room 1"
    dispatches = {item.person_id: item for item in call_sheet.dispatches()}
    assert dispatches["actor"].destination == "alex@example.com"
    assert dispatches["lx"].channel == ContactChannel.SMS


def test_dispatch_requires_publication(call_sheet: CallSheet) -> None:
    with pytest.raises(WorkflowError, match="publish"):
        call_sheet.dispatches()
    with pytest.raises(NotFoundError, match="not been published"):
        call_sheet.snapshot()


def test_acknowledgement_is_person_bound(call_sheet: CallSheet) -> None:
    with pytest.raises(WorkflowError, match="called person"):
        call_sheet.acknowledge("call-actor", "lx", at=NOW)
    call = call_sheet.acknowledge("call-actor", "actor", at=NOW)
    assert call.status == CallStatus.ACKNOWLEDGED
    with pytest.raises(WorkflowError, match="cannot acknowledge"):
        call_sheet.acknowledge("call-actor", "actor", at=NOW)


def test_arrival_tracks_lateness_and_report(call_sheet: CallSheet) -> None:
    call_sheet.acknowledge("call-actor", "actor", at=NOW)
    arrival = call_sheet.mark_arrived(
        "call-actor",
        "Stage door",
        at=PERFORMANCE - timedelta(hours=1, minutes=50),
    )
    assert arrival.late_by() == timedelta(minutes=10)
    report = call_sheet.report()
    assert report.acknowledged == 1
    assert report.arrived == 1
    assert report.late == ("call-actor",)
    assert report.unacknowledged == ("call-lx",)


def test_excused_call_cannot_arrive_and_is_not_dispatched(call_sheet: CallSheet) -> None:
    call_sheet.excuse("call-lx", "Manager", "cover arranged")
    with pytest.raises(WorkflowError, match="excused"):
        call_sheet.mark_arrived("call-lx", "Door", at=NOW)
    call_sheet.publish("Manager", at=NOW)
    assert [item.person_id for item in call_sheet.dispatches()] == ["actor"]


def test_reschedule_resets_acknowledgement(call_sheet: CallSheet) -> None:
    call_sheet.acknowledge("call-actor", "actor", at=NOW)
    updated = call_sheet.reschedule(
        "call-actor",
        PERFORMANCE - timedelta(hours=2, minutes=30),
        "Manager",
    )
    assert updated.status == CallStatus.CALLED
    assert updated.acknowledged_at is None
    assert call_sheet.changes[-1].field == "call_at"


def test_call_waves_and_department_filter(call_sheet: CallSheet) -> None:
    waves = call_sheet.call_waves(minutes=30)
    assert [wave for wave, _ in waves] == [
        PERFORMANCE - timedelta(hours=3),
        PERFORMANCE - timedelta(hours=2),
    ]
    assert [call.id for call in call_sheet.by_department("CAST")] == ["call-actor"]
    with pytest.raises(ValidationError, match="positive"):
        call_sheet.call_waves(minutes=0)


def test_empty_sheet_cannot_be_published() -> None:
    sheet = CallSheet("p", "perf", PERFORMANCE, "Venue")
    with pytest.raises(WorkflowError, match="empty"):
        sheet.publish("Manager", at=NOW)
