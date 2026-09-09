"""Ticket inventory, refunds, settlement, and tender reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

from lumenstage.errors import ConflictError, NotFoundError, ValidationError

CENT = Decimal("0.01")


def as_money(value: Decimal | str | int, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValidationError(f"{field_name} must be a decimal amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValidationError(f"{field_name} must be finite and non-negative")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


class TenderType(StrEnum):
    CASH = "cash"
    CARD = "card"
    TRANSFER = "transfer"
    VOUCHER = "voucher"
    COMPLIMENTARY = "complimentary"


@dataclass(frozen=True, slots=True)
class TicketBand:
    code: str
    name: str
    face_value: Decimal
    allocation: int
    service_fee: Decimal = Decimal("0")
    tax_rate: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        code = self.code.strip().upper()
        if not code or not self.name.strip():
            raise ValidationError("ticket band code and name are required")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "face_value", as_money(self.face_value, "face_value"))
        object.__setattr__(self, "service_fee", as_money(self.service_fee, "service_fee"))
        if isinstance(self.allocation, bool) or self.allocation < 1:
            raise ValidationError("allocation must be a positive integer")
        rate = Decimal(str(self.tax_rate))
        if not rate.is_finite() or rate < 0 or rate > 1:
            raise ValidationError("tax_rate must be between 0 and 1")
        object.__setattr__(self, "tax_rate", rate)


@dataclass(slots=True)
class TicketSale:
    id: str
    band_code: str
    quantity: int
    unit_price: Decimal
    service_fee: Decimal
    tax: Decimal
    discount: Decimal
    tender: TenderType
    occurred_at: datetime
    refunded_quantity: int = 0
    refund_total: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValidationError("sale id is required")
        if isinstance(self.quantity, bool) or self.quantity < 1:
            raise ValidationError("sale quantity must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValidationError("sale timestamp must be timezone-aware")

    @property
    def complimentary(self) -> bool:
        return self.tender == TenderType.COMPLIMENTARY

    @property
    def gross(self) -> Decimal:
        return (self.unit_price * self.quantity).quantize(CENT)

    @property
    def fee_total(self) -> Decimal:
        return (self.service_fee * self.quantity).quantize(CENT)

    @property
    def total(self) -> Decimal:
        return (self.gross + self.fee_total + self.tax - self.discount).quantize(CENT)

    @property
    def net_total(self) -> Decimal:
        return (self.total - self.refund_total).quantize(CENT)

    @property
    def active_quantity(self) -> int:
        return self.quantity - self.refunded_quantity


@dataclass(frozen=True, slots=True)
class BandSales:
    code: str
    sold: int
    refunded: int
    active: int
    allocation: int
    net_receipts: Decimal

    @property
    def sell_through(self) -> float:
        return self.active / self.allocation


@dataclass(frozen=True, slots=True)
class SettlementReport:
    performance_id: str
    currency: str
    capacity: int
    sold: int
    refunded: int
    complimentary: int
    attendance: int
    gross_sales: Decimal
    discounts: Decimal
    fees: Decimal
    taxes: Decimal
    refunds: Decimal
    net_receipts: Decimal

    @property
    def paid_attendance(self) -> int:
        return self.attendance - self.complimentary

    @property
    def occupancy(self) -> float:
        return self.attendance / self.capacity

    @property
    def average_paid_ticket(self) -> Decimal:
        if self.paid_attendance <= 0:
            return Decimal("0.00")
        return (self.net_receipts / self.paid_attendance).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Reconciliation:
    expected: Decimal
    declared: Decimal
    variance: Decimal
    balanced: bool


class BoxOfficeLedger:
    """Maintain one performance's ticket inventory and financial settlement."""

    def __init__(self, performance_id: str, capacity: int, *, currency: str = "USD") -> None:
        if not performance_id.strip():
            raise ValidationError("performance_id is required")
        if isinstance(capacity, bool) or capacity < 1:
            raise ValidationError("capacity must be a positive integer")
        currency = currency.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValidationError("currency must be a three-letter code")
        self.performance_id = performance_id.strip()
        self.capacity = capacity
        self.currency = currency
        self._bands: dict[str, TicketBand] = {}
        self._sales: dict[str, TicketSale] = {}

    @property
    def bands(self) -> tuple[TicketBand, ...]:
        return tuple(sorted(self._bands.values(), key=lambda band: band.code))

    @property
    def sales(self) -> tuple[TicketSale, ...]:
        return tuple(sorted(self._sales.values(), key=lambda sale: (sale.occurred_at, sale.id)))

    def add_band(self, band: TicketBand) -> None:
        if band.code in self._bands:
            raise ConflictError(f"ticket band already exists: {band.code}")
        if sum(item.allocation for item in self._bands.values()) + band.allocation > self.capacity:
            raise ConflictError("ticket allocations exceed venue capacity")
        self._bands[band.code] = band

    def require_band(self, code: str) -> TicketBand:
        try:
            return self._bands[code.strip().upper()]
        except KeyError as exc:
            raise NotFoundError(f"ticket band not found: {code}") from exc

    def require_sale(self, sale_id: str) -> TicketSale:
        try:
            return self._sales[sale_id]
        except KeyError as exc:
            raise NotFoundError(f"ticket sale not found: {sale_id}") from exc

    def available(self, band_code: str | None = None) -> int:
        if band_code is None:
            return self.capacity - sum(sale.active_quantity for sale in self._sales.values())
        band = self.require_band(band_code)
        active = sum(
            sale.active_quantity for sale in self._sales.values() if sale.band_code == band.code
        )
        return band.allocation - active

    def record_sale(
        self,
        sale_id: str,
        band_code: str,
        quantity: int,
        tender: TenderType,
        *,
        discount: Decimal | str | int = Decimal("0"),
        occurred_at: datetime | None = None,
    ) -> TicketSale:
        if sale_id in self._sales:
            raise ConflictError(f"ticket sale already exists: {sale_id}")
        if isinstance(quantity, bool) or quantity < 1:
            raise ValidationError("quantity must be a positive integer")
        band = self.require_band(band_code)
        if quantity > self.available(band.code):
            raise ConflictError(f"insufficient inventory in band {band.code}")
        discount_amount = as_money(discount, "discount")
        if tender == TenderType.COMPLIMENTARY:
            if discount_amount:
                raise ValidationError("complimentary tickets cannot have a discount")
            unit_price = Decimal("0.00")
            fee = Decimal("0.00")
            tax = Decimal("0.00")
        else:
            unit_price = band.face_value
            fee = band.service_fee
            subtotal = unit_price * quantity
            if discount_amount > subtotal:
                raise ValidationError("discount cannot exceed face value")
            tax = ((subtotal - discount_amount) * band.tax_rate).quantize(
                CENT, rounding=ROUND_HALF_UP
            )
        sale = TicketSale(
            id=sale_id,
            band_code=band.code,
            quantity=quantity,
            unit_price=unit_price,
            service_fee=fee,
            tax=tax,
            discount=discount_amount,
            tender=tender,
            occurred_at=occurred_at or datetime.now(UTC),
        )
        self._sales[sale.id] = sale
        return sale

    def refund(
        self,
        sale_id: str,
        quantity: int,
        *,
        refund_fees: bool = False,
    ) -> Decimal:
        sale = self.require_sale(sale_id)
        if sale.complimentary:
            raise ValidationError("complimentary tickets must be released, not refunded")
        if isinstance(quantity, bool) or quantity < 1:
            raise ValidationError("refund quantity must be positive")
        if quantity > sale.active_quantity:
            raise ConflictError("refund quantity exceeds active tickets")
        per_ticket_face = sale.unit_price - (sale.discount / sale.quantity)
        per_ticket_tax = sale.tax / sale.quantity
        per_ticket_fee = sale.service_fee if refund_fees else Decimal("0")
        amount = ((per_ticket_face + per_ticket_tax + per_ticket_fee) * quantity).quantize(
            CENT, rounding=ROUND_HALF_UP
        )
        sale.refunded_quantity += quantity
        sale.refund_total = (sale.refund_total + amount).quantize(CENT)
        return amount

    def release_comps(self, sale_id: str, quantity: int) -> None:
        sale = self.require_sale(sale_id)
        if not sale.complimentary:
            raise ValidationError("only complimentary tickets can be released")
        if isinstance(quantity, bool) or quantity < 1 or quantity > sale.active_quantity:
            raise ValidationError("release quantity exceeds active complimentary tickets")
        sale.refunded_quantity += quantity

    def band_sales(self) -> list[BandSales]:
        result = []
        for band in self.bands:
            rows = [sale for sale in self._sales.values() if sale.band_code == band.code]
            result.append(
                BandSales(
                    code=band.code,
                    sold=sum(row.quantity for row in rows),
                    refunded=sum(row.refunded_quantity for row in rows),
                    active=sum(row.active_quantity for row in rows),
                    allocation=band.allocation,
                    net_receipts=sum((row.net_total for row in rows), Decimal("0")),
                )
            )
        return result

    def settlement(self) -> SettlementReport:
        rows = list(self._sales.values())
        sold = sum(row.quantity for row in rows)
        refunded = sum(row.refunded_quantity for row in rows)
        complimentary = sum(row.active_quantity for row in rows if row.complimentary)
        return SettlementReport(
            performance_id=self.performance_id,
            currency=self.currency,
            capacity=self.capacity,
            sold=sold,
            refunded=refunded,
            complimentary=complimentary,
            attendance=sold - refunded,
            gross_sales=sum((row.gross for row in rows), Decimal("0")),
            discounts=sum((row.discount for row in rows), Decimal("0")),
            fees=sum((row.fee_total for row in rows), Decimal("0")),
            taxes=sum((row.tax for row in rows), Decimal("0")),
            refunds=sum((row.refund_total for row in rows), Decimal("0")),
            net_receipts=sum((row.net_total for row in rows), Decimal("0")),
        )

    def tender_totals(self) -> dict[TenderType, Decimal]:
        return {
            tender: sum(
                (sale.net_total for sale in self._sales.values() if sale.tender == tender),
                Decimal("0"),
            )
            for tender in TenderType
        }

    def reconcile(
        self,
        declared: dict[TenderType, Decimal | str | int],
        *,
        tolerance: Decimal | str | int = Decimal("0.01"),
    ) -> Reconciliation:
        expected = self.settlement().net_receipts
        declared_total = sum(
            (as_money(amount, f"declared.{tender.value}") for tender, amount in declared.items()),
            Decimal("0"),
        )
        allowed = as_money(tolerance, "tolerance")
        variance = (declared_total - expected).quantize(CENT)
        return Reconciliation(expected, declared_total, variance, abs(variance) <= allowed)
