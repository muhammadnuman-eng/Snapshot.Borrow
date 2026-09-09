"""Behavioral tests for persisted production day packs."""

from __future__ import annotations

from pathlib import Path

import pytest

from lumenstage.errors import ConflictError, NotFoundError, ValidationError
from lumenstage.services.day_pack import DayPackService
from lumenstage.services.performance import PerformanceService
from lumenstage.services.production import ProductionService
from lumenstage.services.prop_asset import PropAssetService
from lumenstage.services.rehearsal_slot import RehearsalSlotService
from lumenstage.services.role_track import RoleTrackService
from lumenstage.services.sound_cue import SoundCueService
from lumenstage.storage.store import JsonDocumentStore

PACK_DATE = "2021-03-15"
OTHER_DATE = "2021-03-16"
EVENING_START = "2021-03-15T19:30:00+00:00"
MATINEE_START = "2021-03-15T14:00:00+00:00"
NEXT_DAY_START = "2021-03-16T01:00:00+00:00"
REHEARSAL_START = "2021-03-15T10:00:00+00:00"
REHEARSAL_END = "2021-03-15T12:00:00+00:00"
MIDNIGHT_REHEARSAL_START = "2021-03-15T23:00:00+00:00"
MIDNIGHT_REHEARSAL_END = "2021-03-16T01:30:00+00:00"


@pytest.fixture()
def store(tmp_path: Path) -> JsonDocumentStore:
    return JsonDocumentStore(tmp_path / "store.json")


@pytest.fixture()
def service(store: JsonDocumentStore) -> DayPackService:
    return DayPackService(store)


def _gap_codes(pack) -> set[str]:
    return {gap["code"] for gap in pack.gaps}


def _warning_codes(pack) -> set[str]:
    return {warning["code"] for warning in pack.warnings}


def seed_production(
    store: JsonDocumentStore,
    *,
    slug: str = "hamlet",
    timezone: str | None = None,
):
    metadata = {
        "venue_id": "VEN-1",
        "stage": "preview",
        "director_id": "DIR-1",
        "opens_at": "2021-03-01T00:00:00+00:00",
        "closes_at": "2021-03-31T00:00:00+00:00",
    }
    if timezone is not None:
        metadata["timezone"] = timezone
    return ProductionService(store).create("Hamlet", slug, metadata=metadata)


def add_performance(
    store: JsonDocumentStore,
    production_id: str,
    *,
    slug: str,
    starts_at: str | None = EVENING_START,
    status: str = "active",
):
    service = PerformanceService(store)
    item = service.create(
        slug.replace("-", " ").title(),
        slug,
        metadata={
            "production_id": production_id,
            "starts_at": starts_at,
            "capacity": 200,
            "sold": 20,
            "held": 10,
        },
    )
    if status != "active":
        service.update(item.id, status=status)
        item = service.get(item.id)
    return item


def add_rehearsal(
    store: JsonDocumentStore,
    production_id: str,
    *,
    slug: str,
    room_id: str,
    starts_at: str,
    ends_at: str,
    participant_ids: list[str] | None = None,
    status: str = "active",
):
    service = RehearsalSlotService(store)
    item = service.create(
        slug.replace("-", " ").title(),
        slug,
        metadata={
            "production_id": production_id,
            "room_id": room_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "participant_ids": participant_ids or [],
        },
    )
    if status != "active":
        service.update(item.id, status=status)
        item = service.get(item.id)
    return item


def add_sound_cue(
    store: JsonDocumentStore,
    production_id: str,
    *,
    slug: str,
    cue_number: int,
    ready: bool = True,
    status: str = "active",
):
    service = SoundCueService(store)
    item = service.create(
        slug.replace("-", " ").title(),
        slug,
        metadata={
            "production_id": production_id,
            "cue_number": cue_number,
            "trigger": "fade",
            "asset_id": "AUD-1",
            "ready": ready,
        },
    )
    if status != "active":
        service.update(item.id, status=status)
        item = service.get(item.id)
    return item


