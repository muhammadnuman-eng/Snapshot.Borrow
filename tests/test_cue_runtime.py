from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lumenstage.domain.cue_engine import (
    Cue,
    CueEventKind,
    CueKind,
    CueRuntime,
    CueSheet,
    CueState,
)
from lumenstage.errors import ConflictError, NotFoundError, ValidationError, WorkflowError


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 2, 19, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, milliseconds: int) -> None:
        self.value += timedelta(milliseconds=milliseconds)


@pytest.fixture()
def sheet() -> CueSheet:
    return CueSheet(
        "prod-hamlet",
        [
            Cue(1, "lights", "House to half", kind=CueKind.LIGHT),
            Cue(
                2,
                "sound",
                "Play preshow sting",
                kind=CueKind.SOUND,
                requires=(1,),
                duration_ms=1800,
                auto_follow_ms=2000,
            ),
            Cue(3, "fly", "Lower chandelier", kind=CueKind.FLY, requires=(2,), critical=True),
        ],
    )


@pytest.fixture()
def clock() -> Clock:
    return Clock()


@pytest.fixture()
def runtime(sheet: CueSheet, clock: Clock) -> CueRuntime:
    return CueRuntime(sheet, clock=clock)


def test_cue_validates_identity_duration_and_dependencies() -> None:
    with pytest.raises(ValidationError, match="positive"):
        Cue(0, "sound", "Go")
    with pytest.raises(ValidationError, match="non-empty"):
        Cue(1, "", "Go")
    with pytest.raises(ValidationError, match="duration"):
        Cue(1, "sound", "Go", duration_ms=-1)
    with pytest.raises(ValidationError, match="itself"):
        Cue(1, "sound", "Go", requires=(1,))
    assert Cue(1, " Sound ", " Go ").department == "sound"


def test_sheet_preserves_legacy_add_filter_and_serialization() -> None:
    sheet = CueSheet("prod")
    cue = sheet.add(2, " Sound ", "Thunder", page="12")
    sheet.add(1, "lights", "Blackout", kind="light")
    assert cue.label == "SOUND 2"
    assert sheet.next_number() == 3
    assert sheet.by_department("SOUND") == [cue]
    assert sheet.by_kind(CueKind.LIGHT)[0].number == 1
    assert sheet.to_dict()["cues"][1]["page"] == "12"


def test_sheet_rejects_missing_and_cyclic_dependencies() -> None:
    with pytest.raises(ValidationError, match="missing dependencies"):
        CueSheet("prod", [Cue(2, "sound", "Go", requires=(1,))])
    first = Cue(1, "sound", "One", requires=(2,))
    second = Cue(2, "sound", "Two", requires=(1,))
    with pytest.raises(ValidationError, match="cycle"):
        CueSheet("prod", [first, second])


def test_sheet_renumber_updates_dependants(sheet: CueSheet) -> None:
    sheet.renumber(2, 20)
    assert sheet.require(3).requires == (20,)
    assert [cue.number for cue in sheet.dependency_order()] == [1, 20, 3]
    with pytest.raises(ConflictError, match="already exists"):
        sheet.renumber(20, 1)


def test_sheet_prevents_removing_required_cue(sheet: CueSheet) -> None:
    with pytest.raises(ConflictError, match="required by"):
        sheet.remove(2)
    with pytest.raises(NotFoundError):
        sheet.require(99)


def test_runtime_requires_start_and_records_order(runtime: CueRuntime) -> None:
    with pytest.raises(WorkflowError, match="not active"):
        runtime.standby(1, "SM")
    runtime.start("SM")
    runtime.standby(1, "SM")
    runtime.go(1, "SM")
    runtime.complete(1, "Board op")
    assert runtime.state(1) == CueState.COMPLETED
    assert [event.kind for event in runtime.events] == [
        CueEventKind.RUN_STARTED,
        CueEventKind.STANDBY,
        CueEventKind.GO,
        CueEventKind.COMPLETED,
    ]
    assert [event.sequence for event in runtime.events] == [1, 2, 3, 4]


def test_dependency_blocks_standby_until_predecessor_finishes(runtime: CueRuntime) -> None:
    runtime.start("SM")
    with pytest.raises(WorkflowError, match="blocked"):
        runtime.standby(2, "SM")
    runtime.standby(1, "SM")
    runtime.go(1, "SM")
    runtime.complete(1, "LX")
    runtime.standby(2, "SM")
    assert runtime.state(2) == CueState.STANDBY


def test_critical_cue_requires_safety_arm(runtime: CueRuntime) -> None:
    runtime.start("SM")
    for number in (1, 2):
        runtime.standby(number, "SM")
        runtime.go(number, "SM")
        runtime.complete(number, "operator")
    runtime.standby(3, "SM")
    with pytest.raises(WorkflowError, match="must be armed"):
        runtime.go(3, "SM")
    runtime.arm(3, "Head flyman", detail="deck clear")
    runtime.go(3, "SM")
    assert runtime.state(3) == CueState.FIRED
    assert CueEventKind.ARMED in [event.kind for event in runtime.events]


