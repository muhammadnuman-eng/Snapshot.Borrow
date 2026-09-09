from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from lumenstage.domain.inventory import (
    AssetCondition,
    AssetStatus,
    InventoryLedger,
    MaintenanceStatus,
    MaintenanceTicket,
    MovementType,
    ReservationStatus,
    StockItem,
    StockKind,
    StockReservation,
)
from lumenstage.errors import ConflictError, NotFoundError, ValidationError, WorkflowError

NOW = datetime(2027, 3, 1, 10, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        value = self.value
        self.value += timedelta(seconds=1)
        return value


@pytest.fixture()
def ledger() -> InventoryLedger:
    result = InventoryLedger(currency="gbp", clock=Clock())
    result.add_item(
        StockItem(
            "TAPE-BLK",
            "Black gaffer tape",
            "consumables",
            StockKind.CONSUMABLE,
            reorder_point=5,
            replacement_cost=Decimal("8.50"),
        )
    )
    result.add_item(
        StockItem(
            "RADIO",
            "Production radio",
            "communications",
            StockKind.SERIALIZED,
            reorder_point=1,
            replacement_cost=Decimal("350"),
        )
    )
    result.add_item(
        StockItem(
            "CHAIR",
            "Rehearsal chair",
            "furniture",
            StockKind.BULK,
            replacement_cost=Decimal("40"),
        )
    )
    return result


def reservation(identifier: str, sku: str, quantity: int, **overrides: object):
    values: dict[str, object] = {
        "id": identifier,
        "production_id": "prod-1",
        "sku": sku,
        "quantity": quantity,
        "location": "Warehouse",
        "starts_at": NOW + timedelta(days=1),
        "ends_at": NOW + timedelta(days=2),
        "requested_by": "Production manager",
    }
    values.update(overrides)
    return StockReservation(**values)  # type: ignore[arg-type]


def test_item_normalizes_identity_money_and_tags() -> None:
    item = StockItem(
        " radio ",
        "Radio",
        "Comms",
        StockKind.SERIALIZED,
        replacement_cost="12.345",
        tags=frozenset({" RF ", "rf"}),
    )
    assert item.sku == "RADIO"
    assert item.replacement_cost == Decimal("12.35")
    assert item.tags == frozenset({"rf"})


def test_duplicate_and_missing_items_raise_domain_errors(ledger: InventoryLedger) -> None:
    with pytest.raises(ConflictError, match="already exists"):
        ledger.add_item(StockItem("RADIO", "Other", "Comms", StockKind.SERIALIZED))
    with pytest.raises(NotFoundError, match="not found"):
        ledger.require_item("missing")


def test_receive_bulk_stock_updates_balance_and_movement(ledger: InventoryLedger) -> None:
    movement = ledger.receive("tape-blk", 20, "Warehouse", "Stores", unit_cost="7.25")
    availability = ledger.availability("TAPE-BLK", "Warehouse", NOW, NOW + timedelta(days=1))
    assert movement.movement_type == MovementType.RECEIVE
    assert movement.value == Decimal("145.00")
    assert availability.on_hand == 20
    assert availability.available == 20


def test_serialized_receipt_requires_unique_units_and_serials(ledger: InventoryLedger) -> None:
    with pytest.raises(ValidationError, match="one unit id"):
        ledger.receive("RADIO", 2, "Warehouse", "Stores", unit_ids=("r1",))
    ledger.receive(
        "RADIO",
        2,
        "Warehouse",
        "Stores",
        unit_ids=("r1", "r2"),
        serial_numbers=("S1", "S2"),
    )
    assert [unit.id for unit in ledger.units] == ["r1", "r2"]
    with pytest.raises(ConflictError, match="unit id"):
        ledger.receive(
            "RADIO",
            1,
            "Warehouse",
            "Stores",
            unit_ids=("r1",),
            serial_numbers=("S3",),
        )


def test_bulk_transfer_preserves_total_and_respects_reservations(
    ledger: InventoryLedger,
) -> None:
    ledger.receive("CHAIR", 10, "Warehouse", "Stores")
    ledger.reserve(reservation("hold", "CHAIR", 8))
    with pytest.raises(ConflictError, match="reserved"):
        ledger.transfer("CHAIR", 3, "Warehouse", "Studio", "Stores")
    ledger.transfer("CHAIR", 2, "Warehouse", "Studio", "Stores")
    source = ledger.availability("CHAIR", "Warehouse", NOW, NOW + timedelta(hours=1))
    destination = ledger.availability("CHAIR", "Studio", NOW, NOW + timedelta(hours=1))
    assert source.on_hand == 8
    assert destination.on_hand == 2


def test_serialized_transfer_updates_location(ledger: InventoryLedger) -> None:
    ledger.receive("RADIO", 1, "Warehouse", "Stores", unit_ids=("r1",), serial_numbers=("S1",))
    ledger.transfer("RADIO", 1, "Warehouse", "Theatre", "Stores", unit_ids=("r1",))
    assert ledger.require_unit("r1").location == "Theatre"


def test_consumption_reduces_stock_and_nonconsumable_rejects_consume(
    ledger: InventoryLedger,
) -> None:
    ledger.receive("TAPE-BLK", 5, "Warehouse", "Stores")
    movement = ledger.issue("TAPE-BLK", 2, "Warehouse", "Crew", consume=True)
    assert movement.movement_type == MovementType.CONSUME
    assert ledger.availability("TAPE-BLK", "Warehouse", NOW, NOW + timedelta(1)).on_hand == 3
    ledger.receive("CHAIR", 2, "Warehouse", "Stores")
    with pytest.raises(ValidationError, match="consumable"):
        ledger.issue("CHAIR", 1, "Warehouse", "Crew", consume=True)


def test_serialized_issue_and_return_tracks_condition(ledger: InventoryLedger) -> None:
    ledger.receive("RADIO", 1, "Warehouse", "Stores", unit_ids=("r1",), serial_numbers=("S1",))
    ledger.issue("RADIO", 1, "Warehouse", "Crew", unit_ids=("r1",))
    assert ledger.require_unit("r1").status == AssetStatus.ISSUED
    ledger.return_units("RADIO", ("r1",), "Warehouse", "Crew", condition=AssetCondition.DAMAGED)
    unit = ledger.require_unit("r1")
    assert unit.status == AssetStatus.MAINTENANCE
    assert unit.condition == AssetCondition.DAMAGED


def test_adjustment_requires_authorization_and_nonnegative_result(
    ledger: InventoryLedger,
) -> None:
    ledger.receive("CHAIR", 2, "Warehouse", "Stores")
    with pytest.raises(WorkflowError, match="authorization"):
        ledger.adjust("CHAIR", "Warehouse", -1, "Manager", "damage")
    with pytest.raises(ConflictError, match="negative"):
        ledger.adjust("CHAIR", "Warehouse", -3, "Manager", "damage", authorized=True)
    movement = ledger.adjust("CHAIR", "Warehouse", -1, "Manager", "damaged", authorized=True)
    assert movement.reason == "damaged"


def test_bulk_reservations_prevent_overbooking(ledger: InventoryLedger) -> None:
    ledger.receive("CHAIR", 10, "Warehouse", "Stores")
    held = ledger.reserve(reservation("one", "CHAIR", 7))
    assert held.status == ReservationStatus.HELD
    with pytest.raises(ConflictError, match="available 3"):
        ledger.reserve(reservation("two", "CHAIR", 4))
    availability = ledger.availability(
        "CHAIR", "Warehouse", NOW + timedelta(days=1), NOW + timedelta(days=2)
    )
    assert availability.reserved == 7
    assert availability.available == 3


def test_nonoverlapping_reservations_can_reuse_stock(ledger: InventoryLedger) -> None:
    ledger.receive("CHAIR", 5, "Warehouse", "Stores")
    ledger.reserve(reservation("one", "CHAIR", 5))
    second = reservation(
        "two",
        "CHAIR",
        5,
        starts_at=NOW + timedelta(days=3),
        ends_at=NOW + timedelta(days=4),
    )
    assert ledger.reserve(second).quantity == 5


def test_serialized_reservation_auto_assigns_and_releases_units(
    ledger: InventoryLedger,
) -> None:
    ledger.receive(
        "RADIO",
        2,
        "Warehouse",
        "Stores",
        unit_ids=("r1", "r2"),
        serial_numbers=("S1", "S2"),
    )
    held = ledger.reserve(reservation("radio-hold", "RADIO", 1))
    assert held.unit_ids == ("r1",)
    assert ledger.require_unit("r1").status == AssetStatus.RESERVED
    released = ledger.release_reservation("radio-hold")
    assert released.status == ReservationStatus.RELEASED
    assert ledger.require_unit("r1").status == AssetStatus.AVAILABLE


def test_nonoverlapping_serialized_reservations_can_share_a_unit(
    ledger: InventoryLedger,
) -> None:
    ledger.receive("RADIO", 1, "Warehouse", "Stores", unit_ids=("r1",), serial_numbers=("S1",))
    first = ledger.reserve(reservation("first", "RADIO", 1))
    later = reservation(
        "later",
        "RADIO",
        1,
        starts_at=NOW + timedelta(days=3),
        ends_at=NOW + timedelta(days=4),
    )
    second = ledger.reserve(later)
    assert first.unit_ids == second.unit_ids == ("r1",)
    ledger.release_reservation("first")
    assert ledger.require_unit("r1").status == AssetStatus.RESERVED
    ledger.release_reservation("later")
    assert ledger.require_unit("r1").status == AssetStatus.AVAILABLE


def test_fulfill_bulk_and_serialized_reservations(ledger: InventoryLedger) -> None:
    ledger.receive("TAPE-BLK", 10, "Warehouse", "Stores")
    ledger.reserve(reservation("tape", "TAPE-BLK", 2))
    movement = ledger.fulfill_reservation("tape", "Stage manager")
    assert movement.movement_type == MovementType.CONSUME
    assert ledger.require_reservation("tape").status == ReservationStatus.FULFILLED
    ledger.receive("RADIO", 1, "Warehouse", "Stores", unit_ids=("r1",), serial_numbers=("S1",))
    ledger.reserve(reservation("radio", "RADIO", 1))
    issued = ledger.fulfill_reservation("radio", "Stage manager")
    assert issued.unit_ids == ("r1",)
    assert ledger.require_unit("r1").status == AssetStatus.ISSUED


def test_expired_reservations_release_serialized_units(ledger: InventoryLedger) -> None:
    ledger.receive("RADIO", 1, "Warehouse", "Stores", unit_ids=("r1",), serial_numbers=("S1",))
    ledger.reserve(reservation("radio", "RADIO", 1))
    expired = ledger.expire_reservations(at=NOW + timedelta(days=3))
    assert expired[0].status == ReservationStatus.EXPIRED
    assert ledger.require_unit("r1").status == AssetStatus.AVAILABLE


def test_maintenance_removes_and_restores_asset_availability(
    ledger: InventoryLedger,
) -> None:
    ledger.receive("RADIO", 1, "Warehouse", "Stores", unit_ids=("r1",), serial_numbers=("S1",))
    ticket = MaintenanceTicket("m1", "r1", "Annual service", "Tech", NOW, NOW + timedelta(days=1))
    ledger.open_maintenance(ticket)
    assert ledger.require_unit("r1").status == AssetStatus.MAINTENANCE
    started = ledger.start_maintenance("m1", "Engineer")
    assert started.status == MaintenanceStatus.IN_PROGRESS
    completed = ledger.complete_maintenance(
        "m1", "Tested and cleaned", cost="45.50", next_due_at=NOW + timedelta(days=365), at=NOW
    )
    assert completed.cost == Decimal("45.50")
    assert ledger.require_unit("r1").status == AssetStatus.AVAILABLE


def test_cycle_count_records_authorized_variance(ledger: InventoryLedger) -> None:
    ledger.receive("CHAIR", 10, "Warehouse", "Stores")
    result = ledger.cycle_count("CHAIR", "Warehouse", 8, "Stores", authorized=True)
    assert result.expected == 10
    assert result.variance == -2
    assert result.movement_id == "MOV-00000002"


def test_reorder_suggestions_include_reservations(ledger: InventoryLedger) -> None:
    ledger.receive("TAPE-BLK", 8, "Warehouse", "Stores")
    ledger.reserve(reservation("tape", "TAPE-BLK", 4))
    suggestions = ledger.reorder_suggestions(at=NOW)
    suggestion = next(item for item in suggestions if item.sku == "TAPE-BLK")
    assert suggestion.on_hand == 8
    assert suggestion.reserved == 4
    assert suggestion.suggested_quantity == 6


def test_valuation_groups_bulk_and_serialized_assets(ledger: InventoryLedger) -> None:
    ledger.receive("CHAIR", 2, "Warehouse", "Stores")
    ledger.receive("RADIO", 1, "Warehouse", "Stores", unit_ids=("r1",), serial_numbers=("S1",))
    value = ledger.valuation()
    assert value.currency == "GBP"
    assert value.bulk_value == Decimal("80.00")
    assert value.serialized_value == Decimal("350.00")
    assert value.total_value == Decimal("430.00")


def test_movement_history_filters_type_location_and_reference(
    ledger: InventoryLedger,
) -> None:
    ledger.receive("CHAIR", 5, "Warehouse", "Stores", reference="PO-1", at=NOW)
    ledger.transfer("CHAIR", 1, "Warehouse", "Studio", "Stores", at=NOW + timedelta(hours=1))
    result = ledger.movement_history(
        sku="chair",
        movement_type=MovementType.RECEIVE,
        location="Warehouse",
        reference="PO-1",
        starts_at=NOW - timedelta(minutes=1),
        ends_at=NOW + timedelta(minutes=1),
    )
    assert [movement.id for movement in result] == ["MOV-00000001"]


def test_retire_unit_changes_valuation_and_prevents_issued_retirement(
    ledger: InventoryLedger,
) -> None:
    ledger.receive("RADIO", 1, "Warehouse", "Stores", unit_ids=("r1",), serial_numbers=("S1",))
    ledger.issue("RADIO", 1, "Warehouse", "Crew", unit_ids=("r1",))
    with pytest.raises(WorkflowError, match="cannot retire"):
        ledger.retire_unit("r1", "Manager", "obsolete")
    ledger.return_units("RADIO", ("r1",), "Warehouse", "Crew")
    ledger.retire_unit("r1", "Manager", "obsolete")
    assert ledger.valuation().serialized_value == Decimal("0.00")


def test_inventory_report_summarizes_operational_state(ledger: InventoryLedger) -> None:
    ledger.receive("CHAIR", 2, "Warehouse", "Stores")
    ledger.receive("RADIO", 1, "Warehouse", "Stores", unit_ids=("r1",), serial_numbers=("S1",))
    ledger.reserve(reservation("chairs", "CHAIR", 1))
    report = ledger.report(at=NOW)
    assert report.item_count == 3
    assert report.asset_units == 1
    assert report.available_units == 1
    assert report.open_reservations == 1
    assert report.movement_count == 2
    assert report.by_kind == {"consumable": 1, "serialized": 1, "bulk": 1}


def test_naive_inventory_clock_is_rejected() -> None:
    ledger = InventoryLedger(clock=lambda: datetime(2027, 1, 1))
    ledger.add_item(StockItem("X", "X", "X", StockKind.BULK))
    with pytest.raises(ValidationError, match="timezone-aware"):
        ledger.receive("X", 1, "Room", "Stores")
