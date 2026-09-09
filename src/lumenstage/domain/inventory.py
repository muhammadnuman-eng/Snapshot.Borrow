"""Location-aware stock, serialized assets, reservations, and maintenance."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

from lumenstage.errors import ConflictError, NotFoundError, ValidationError, WorkflowError

CENT = Decimal("0.01")


class StockKind(StrEnum):
    BULK = "bulk"
    CONSUMABLE = "consumable"
    SERIALIZED = "serialized"


class AssetCondition(StrEnum):
    GOOD = "good"
    FAIR = "fair"
    DAMAGED = "damaged"
    UNSAFE = "unsafe"


class AssetStatus(StrEnum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    ISSUED = "issued"
    MAINTENANCE = "maintenance"
    RETIRED = "retired"


class MovementType(StrEnum):
    RECEIVE = "receive"
    TRANSFER = "transfer"
    ISSUE = "issue"
    RETURN = "return"
    ADJUST = "adjust"
    CONSUME = "consume"
    RETIRE = "retire"


class ReservationStatus(StrEnum):
    HELD = "held"
    FULFILLED = "fulfilled"
    RELEASED = "released"
    EXPIRED = "expired"


class MaintenanceStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValidationError(f"{field_name} must be timezone-aware")
    return value


def _money(value: Decimal | str | int, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValidationError(f"{field_name} must be a decimal amount") from exc
    if not result.is_finite() or result < 0:
        raise ValidationError(f"{field_name} must be finite and non-negative")
    return result.quantize(CENT, rounding=ROUND_HALF_UP)


def _quantity(value: int, field_name: str = "quantity") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError(f"{field_name} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class StockItem:
    sku: str
    name: str
    category: str
    kind: StockKind
    unit: str = "each"
    reorder_point: int = 0
    replacement_cost: Decimal = Decimal("0")
    active: bool = True
    tags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        sku = _text(self.sku, "sku").upper()
        object.__setattr__(self, "sku", sku)
        _text(self.name, "item name")
        _text(self.category, "category")
        _text(self.unit, "unit")
        if isinstance(self.reorder_point, bool) or self.reorder_point < 0:
            raise ValidationError("reorder_point must be non-negative")
        object.__setattr__(
            self,
            "replacement_cost",
            _money(self.replacement_cost, "replacement_cost"),
        )
        object.__setattr__(
            self,
            "tags",
            frozenset(tag.strip().lower() for tag in self.tags if tag.strip()),
        )


@dataclass(frozen=True, slots=True)
class AssetUnit:
    id: str
    sku: str
    serial_number: str
    location: str
    condition: AssetCondition = AssetCondition.GOOD
    status: AssetStatus = AssetStatus.AVAILABLE
    acquired_at: datetime | None = None
    maintenance_due_at: datetime | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        _text(self.id, "asset unit id")
        object.__setattr__(self, "sku", _text(self.sku, "sku").upper())
        _text(self.serial_number, "serial_number")
        _text(self.location, "asset location")
        if self.acquired_at is not None:
            _aware(self.acquired_at, "acquired_at")
        if self.maintenance_due_at is not None:
            _aware(self.maintenance_due_at, "maintenance_due_at")

    @property
    def usable(self) -> bool:
        return self.status == AssetStatus.AVAILABLE and self.condition not in {
            AssetCondition.DAMAGED,
            AssetCondition.UNSAFE,
        }


@dataclass(frozen=True, slots=True)
class StockMovement:
    sequence: int
    id: str
    movement_type: MovementType
    sku: str
    quantity: int
    source: str
    destination: str
    actor: str
    occurred_at: datetime
    reference: str = ""
    reason: str = ""
    unit_ids: tuple[str, ...] = ()
    unit_cost: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise ValidationError("movement sequence must be positive")
        _text(self.id, "movement id")
        object.__setattr__(self, "sku", _text(self.sku, "sku").upper())
        _quantity(self.quantity)
        _text(self.actor, "movement actor")
        _aware(self.occurred_at, "movement occurred_at")
        object.__setattr__(self, "unit_cost", _money(self.unit_cost, "unit_cost"))
        if self.unit_ids and len(self.unit_ids) != self.quantity:
            raise ValidationError("serialized movement quantity must match unit_ids")

    @property
    def value(self) -> Decimal:
        return (self.unit_cost * self.quantity).quantize(CENT)


@dataclass(frozen=True, slots=True)
class StockReservation:
    id: str
    production_id: str
    sku: str
    quantity: int
    location: str
    starts_at: datetime
    ends_at: datetime
    requested_by: str
    status: ReservationStatus = ReservationStatus.HELD
    unit_ids: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        _text(self.id, "reservation id")
        _text(self.production_id, "production_id")
        object.__setattr__(self, "sku", _text(self.sku, "sku").upper())
        _quantity(self.quantity)
        _text(self.location, "reservation location")
        _text(self.requested_by, "requested_by")
        _aware(self.starts_at, "reservation starts_at")
        _aware(self.ends_at, "reservation ends_at")
        if self.ends_at <= self.starts_at:
            raise ValidationError("reservation end must follow start")
        if self.unit_ids and len(self.unit_ids) != self.quantity:
            raise ValidationError("reservation quantity must match unit_ids")

    def overlaps(self, starts_at: datetime, ends_at: datetime) -> bool:
        return self.starts_at < ends_at and starts_at < self.ends_at


@dataclass(frozen=True, slots=True)
class MaintenanceTicket:
    id: str
    unit_id: str
    summary: str
    opened_by: str
    opened_at: datetime
    due_at: datetime
    status: MaintenanceStatus = MaintenanceStatus.OPEN
    assigned_to: str = ""
    completion_note: str = ""
    completed_at: datetime | None = None
    cost: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        _text(self.id, "maintenance id")
        _text(self.unit_id, "unit_id")
        _text(self.summary, "maintenance summary")
        _text(self.opened_by, "opened_by")
        _aware(self.opened_at, "opened_at")
        _aware(self.due_at, "due_at")
        if self.due_at < self.opened_at:
            raise ValidationError("maintenance due_at must not precede opened_at")
        object.__setattr__(self, "cost", _money(self.cost, "maintenance cost"))


@dataclass(frozen=True, slots=True)
class StockAvailability:
    sku: str
    location: str
    on_hand: int
    reserved: int
    available: int
    usable_units: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReorderSuggestion:
    sku: str
    on_hand: int
    reserved: int
    reorder_point: int
    suggested_quantity: int


@dataclass(frozen=True, slots=True)
class InventoryValuation:
    currency: str
    bulk_value: Decimal
    serialized_value: Decimal
    total_value: Decimal
    by_category: dict[str, Decimal]


@dataclass(frozen=True, slots=True)
class CycleCountResult:
    sku: str
    location: str
    expected: int
    counted: int
    variance: int
    movement_id: str | None


@dataclass(frozen=True, slots=True)
class InventoryReport:
    item_count: int
    active_items: int
    asset_units: int
    available_units: int
    open_reservations: int
    overdue_maintenance: int
    movement_count: int
    by_kind: dict[str, int]
    by_condition: dict[str, int]


class InventoryLedger:
    """Track stock without allowing reservations or maintenance to overbook it."""

    def __init__(
        self,
        *,
        currency: str = "USD",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        currency = currency.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValidationError("currency must be a three-letter code")
        self.currency = currency
        self._clock = clock or (lambda: datetime.now(UTC))
        self._items: dict[str, StockItem] = {}
        self._balances: defaultdict[tuple[str, str], int] = defaultdict(int)
        self._units: dict[str, AssetUnit] = {}
        self._movements: list[StockMovement] = []
        self._reservations: dict[str, StockReservation] = {}
        self._maintenance: dict[str, MaintenanceTicket] = {}

    @property
    def items(self) -> tuple[StockItem, ...]:
        return tuple(sorted(self._items.values(), key=lambda item: item.sku))

    @property
    def units(self) -> tuple[AssetUnit, ...]:
        return tuple(sorted(self._units.values(), key=lambda unit: unit.id))

    @property
    def movements(self) -> tuple[StockMovement, ...]:
        return tuple(self._movements)

    @property
    def reservations(self) -> tuple[StockReservation, ...]:
        return tuple(sorted(self._reservations.values(), key=lambda item: item.id))

    @property
    def maintenance(self) -> tuple[MaintenanceTicket, ...]:
        return tuple(sorted(self._maintenance.values(), key=lambda item: item.id))

    def add_item(self, item: StockItem) -> None:
        if item.sku in self._items:
            raise ConflictError(f"stock item already exists: {item.sku}")
        self._items[item.sku] = item

    def replace_item(self, item: StockItem) -> None:
        self.require_item(item.sku)
        self._items[item.sku] = item

    def require_item(self, sku: str) -> StockItem:
        normalized = sku.strip().upper()
        try:
            return self._items[normalized]
        except KeyError as exc:
            raise NotFoundError(f"stock item not found: {normalized}") from exc

    def require_unit(self, unit_id: str) -> AssetUnit:
        try:
            return self._units[unit_id]
        except KeyError as exc:
            raise NotFoundError(f"asset unit not found: {unit_id}") from exc

    def receive(
        self,
        sku: str,
        quantity: int,
        location: str,
        actor: str,
        *,
        unit_ids: Iterable[str] = (),
        serial_numbers: Iterable[str] = (),
        unit_cost: Decimal | str | int | None = None,
        reference: str = "",
        at: datetime | None = None,
    ) -> StockMovement:
        item = self.require_item(sku)
        self._require_active(item)
        quantity = _quantity(quantity)
        location = _text(location, "destination location")
        identifiers = tuple(unit_ids)
        serials = tuple(serial_numbers)
        if item.kind == StockKind.SERIALIZED:
            if len(identifiers) != quantity or len(serials) != quantity:
                raise ValidationError(
                    "serialized receipt requires one unit id and serial per quantity"
                )
            if len(identifiers) != len(set(identifiers)):
                raise ValidationError("asset unit ids must be unique")
            if len(serials) != len(set(serials)):
                raise ValidationError("asset serial numbers must be unique")
            if any(identifier in self._units for identifier in identifiers):
                raise ConflictError("asset unit id already exists")
            existing_serials = {unit.serial_number for unit in self._units.values()}
            if existing_serials.intersection(serials):
                raise ConflictError("asset serial number already exists")
        elif identifiers or serials:
            raise ValidationError("unit ids are only valid for serialized stock")
        cost = item.replacement_cost if unit_cost is None else _money(unit_cost, "unit_cost")
        movement = self._movement(
            MovementType.RECEIVE,
            item.sku,
            quantity,
            "",
            location,
            actor,
            reference=reference,
            unit_ids=identifiers,
            unit_cost=cost,
            at=at,
        )
        if item.kind == StockKind.SERIALIZED:
            for identifier, serial in zip(identifiers, serials, strict=True):
                self._units[identifier] = AssetUnit(
                    identifier,
                    item.sku,
                    serial,
                    location,
                    acquired_at=movement.occurred_at,
                )
        else:
            self._balances[(item.sku, location)] += quantity
        return movement

    def transfer(
        self,
        sku: str,
        quantity: int,
        source: str,
        destination: str,
        actor: str,
        *,
        unit_ids: Iterable[str] = (),
        reference: str = "",
        at: datetime | None = None,
    ) -> StockMovement:
        item = self.require_item(sku)
        quantity = _quantity(quantity)
        source = _text(source, "source location")
        destination = _text(destination, "destination location")
        if source.casefold() == destination.casefold():
            raise ValidationError("transfer source and destination must differ")
        identifiers = tuple(unit_ids)
        if item.kind == StockKind.SERIALIZED:
            self._validate_units(identifiers, item.sku, source, AssetStatus.AVAILABLE)
            if len(identifiers) != quantity:
                raise ValidationError("transfer quantity must match unit_ids")
        else:
            if identifiers:
                raise ValidationError("unit ids are only valid for serialized stock")
            held = self._reserved_quantity(item.sku, source)
            if self._balances[(item.sku, source)] - quantity < held:
                raise ConflictError("transfer would consume reserved stock")
        movement = self._movement(
            MovementType.TRANSFER,
            item.sku,
            quantity,
            source,
            destination,
            actor,
            reference=reference,
            unit_ids=identifiers,
            at=at,
        )
        if item.kind == StockKind.SERIALIZED:
            for identifier in identifiers:
                self._units[identifier] = replace(self._units[identifier], location=destination)
        else:
            self._balances[(item.sku, source)] -= quantity
            self._balances[(item.sku, destination)] += quantity
        return movement

    def issue(
        self,
        sku: str,
        quantity: int,
        location: str,
        actor: str,
        *,
        unit_ids: Iterable[str] = (),
        reference: str = "",
        consume: bool = False,
        at: datetime | None = None,
    ) -> StockMovement:
        item = self.require_item(sku)
        quantity = _quantity(quantity)
        location = _text(location, "issue location")
        identifiers = tuple(unit_ids)
        if item.kind == StockKind.SERIALIZED:
            self._validate_units(identifiers, item.sku, location, AssetStatus.AVAILABLE)
            if len(identifiers) != quantity:
                raise ValidationError("issue quantity must match unit_ids")
        else:
            if identifiers:
                raise ValidationError("unit ids are only valid for serialized stock")
            if self._balances[(item.sku, location)] < quantity:
                raise ConflictError("insufficient stock to issue")
        movement_type = MovementType.CONSUME if consume else MovementType.ISSUE
        if consume and item.kind != StockKind.CONSUMABLE:
            raise ValidationError("only consumable stock can be consumed")
        movement = self._movement(
            movement_type,
            item.sku,
            quantity,
            location,
            "issued",
            actor,
            reference=reference,
            unit_ids=identifiers,
            at=at,
        )
        if item.kind == StockKind.SERIALIZED:
            for identifier in identifiers:
                self._units[identifier] = replace(
                    self._units[identifier],
                    status=AssetStatus.ISSUED,
                )
        else:
            self._balances[(item.sku, location)] -= quantity
        return movement

    def return_units(
        self,
        sku: str,
        unit_ids: Iterable[str],
        location: str,
        actor: str,
        *,
        condition: AssetCondition = AssetCondition.GOOD,
        reference: str = "",
        at: datetime | None = None,
    ) -> StockMovement:
        item = self.require_item(sku)
        if item.kind != StockKind.SERIALIZED:
            raise ValidationError("return_units requires serialized stock")
        identifiers = tuple(unit_ids)
        if not identifiers:
            raise ValidationError("at least one unit id is required")
        for identifier in identifiers:
            unit = self.require_unit(identifier)
            if unit.sku != item.sku or unit.status != AssetStatus.ISSUED:
                raise WorkflowError(f"asset unit is not issued for this item: {identifier}")
        movement = self._movement(
            MovementType.RETURN,
            item.sku,
            len(identifiers),
            "issued",
            _text(location, "return location"),
            actor,
            reference=reference,
            unit_ids=identifiers,
            at=at,
        )
        status = (
            AssetStatus.AVAILABLE
            if condition not in {AssetCondition.DAMAGED, AssetCondition.UNSAFE}
            else AssetStatus.MAINTENANCE
        )
        for identifier in identifiers:
            self._units[identifier] = replace(
                self._units[identifier],
                location=location,
                condition=condition,
                status=status,
            )
        return movement

    def adjust(
        self,
        sku: str,
        location: str,
        delta: int,
        actor: str,
        reason: str,
        *,
        authorized: bool = False,
        at: datetime | None = None,
    ) -> StockMovement:
        item = self.require_item(sku)
        if item.kind == StockKind.SERIALIZED:
            raise ValidationError("serialized assets must be received or retired individually")
        if isinstance(delta, bool) or not isinstance(delta, int) or delta == 0:
            raise ValidationError("adjustment delta must be a non-zero integer")
        if not authorized:
            raise WorkflowError("stock adjustment requires authorization")
        location = _text(location, "adjustment location")
        reason = _text(reason, "adjustment reason")
        resulting = self._balances[(item.sku, location)] + delta
        if resulting < 0:
            raise ConflictError("stock adjustment would create a negative balance")
        movement = self._movement(
            MovementType.ADJUST,
            item.sku,
            abs(delta),
            location if delta < 0 else "adjustment",
            "adjustment" if delta < 0 else location,
            actor,
            reason=reason,
            at=at,
        )
        self._balances[(item.sku, location)] = resulting
        return movement

    def reserve(
        self,
        reservation: StockReservation,
        *,
        auto_assign_units: bool = True,
    ) -> StockReservation:
        if reservation.id in self._reservations:
            raise ConflictError(f"stock reservation already exists: {reservation.id}")
        item = self.require_item(reservation.sku)
        self._require_active(item)
        available = self.availability(
            item.sku,
            reservation.location,
            reservation.starts_at,
            reservation.ends_at,
        )
        if reservation.quantity > available.available:
            raise ConflictError(
                f"insufficient reservable stock: requested {reservation.quantity}, "
                f"available {available.available}"
            )
        assigned = reservation
        if item.kind == StockKind.SERIALIZED:
            identifiers = reservation.unit_ids
            if not identifiers and auto_assign_units:
                identifiers = available.usable_units[: reservation.quantity]
            if len(identifiers) != reservation.quantity:
                raise ValidationError("serialized reservation requires assigned unit ids")
            if not set(identifiers).issubset(available.usable_units):
                raise ConflictError("one or more asset units are unavailable")
            assigned = replace(reservation, unit_ids=tuple(identifiers))
            for identifier in identifiers:
                self._units[identifier] = replace(
                    self._units[identifier],
                    status=AssetStatus.RESERVED,
                )
        self._reservations[assigned.id] = assigned
        return assigned

    def fulfill_reservation(
        self,
        reservation_id: str,
        actor: str,
        *,
        at: datetime | None = None,
    ) -> StockMovement:
        reservation = self.require_reservation(reservation_id)
        if reservation.status != ReservationStatus.HELD:
            raise WorkflowError(f"cannot fulfill a {reservation.status} reservation")
        item = self.require_item(reservation.sku)
        if item.kind == StockKind.SERIALIZED:
            for identifier in reservation.unit_ids:
                unit = self.require_unit(identifier)
                if unit.status != AssetStatus.RESERVED:
                    raise ConflictError(f"reserved asset unit changed state: {identifier}")
                self._units[identifier] = replace(unit, status=AssetStatus.AVAILABLE)
        movement = self.issue(
            reservation.sku,
            reservation.quantity,
            reservation.location,
            actor,
            unit_ids=reservation.unit_ids,
            reference=reservation.production_id,
            consume=item.kind == StockKind.CONSUMABLE,
            at=at,
        )
        self._reservations[reservation.id] = replace(
            reservation,
            status=ReservationStatus.FULFILLED,
        )
        return movement

    def release_reservation(self, reservation_id: str) -> StockReservation:
        reservation = self.require_reservation(reservation_id)
        if reservation.status != ReservationStatus.HELD:
            raise WorkflowError(f"cannot release a {reservation.status} reservation")
        for identifier in reservation.unit_ids:
            unit = self.require_unit(identifier)
            held_elsewhere = any(
                other.id != reservation.id
                and other.status == ReservationStatus.HELD
                and identifier in other.unit_ids
                for other in self._reservations.values()
            )
            if unit.status == AssetStatus.RESERVED and not held_elsewhere:
                self._units[identifier] = replace(unit, status=AssetStatus.AVAILABLE)
        updated = replace(reservation, status=ReservationStatus.RELEASED)
        self._reservations[reservation.id] = updated
        return updated

    def expire_reservations(self, *, at: datetime | None = None) -> list[StockReservation]:
        moment = at or self._now()
        expired = []
        for reservation in self.reservations:
            if reservation.status == ReservationStatus.HELD and reservation.ends_at < moment:
                released = self.release_reservation(reservation.id)
                updated = replace(released, status=ReservationStatus.EXPIRED)
                self._reservations[reservation.id] = updated
                expired.append(updated)
        return expired

    def require_reservation(self, reservation_id: str) -> StockReservation:
        try:
            return self._reservations[reservation_id]
        except KeyError as exc:
            raise NotFoundError(f"stock reservation not found: {reservation_id}") from exc

    def availability(
        self,
        sku: str,
        location: str,
        starts_at: datetime,
        ends_at: datetime,
        *,
        exclude_reservation_id: str = "",
    ) -> StockAvailability:
        item = self.require_item(sku)
        location = _text(location, "availability location")
        _aware(starts_at, "availability starts_at")
        _aware(ends_at, "availability ends_at")
        if ends_at <= starts_at:
            raise ValidationError("availability end must follow start")
        overlapping = [
            reservation
            for reservation in self._reservations.values()
            if reservation.id != exclude_reservation_id
            and reservation.sku == item.sku
            and reservation.location == location
            and reservation.status == ReservationStatus.HELD
            and reservation.overlaps(starts_at, ends_at)
        ]
        if item.kind == StockKind.SERIALIZED:
            reserved_units = {
                identifier for reservation in overlapping for identifier in reservation.unit_ids
            }
            usable = tuple(
                unit.id
                for unit in self.units
                if unit.sku == item.sku
                and unit.location == location
                and unit.status in {AssetStatus.AVAILABLE, AssetStatus.RESERVED}
                and unit.condition not in {AssetCondition.DAMAGED, AssetCondition.UNSAFE}
                and unit.id not in reserved_units
            )
            on_hand = sum(
                unit.sku == item.sku
                and unit.location == location
                and unit.status != AssetStatus.RETIRED
                for unit in self._units.values()
            )
            reserved = len(reserved_units)
            return StockAvailability(item.sku, location, on_hand, reserved, len(usable), usable)
        on_hand = self._balances[(item.sku, location)]
        reserved = sum(reservation.quantity for reservation in overlapping)
        return StockAvailability(item.sku, location, on_hand, reserved, max(0, on_hand - reserved))

    def open_maintenance(
        self,
        ticket: MaintenanceTicket,
    ) -> MaintenanceTicket:
        if ticket.id in self._maintenance:
            raise ConflictError(f"maintenance ticket already exists: {ticket.id}")
        unit = self.require_unit(ticket.unit_id)
        if unit.status in {AssetStatus.ISSUED, AssetStatus.RETIRED}:
            raise WorkflowError(f"cannot maintain asset in {unit.status} state")
        if any(
            item.unit_id == unit.id
            and item.status in {MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS}
            for item in self._maintenance.values()
        ):
            raise ConflictError(f"asset already has open maintenance: {unit.id}")
        self._units[unit.id] = replace(unit, status=AssetStatus.MAINTENANCE)
        self._maintenance[ticket.id] = ticket
        return ticket

    def start_maintenance(self, ticket_id: str, assigned_to: str) -> MaintenanceTicket:
        ticket = self.require_maintenance(ticket_id)
        if ticket.status != MaintenanceStatus.OPEN:
            raise WorkflowError(f"cannot start maintenance from {ticket.status} state")
        updated = replace(
            ticket,
            status=MaintenanceStatus.IN_PROGRESS,
            assigned_to=_text(assigned_to, "assigned_to"),
        )
        self._maintenance[ticket.id] = updated
        return updated

    def complete_maintenance(
        self,
        ticket_id: str,
        note: str,
        *,
        condition: AssetCondition = AssetCondition.GOOD,
        cost: Decimal | str | int = Decimal("0"),
        next_due_at: datetime | None = None,
        at: datetime | None = None,
    ) -> MaintenanceTicket:
        ticket = self.require_maintenance(ticket_id)
        if ticket.status not in {MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS}:
            raise WorkflowError(f"cannot complete maintenance from {ticket.status} state")
        if condition == AssetCondition.UNSAFE:
            raise ValidationError("completed maintenance cannot return an unsafe asset")
        moment = at or self._now()
        updated = replace(
            ticket,
            status=MaintenanceStatus.COMPLETED,
            completion_note=_text(note, "maintenance completion note"),
            completed_at=moment,
            cost=_money(cost, "maintenance cost"),
        )
        self._maintenance[ticket.id] = updated
        unit = self.require_unit(ticket.unit_id)
        self._units[unit.id] = replace(
            unit,
            condition=condition,
            status=AssetStatus.AVAILABLE,
            maintenance_due_at=next_due_at,
        )
        return updated

    def require_maintenance(self, ticket_id: str) -> MaintenanceTicket:
        try:
            return self._maintenance[ticket_id]
        except KeyError as exc:
            raise NotFoundError(f"maintenance ticket not found: {ticket_id}") from exc

    def retire_unit(self, unit_id: str, actor: str, reason: str) -> StockMovement:
        unit = self.require_unit(unit_id)
        if unit.status in {AssetStatus.ISSUED, AssetStatus.RESERVED}:
            raise WorkflowError(f"cannot retire asset in {unit.status} state")
        movement = self._movement(
            MovementType.RETIRE,
            unit.sku,
            1,
            unit.location,
            "retired",
            actor,
            reason=_text(reason, "retirement reason"),
            unit_ids=(unit.id,),
        )
        self._units[unit.id] = replace(unit, status=AssetStatus.RETIRED)
        return movement

    def cycle_count(
        self,
        sku: str,
        location: str,
        counted: int,
        actor: str,
        *,
        authorized: bool = False,
    ) -> CycleCountResult:
        item = self.require_item(sku)
        if item.kind == StockKind.SERIALIZED:
            raise ValidationError("serialized assets must be counted by unit id")
        if isinstance(counted, bool) or counted < 0:
            raise ValidationError("counted quantity must be non-negative")
        expected = self._balances[(item.sku, location)]
        variance = counted - expected
        movement = None
        if variance:
            movement = self.adjust(
                item.sku,
                location,
                variance,
                actor,
                "cycle count variance",
                authorized=authorized,
            )
        return CycleCountResult(
            item.sku,
            location,
            expected,
            counted,
            variance,
            movement.id if movement else None,
        )

    def reorder_suggestions(self, *, at: datetime | None = None) -> list[ReorderSuggestion]:
        moment = at or self._now()
        result = []
        for item in self.items:
            if not item.active or item.reorder_point == 0:
                continue
            if item.kind == StockKind.SERIALIZED:
                on_hand = sum(unit.sku == item.sku and unit.usable for unit in self._units.values())
            else:
                on_hand = sum(
                    quantity for (sku, _), quantity in self._balances.items() if sku == item.sku
                )
            reserved = sum(
                reservation.quantity
                for reservation in self._reservations.values()
                if reservation.sku == item.sku
                and reservation.status == ReservationStatus.HELD
                and reservation.ends_at >= moment
            )
            projected = on_hand - reserved
            if projected <= item.reorder_point:
                result.append(
                    ReorderSuggestion(
                        item.sku,
                        on_hand,
                        reserved,
                        item.reorder_point,
                        max(1, item.reorder_point * 2 - projected),
                    )
                )
        return sorted(result, key=lambda suggestion: suggestion.sku)

    def valuation(self) -> InventoryValuation:
        bulk_value = Decimal("0")
        serialized_value = Decimal("0")
        by_category: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for item in self.items:
            if item.kind == StockKind.SERIALIZED:
                count = sum(
                    unit.sku == item.sku and unit.status != AssetStatus.RETIRED
                    for unit in self._units.values()
                )
                value = item.replacement_cost * count
                serialized_value += value
            else:
                count = sum(
                    quantity for (sku, _), quantity in self._balances.items() if sku == item.sku
                )
                value = item.replacement_cost * count
                bulk_value += value
            by_category[item.category] += value
        total = bulk_value + serialized_value
        return InventoryValuation(
            self.currency,
            bulk_value.quantize(CENT),
            serialized_value.quantize(CENT),
            total.quantize(CENT),
            {key: value.quantize(CENT) for key, value in sorted(by_category.items())},
        )

    def movement_history(
        self,
        *,
        sku: str = "",
        movement_type: MovementType | None = None,
        location: str = "",
        reference: str = "",
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
    ) -> list[StockMovement]:
        normalized_sku = sku.strip().upper()
        return [
            movement
            for movement in self._movements
            if (not normalized_sku or movement.sku == normalized_sku)
            and (movement_type is None or movement.movement_type == movement_type)
            and (
                not location
                or location.casefold()
                in {movement.source.casefold(), movement.destination.casefold()}
            )
            and (not reference or movement.reference == reference)
            and (starts_at is None or movement.occurred_at >= starts_at)
            and (ends_at is None or movement.occurred_at <= ends_at)
        ]

    def report(self, *, at: datetime | None = None) -> InventoryReport:
        moment = at or self._now()
        return InventoryReport(
            item_count=len(self._items),
            active_items=sum(item.active for item in self._items.values()),
            asset_units=len(self._units),
            available_units=sum(unit.usable for unit in self._units.values()),
            open_reservations=sum(
                reservation.status == ReservationStatus.HELD
                for reservation in self._reservations.values()
            ),
            overdue_maintenance=sum(
                ticket.due_at < moment
                and ticket.status in {MaintenanceStatus.OPEN, MaintenanceStatus.IN_PROGRESS}
                for ticket in self._maintenance.values()
            ),
            movement_count=len(self._movements),
            by_kind=dict(Counter(item.kind.value for item in self._items.values())),
            by_condition=dict(Counter(unit.condition.value for unit in self._units.values())),
        )

    def _movement(
        self,
        movement_type: MovementType,
        sku: str,
        quantity: int,
        source: str,
        destination: str,
        actor: str,
        *,
        reference: str = "",
        reason: str = "",
        unit_ids: tuple[str, ...] = (),
        unit_cost: Decimal = Decimal("0"),
        at: datetime | None = None,
    ) -> StockMovement:
        sequence = len(self._movements) + 1
        movement = StockMovement(
            sequence=sequence,
            id=f"MOV-{sequence:08d}",
            movement_type=movement_type,
            sku=sku,
            quantity=quantity,
            source=source,
            destination=destination,
            actor=actor,
            occurred_at=at or self._now(),
            reference=reference.strip(),
            reason=reason.strip(),
            unit_ids=unit_ids,
            unit_cost=unit_cost,
        )
        self._movements.append(movement)
        return movement

    def _validate_units(
        self,
        unit_ids: tuple[str, ...],
        sku: str,
        location: str,
        status: AssetStatus,
    ) -> None:
        if not unit_ids or len(unit_ids) != len(set(unit_ids)):
            raise ValidationError("unique asset unit ids are required")
        for identifier in unit_ids:
            unit = self.require_unit(identifier)
            if unit.sku != sku:
                raise ValidationError(f"asset unit belongs to another SKU: {identifier}")
            if unit.location != location or unit.status != status:
                raise ConflictError(f"asset unit is unavailable at {location}: {identifier}")
            if unit.condition in {AssetCondition.DAMAGED, AssetCondition.UNSAFE}:
                raise ConflictError(f"asset unit condition prevents movement: {identifier}")

    def _reserved_quantity(self, sku: str, location: str) -> int:
        return sum(
            reservation.quantity
            for reservation in self._reservations.values()
            if reservation.sku == sku
            and reservation.location == location
            and reservation.status == ReservationStatus.HELD
        )

    @staticmethod
    def _require_active(item: StockItem) -> None:
        if not item.active:
            raise WorkflowError(f"stock item is inactive: {item.sku}")

    def _now(self) -> datetime:
        return _aware(self._clock(), "inventory clock")