def add_role_track(
    store: JsonDocumentStore,
    production_id: str,
    *,
    slug: str,
    role_name: str,
    primary_cast_id: str = "",
    understudy_ids: list[str] | None = None,
    status: str = "active",
):
    service = RoleTrackService(store)
    metadata = {
        "production_id": production_id,
        "role_name": role_name,
        "primary_cast_id": primary_cast_id,
        "understudy_ids": understudy_ids or [],
    }
    item = service.create(role_name, slug, metadata=metadata)
    if status != "active":
        service.update(item.id, status=status)
        item = service.get(item.id)
    return item


def add_prop_asset(
    store: JsonDocumentStore,
    production_id: str,
    *,
    slug: str,
    condition: str = "good",
    status: str = "active",
):
    service = PropAssetService(store)
    item = service.create(
        slug.replace("-", " ").title(),
        slug,
        metadata={"production_id": production_id, "condition": condition, "location": "dock"},
    )
    if status != "active":
        service.update(item.id, status=status)
        item = service.get(item.id)
    return item


def seed_rich_day(store: JsonDocumentStore, production_id: str) -> None:
    add_performance(store, production_id, slug="evening", starts_at=EVENING_START)
    add_performance(store, production_id, slug="matinee", starts_at=MATINEE_START)
    add_rehearsal(
        store,
        production_id,
        slug="tech",
        room_id="room-main",
        starts_at=REHEARSAL_START,
        ends_at=REHEARSAL_END,
        participant_ids=["CST-1"],
    )
    add_sound_cue(store, production_id, slug="cue-two", cue_number=2, ready=False)
    add_sound_cue(store, production_id, slug="cue-one", cue_number=1, ready=True)
    add_role_track(
        store,
        production_id,
        slug="hamlet-role",
        role_name="Hamlet",
        primary_cast_id="CST-1",
        understudy_ids=["CST-2"],
    )
    add_role_track(
        store,
        production_id,
        slug="ghost-role",
        role_name="Ghost",
        primary_cast_id="",
    )
    add_prop_asset(store, production_id, slug="throne", condition="repair")