def test_noncritical_cue_cannot_be_armed(runtime: CueRuntime) -> None:
    runtime.start("SM")
    with pytest.raises(WorkflowError, match="does not require"):
        runtime.arm(1, "SM")
    with pytest.raises(WorkflowError, match="not armed"):
        runtime.disarm(3, "SM")


def test_failure_and_skip_require_valid_transitions(runtime: CueRuntime) -> None:
    runtime.start("SM")
    with pytest.raises(WorkflowError, match="cannot fail"):
        runtime.fail(1, "LX", "console offline")
    runtime.standby(1, "SM")
    runtime.fail(1, "LX", "console offline")
    assert runtime.state(1) == CueState.FAILED
    with pytest.raises(ValidationError, match="at least"):
        runtime.skip(3, "SM", "no")
    runtime.skip(3, "SM", "automation isolated")
    assert runtime.state(3) == CueState.SKIPPED


def test_skipped_dependency_allows_dependant(runtime: CueRuntime) -> None:
    runtime.start("SM")
    runtime.skip(1, "SM", "operator decision")
    assert [cue.number for cue in runtime.ready_cues()] == [2]


def test_force_go_bypasses_standby_but_not_critical_arm(runtime: CueRuntime) -> None:
    runtime.start("SM")
    runtime.go(1, "SM", force=True)
    assert runtime.state(1) == CueState.FIRED
    with pytest.raises(WorkflowError, match="armed"):
        runtime.go(3, "SM", force=True)


def test_auto_follow_fires_next_cue_after_delay(runtime: CueRuntime, clock: Clock) -> None:
    runtime.start("SM")
    runtime.skip(1, "SM", "start at sound cue")
    runtime.standby(2, "SM")
    runtime.go(2, "SM")
    clock.advance(1999)
    assert runtime.process_auto_follows("SM") == []
    clock.advance(1)
    runtime.arm(3, "Fly captain")
    assert runtime.process_auto_follows("SM") == [3]
    assert runtime.state(3) == CueState.FIRED


def test_complete_records_elapsed_time(runtime: CueRuntime, clock: Clock) -> None:
    runtime.start("SM")
    runtime.standby(1, "SM")
    runtime.go(1, "SM")
    clock.advance(725)
    runtime.complete(1, "LX")
    completed = runtime.event_log(kinds=[CueEventKind.COMPLETED])[0]
    assert completed.elapsed_ms == 725


def test_reset_requires_cascade_after_dependants_progress(runtime: CueRuntime) -> None:
    runtime.start("SM")
    for number in (1, 2):
        runtime.standby(number, "SM")
        runtime.go(number, "SM")
        runtime.complete(number, "operator")
    with pytest.raises(ConflictError, match="progressed"):
        runtime.reset(1, "SM")
    assert runtime.reset(1, "SM", cascade=True) == [1, 2, 3]
    assert all(runtime.state(number) == CueState.PENDING for number in (1, 2, 3))


def test_snapshot_restores_runtime_state(
    sheet: CueSheet, runtime: CueRuntime, clock: Clock
) -> None:
    runtime.start("SM")
    runtime.standby(1, "SM")
    snapshot = runtime.snapshot()
    recovered = CueRuntime(sheet, clock=clock)
    recovered.restore(snapshot)
    assert recovered.running
    assert recovered.state(1) == CueState.STANDBY
    assert recovered.snapshot().to_dict()["production_id"] == "prod-hamlet"


def test_snapshot_rejects_wrong_production(runtime: CueRuntime) -> None:
    runtime.start("SM")
    other = CueRuntime(CueSheet("other"))
    with pytest.raises(ValidationError, match="different production"):
        other.restore(runtime.snapshot())


def test_end_requires_terminal_cues_and_builds_report(runtime: CueRuntime) -> None:
    runtime.start("SM")
    with pytest.raises(WorkflowError, match="unfinished"):
        runtime.end("SM")
    runtime.skip(1, "SM", "cancelled sequence")
    runtime.skip(2, "SM", "cancelled sequence")
    runtime.skip(3, "SM", "automation cancelled")
    report = runtime.end("SM")
    assert report.successful
    assert report.completion_ratio == 1.0
    assert report.pending == 0
    assert report.event_count == 5


def test_failed_critical_cue_marks_report_unsuccessful(runtime: CueRuntime) -> None:
    runtime.start("SM")
    runtime.arm(3, "Fly")
    runtime.go(3, "SM", force=True)
    runtime.fail(3, "Fly", "travel limit fault")
    report = runtime.end("SM", allow_incomplete=True)
    assert not report.successful
    assert report.critical_failures == (3,)


def test_notes_and_event_filters(runtime: CueRuntime) -> None:
    runtime.start("SM")
    runtime.note("SM", "hold for applause", cue_number=1)
    runtime.note("Director", "continue", cue_number=1)
    notes = runtime.event_log(cue_number=1, kinds=[CueEventKind.NOTE], operator="SM")
    assert len(notes) == 1
    assert notes[0].detail == "hold for applause"


def test_runtime_rejects_naive_clock(sheet: CueSheet) -> None:
    runtime = CueRuntime(sheet, clock=lambda: datetime(2026, 10, 2, 19))
    with pytest.raises(ValidationError, match="timezone-aware"):
        runtime.start("SM")