def test_first_build_creates_version_one_draft(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    pack, created = service.build(production.id, PACK_DATE)
    assert created is True
    assert pack.status == "draft"
    assert pack.version == 1
    assert pack.production_id == production.id
    assert pack.date == PACK_DATE
    assert pack.published_at is None


def test_rebuild_preserves_pack_id_and_increments_version(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    first, _ = service.build(production.id, PACK_DATE)
    add_performance(store, production.id, slug="evening", starts_at=EVENING_START)
    second, created = service.build(production.id, PACK_DATE)
    assert created is False
    assert second.id == first.id
    assert second.version == 2
    assert len(second.performances) == 1


def test_different_dates_create_separate_packs(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    first, _ = service.build(production.id, PACK_DATE)
    second, created = service.build(production.id, OTHER_DATE)
    assert created is True
    assert second.id != first.id
    assert second.date == OTHER_DATE


def test_unknown_production_raises_not_found(service: DayPackService) -> None:
    with pytest.raises(NotFoundError, match="production"):
        service.build("PRD-missing", PACK_DATE)


def test_invalid_date_format_raises_validation_error(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        service.build(production.id, "15-09-2026")
    with pytest.raises(ValidationError, match="valid calendar day"):
        service.build(production.id, "2021-02-30")


def test_empty_schedule_produces_empty_schedule_gap(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    pack, _ = service.build(production.id, PACK_DATE)
    assert "empty_schedule" in _gap_codes(pack)
    assert pack.performances == []
    assert pack.rehearsals == []


def test_archived_child_records_are_excluded(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    performance = add_performance(store, production.id, slug="evening", status="archived")
    rehearsal = add_rehearsal(
        store,
        production.id,
        slug="archived-tech",
        room_id="room-a",
        starts_at=REHEARSAL_START,
        ends_at=REHEARSAL_END,
        status="archived",
    )
    pack, _ = service.build(production.id, PACK_DATE)
    assert performance.id not in {row["id"] for row in pack.performances}
    assert rehearsal.id not in {row["id"] for row in pack.rehearsals}
    assert "empty_schedule" in _gap_codes(pack)


def test_production_id_linking_excludes_unrelated_catalog_rows(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    other = seed_production(store, slug="macbeth")
    add_performance(store, production.id, slug="evening", starts_at=EVENING_START)
    add_performance(store, other.id, slug="other-show", starts_at=EVENING_START)
    add_sound_cue(store, other.id, slug="other-cue", cue_number=1)
    pack, _ = service.build(production.id, PACK_DATE)
    performance_ids = {row["id"] for row in pack.performances}
    cue_ids = {row["id"] for row in pack.sound_cues}
    assert len(performance_ids) == 1
    assert len(cue_ids) == 0


def test_performances_selected_by_utc_calendar_day_boundary(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    evening = add_performance(store, production.id, slug="evening", starts_at=EVENING_START)
    add_performance(store, production.id, slug="next-day", starts_at=NEXT_DAY_START)
    pack, _ = service.build(production.id, PACK_DATE)
    assert [row["id"] for row in pack.performances] == [evening.id]


def test_performance_without_starts_at_is_excluded(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    missing = PerformanceService(store).create(
        "Untimed",
        "untimed",
        metadata={"production_id": production.id, "capacity": 50},
    )
    add_rehearsal(
        store,
        production.id,
        slug="tech",
        room_id="room-main",
        starts_at=REHEARSAL_START,
        ends_at=REHEARSAL_END,
    )
    pack, _ = service.build(production.id, PACK_DATE)
    assert missing.id not in {row["id"] for row in pack.performances}
    assert len(pack.rehearsals) == 1


def test_timezone_day_boundary_uses_production_timezone_when_available(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    pytest.importorskip("tzdata")
    production = seed_production(store, timezone="America/New_York")
    late_night = add_performance(
        store,
        production.id,
        slug="late",
        starts_at="2021-03-15T03:30:00+00:00",
    )
    evening = add_performance(store, production.id, slug="evening", starts_at=EVENING_START)
    pack, _ = service.build(production.id, PACK_DATE)
    performance_ids = {row["id"] for row in pack.performances}
    assert evening.id in performance_ids
    assert late_night.id not in performance_ids
    assert pack.timezone == "America/New_York"


def test_rehearsal_intersecting_midnight_is_included(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    rehearsal = add_rehearsal(
        store,
        production.id,
        slug="late-tech",
        room_id="room-main",
        starts_at=MIDNIGHT_REHEARSAL_START,
        ends_at=MIDNIGHT_REHEARSAL_END,
    )
    pack, _ = service.build(production.id, PACK_DATE)
    assert [row["id"] for row in pack.rehearsals] == [rehearsal.id]


def test_non_overlapping_rehearsals_do_not_emit_conflict_warning(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    add_rehearsal(
        store,
        production.id,
        slug="morning",
        room_id="room-main",
        starts_at="2021-03-15T08:00:00+00:00",
        ends_at="2021-03-15T10:00:00+00:00",
        participant_ids=["CST-1"],
    )
    add_rehearsal(
        store,
        production.id,
        slug="afternoon",
        room_id="room-main",
        starts_at="2021-03-15T11:00:00+00:00",
        ends_at="2021-03-15T13:00:00+00:00",
        participant_ids=["CST-1"],
    )
    pack, _ = service.build(production.id, PACK_DATE)
    assert "rehearsal_conflict" not in _warning_codes(pack)


def test_room_conflict_warning_for_overlapping_rehearsals(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    left = add_rehearsal(
        store,
        production.id,
        slug="room-a",
        room_id="room-main",
        starts_at=REHEARSAL_START,
        ends_at=REHEARSAL_END,
        participant_ids=["CST-1"],
    )
    right = add_rehearsal(
        store,
        production.id,
        slug="room-b",
        room_id="room-main",
        starts_at="2021-03-15T11:00:00+00:00",
        ends_at="2021-03-15T13:00:00+00:00",
        participant_ids=["CST-2"],
    )
    pack, _ = service.build(production.id, PACK_DATE)
    room_warnings = [
        warning
        for warning in pack.warnings
        if warning["code"] == "rehearsal_conflict" and "Room room-main" in warning["message"]
    ]
    assert room_warnings
    assert set(room_warnings[0]["refs"]) == {left.id, right.id}


def test_shared_participant_conflict_warning(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    left = add_rehearsal(
        store,
        production.id,
        slug="cast-a",
        room_id="room-a",
        starts_at=REHEARSAL_START,
        ends_at=REHEARSAL_END,
        participant_ids=["CST-9"],
    )
    right = add_rehearsal(
        store,
        production.id,
        slug="cast-b",
        room_id="room-b",
        starts_at="2021-03-15T11:00:00+00:00",
        ends_at="2021-03-15T13:00:00+00:00",
        participant_ids=["CST-9"],
    )
    pack, _ = service.build(production.id, PACK_DATE)
    people_warnings = [
        warning
        for warning in pack.warnings
        if warning["code"] == "rehearsal_conflict" and "CST-9" in warning["message"]
    ]
    assert people_warnings
    assert set(people_warnings[0]["refs"]) == {left.id, right.id}


def test_sound_cues_are_ordered_by_cue_number(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    add_rehearsal(
        store,
        production.id,
        slug="tech",
        room_id="room-main",
        starts_at=REHEARSAL_START,
        ends_at=REHEARSAL_END,
    )
    add_sound_cue(store, production.id, slug="cue-three", cue_number=3)
    add_sound_cue(store, production.id, slug="cue-one", cue_number=1)
    add_sound_cue(store, production.id, slug="cue-two", cue_number=2)
    pack, _ = service.build(production.id, PACK_DATE)
    assert [row["cue_number"] for row in pack.sound_cues] == [1, 2, 3]


def test_unready_sound_cue_emits_warning(service: DayPackService, store: JsonDocumentStore) -> None:
    production = seed_production(store)
    cue = add_sound_cue(store, production.id, slug="cue-late", cue_number=4, ready=False)
    add_rehearsal(
        store,
        production.id,
        slug="tech",
        room_id="room-main",
        starts_at=REHEARSAL_START,
        ends_at=REHEARSAL_END,
    )
    pack, _ = service.build(production.id, PACK_DATE)
    assert "unready_sound_cue" in _warning_codes(pack)
    assert cue.id in pack.warnings[0]["refs"]


def test_role_track_coverage_information_and_uncovered_gap(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    add_rehearsal(
        store,
        production.id,
        slug="tech",
        room_id="room-main",
        starts_at=REHEARSAL_START,
        ends_at=REHEARSAL_END,
    )
    covered = add_role_track(
        store,
        production.id,
        slug="hamlet-role",
        role_name="Hamlet",
        primary_cast_id="CST-1",
        understudy_ids=["CST-2"],
    )
    uncovered = add_role_track(
        store,
        production.id,
        slug="ghost-role",
        role_name="Ghost",
        primary_cast_id="",
    )
    pack, _ = service.build(production.id, PACK_DATE)
    rows = {row["id"]: row for row in pack.role_tracks}
    assert rows[covered.id]["covered"] is True
    assert rows[uncovered.id]["covered"] is False
    assert "uncovered_role" in _gap_codes(pack)


def test_production_linked_prop_assets_and_repair_warning(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    add_rehearsal(
        store,
        production.id,
        slug="tech",
        room_id="room-main",
        starts_at=REHEARSAL_START,
        ends_at=REHEARSAL_END,
    )
    prop = add_prop_asset(store, production.id, slug="throne", condition="repair")
    pack, _ = service.build(production.id, PACK_DATE)
    assert [row["id"] for row in pack.prop_assets] == [prop.id]
    assert "prop_repair" in _warning_codes(pack)


def test_invalid_prop_checkout_state_prevents_build(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    add_rehearsal(
        store,
        production.id,
        slug="tech",
        room_id="room-main",
        starts_at=REHEARSAL_START,
        ends_at=REHEARSAL_END,
    )
    rows = (
        PropAssetService(store)
        .create(
            "Sword",
            "sword",
            metadata={"production_id": production.id, "condition": "good"},
        )
        .to_dict()
    )
    rows["metadata"]["checked_out_to"] = "CST-7"
    store.write_collection("prop_assets", [rows])
    with pytest.raises(ValidationError, match="checked_out_at"):
        service.build(production.id, PACK_DATE)


def test_call_timeline_is_deterministic_for_performances_and_primary_roles(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    evening = add_performance(store, production.id, slug="evening", starts_at=EVENING_START)
    add_role_track(
        store,
        production.id,
        slug="hamlet-role",
        role_name="Hamlet",
        primary_cast_id="CST-1",
    )
    add_role_track(
        store,
        production.id,
        slug="horatio-role",
        role_name="Horatio",
        primary_cast_id="CST-3",
    )
    first, _ = service.build(production.id, PACK_DATE)
    second, _ = service.build(production.id, PACK_DATE)
    assert first.call_timeline == second.call_timeline
    assert len(first.call_timeline) == 2
    assert all(row["performance_id"] == evening.id for row in first.call_timeline)
    assert all(row["offset_minutes"] == -60 for row in first.call_timeline)
    assert first.call_timeline[0]["call_at"] == "2021-03-15T18:30:00+00:00"


def test_list_filters_by_date_and_status(service: DayPackService, store: JsonDocumentStore) -> None:
    production = seed_production(store)
    draft, _ = service.build(production.id, PACK_DATE)
    other, _ = service.build(production.id, OTHER_DATE)
    published = service.publish(other.id)
    assert [row.id for row in service.list(production.id, date=PACK_DATE)] == [draft.id]
    assert [row.id for row in service.list(production.id, status="published")] == [published.id]


def test_publish_sets_published_state_and_timestamp(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    pack, _ = service.build(production.id, PACK_DATE)
    published = service.publish(pack.id)
    assert published.status == "published"
    assert published.published_at is not None


def test_publish_already_published_pack_raises_conflict(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    pack, _ = service.build(production.id, PACK_DATE)
    service.publish(pack.id)
    with pytest.raises(ConflictError, match="already published"):
        service.publish(pack.id)


def test_rebuilding_published_pack_raises_conflict(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    pack, _ = service.build(production.id, PACK_DATE)
    service.publish(pack.id)
    with pytest.raises(ConflictError, match="cannot be rebuilt"):
        service.build(production.id, PACK_DATE)


def test_persistence_survives_fresh_service_instance(
    tmp_path: Path, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    seed_rich_day(store, production.id)
    created_service = DayPackService(store)
    pack, _ = created_service.build(production.id, PACK_DATE)
    reloaded = DayPackService(JsonDocumentStore(tmp_path / "store.json"))
    loaded = reloaded.get(pack.id)
    assert loaded.version == pack.version
    assert loaded.performances == pack.performances
    assert loaded.sound_cues == pack.sound_cues


def test_store_revision_increments_on_build_and_publish(
    service: DayPackService, store: JsonDocumentStore
) -> None:
    production = seed_production(store)
    initial = store.revision
    pack, _ = service.build(production.id, PACK_DATE)
    after_build = store.revision
    service.publish(pack.id)
    assert after_build > initial
    assert store.revision > after_build
