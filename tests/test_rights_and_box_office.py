from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from lumenstage.domain.box_office_ledger import BoxOfficeLedger, TenderType, TicketBand
from lumenstage.domain.rights import RightsGrant, RightsLedger, RightsRequest, RightType
from lumenstage.errors import ConflictError, NotFoundError, ValidationError, WorkflowError

NOW = datetime(2026, 11, 1, 19, tzinfo=UTC)


def grant(**overrides: object) -> RightsGrant:
    values: dict[str, object] = {
        "id": "grant-stage",
        "production_id": "prod-1",
        "rightsholder": "The Estate",
        "right_type": RightType.STAGE,
        "territories": frozenset({"GB", "us"}),
        "valid_from": NOW - timedelta(days=30),
        "valid_until": NOW + timedelta(days=30),
        "royalty_rate": Decimal("0.10"),
        "minimum_royalty": Decimal("500"),
        "max_performances": 2,
        "max_audience": 500,
    }
    values.update(overrides)
    return RightsGrant(**values)  # type: ignore[arg-type]


def request(**overrides: object) -> RightsRequest:
    values: dict[str, object] = {
        "performance_id": "perf-1",
        "production_id": "prod-1",
        "right_type": RightType.STAGE,
        "territory": "gb",
        "occurs_at": NOW,
        "audience": 300,
        "gross_receipts": Decimal("8000"),
    }
    values.update(overrides)
    return RightsRequest(**values)  # type: ignore[arg-type]


def test_grant_normalizes_terms_and_calculates_royalty() -> None:
    item = grant()
    assert item.territories == frozenset({"GB", "US"})
    assert item.currency == "USD"
    assert item.royalty_for(Decimal("8000")) == Decimal("800.00")
    assert item.royalty_for(Decimal("1000")) == Decimal("500.00")


def test_grant_rejects_invalid_window_rate_and_currency() -> None:
    with pytest.raises(ValidationError, match="must not precede"):
        grant(valid_from=NOW, valid_until=NOW - timedelta(days=1))
    with pytest.raises(ValidationError, match="between"):
        grant(royalty_rate=Decimal("1.1"))
    with pytest.raises(ValidationError, match="currency"):
        grant(currency="dollars")


def test_request_requires_territory_timezone_and_nonnegative_amounts() -> None:
    with pytest.raises(ValidationError, match="territory"):
        request(territory="England")
    with pytest.raises(ValidationError, match="timezone"):
        request(occurs_at=datetime(2026, 11, 1, 19))
    with pytest.raises(ValidationError, match="gross_receipts"):
        request(gross_receipts=Decimal("-1"))


def test_ledger_selects_cheapest_eligible_grant() -> None:
    ledger = RightsLedger()
    ledger.add_grant(grant(id="expensive", royalty_rate=Decimal("0.15")))
    ledger.add_grant(grant(id="cheaper", royalty_rate=Decimal("0.08")))
    decision = ledger.quote(request())
    assert decision.allowed
    assert decision.grant_id == "cheaper"
    assert decision.royalty_due == Decimal("640.00")


def test_authorization_consumes_allowance_and_prevents_duplicates() -> None:
    ledger = RightsLedger()
    ledger.add_grant(grant(max_performances=1))
    usage = ledger.authorize(request(), "Rights manager", recorded_at=NOW)
    assert usage.grant_id == "grant-stage"
    assert ledger.remaining_performances("grant-stage") == 0
    with pytest.raises(ConflictError, match="already authorized"):
        ledger.authorize(request(), "Rights manager")
    denied = request(performance_id="perf-2")
    with pytest.raises(WorkflowError, match="allowance exhausted"):
        ledger.authorize(denied, "Rights manager")


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"production_id": "other"}, "no grant for production"),
        ({"right_type": RightType.STREAM}, "stream rights unavailable"),
        ({"territory": "FR"}, "territory FR not covered"),
        ({"occurs_at": NOW + timedelta(days=60)}, "outside licensed window"),
        ({"audience": 501}, "audience exceeds"),
    ],
)
def test_quote_explains_denials(overrides: dict[str, object], reason: str) -> None:
    ledger = RightsLedger()
    ledger.add_grant(grant())
    decision = ledger.quote(request(**overrides))
    assert not decision.allowed
    assert reason in decision.reason


def test_revoke_releases_performance_allowance() -> None:
    ledger = RightsLedger()
    ledger.add_grant(grant(max_performances=1))
    ledger.authorize(request(), "Rights manager", recorded_at=NOW)
    revoked = ledger.revoke("perf-1", RightType.STAGE)
    assert revoked.request.performance_id == "perf-1"
    assert ledger.remaining_performances("grant-stage") == 1
    with pytest.raises(NotFoundError):
        ledger.revoke("missing", RightType.STAGE)


def test_exposure_groups_usage_by_currency() -> None:
    ledger = RightsLedger()
    ledger.add_grant(grant(id="usd", max_performances=2))
    ledger.add_grant(
        grant(
            id="gbp",
            currency="GBP",
            territories=frozenset({"GB"}),
            royalty_rate=Decimal("0.05"),
            active=False,
        )
    )
    ledger.authorize(request(), "Manager", recorded_at=NOW)
    ledger.replace_grant(grant(id="usd", max_performances=1, active=False))
    ledger.replace_grant(
        grant(
            id="gbp",
            currency="GBP",
            territories=frozenset({"GB"}),
            royalty_rate=Decimal("0.05"),
        )
    )
    ledger.authorize(request(performance_id="perf-2"), "Manager", recorded_at=NOW)
    reports = {report.currency: report for report in ledger.exposure()}
    assert reports["USD"].royalty_due == Decimal("800.00")
    assert reports["GBP"].usage_count == 1
    assert reports["GBP"].audience == 300


def test_expiring_grants_are_sorted() -> None:
    ledger = RightsLedger()
    ledger.add_grant(grant(id="later", valid_until=NOW + timedelta(days=10)))
    ledger.add_grant(grant(id="sooner", valid_until=NOW + timedelta(days=5)))
    result = ledger.expiring_between(NOW, NOW + timedelta(days=20))
    assert [item.id for item in result] == ["sooner", "later"]


@pytest.fixture()
def box_office() -> BoxOfficeLedger:
    ledger = BoxOfficeLedger("perf-1", 100, currency="gbp")
    ledger.add_band(
        TicketBand(
            "A",
            "Premium",
            Decimal("50"),
            60,
            service_fee=Decimal("2"),
            tax_rate=Decimal("0.20"),
        )
    )
    ledger.add_band(TicketBand("B", "Standard", Decimal("25"), 40))
    return ledger


def test_ticket_band_validates_allocation_prices_and_tax() -> None:
    with pytest.raises(ValidationError, match="allocation"):
        TicketBand("A", "Band", Decimal("10"), 0)
    with pytest.raises(ValidationError, match="face_value"):
        TicketBand("A", "Band", Decimal("-1"), 2)
    with pytest.raises(ValidationError, match="tax_rate"):
        TicketBand("A", "Band", Decimal("10"), 2, tax_rate=Decimal("2"))


def test_band_allocations_cannot_exceed_capacity() -> None:
    ledger = BoxOfficeLedger("perf", 10)
    ledger.add_band(TicketBand("A", "A", Decimal("10"), 8))
    with pytest.raises(ConflictError, match="capacity"):
        ledger.add_band(TicketBand("B", "B", Decimal("10"), 3))


def test_sale_calculates_discount_tax_and_fee(box_office: BoxOfficeLedger) -> None:
    sale = box_office.record_sale(
        "sale-1",
        "a",
        2,
        TenderType.CARD,
        discount=Decimal("10"),
        occurred_at=NOW,
    )
    assert sale.gross == Decimal("100.00")
    assert sale.fee_total == Decimal("4.00")
    assert sale.tax == Decimal("18.00")
    assert sale.total == Decimal("112.00")
    assert box_office.available("A") == 58


def test_inventory_and_duplicate_sale_are_rejected(box_office: BoxOfficeLedger) -> None:
    box_office.record_sale("sale-1", "B", 40, TenderType.CASH, occurred_at=NOW)
    with pytest.raises(ConflictError, match="insufficient"):
        box_office.record_sale("sale-2", "B", 1, TenderType.CASH)
    with pytest.raises(ConflictError, match="already exists"):
        box_office.record_sale("sale-1", "A", 1, TenderType.CASH)


def test_complimentary_tickets_have_no_value_and_can_be_released(
    box_office: BoxOfficeLedger,
) -> None:
    sale = box_office.record_sale("comp-1", "B", 4, TenderType.COMPLIMENTARY, occurred_at=NOW)
    assert sale.total == Decimal("0.00")
    box_office.release_comps("comp-1", 2)
    assert sale.active_quantity == 2
    with pytest.raises(ValidationError, match="released"):
        box_office.refund("comp-1", 1)


def test_refund_releases_inventory_and_optionally_returns_fees(
    box_office: BoxOfficeLedger,
) -> None:
    sale = box_office.record_sale("sale-1", "A", 2, TenderType.CARD, occurred_at=NOW)
    assert box_office.refund("sale-1", 1) == Decimal("60.00")
    assert sale.net_total == Decimal("64.00")
    assert box_office.available("A") == 59
    assert box_office.refund("sale-1", 1, refund_fees=True) == Decimal("62.00")
    with pytest.raises(ConflictError, match="exceeds"):
        box_office.refund("sale-1", 1)


def test_settlement_summarizes_paid_comps_and_refunds(box_office: BoxOfficeLedger) -> None:
    box_office.record_sale("paid", "A", 2, TenderType.CARD, occurred_at=NOW)
    box_office.record_sale("comp", "B", 3, TenderType.COMPLIMENTARY, occurred_at=NOW)
    box_office.refund("paid", 1)
    report = box_office.settlement()
    assert report.sold == 5
    assert report.refunded == 1
    assert report.attendance == 4
    assert report.complimentary == 3
    assert report.paid_attendance == 1
    assert report.occupancy == pytest.approx(0.04)
    assert report.net_receipts == Decimal("64.00")
    assert report.average_paid_ticket == Decimal("64.00")


def test_band_sales_and_tender_totals(box_office: BoxOfficeLedger) -> None:
    box_office.record_sale("card", "A", 2, TenderType.CARD, occurred_at=NOW)
    box_office.record_sale("cash", "B", 1, TenderType.CASH, occurred_at=NOW)
    bands = {row.code: row for row in box_office.band_sales()}
    assert bands["A"].sell_through == pytest.approx(2 / 60)
    assert bands["B"].net_receipts == Decimal("25.00")
    assert box_office.tender_totals()[TenderType.CARD] == Decimal("124.00")


def test_reconciliation_reports_balanced_and_variance(box_office: BoxOfficeLedger) -> None:
    box_office.record_sale("sale", "B", 2, TenderType.CASH, occurred_at=NOW)
    balanced = box_office.reconcile({TenderType.CASH: Decimal("50")})
    assert balanced.balanced
    assert balanced.variance == Decimal("0.00")
    short = box_office.reconcile({TenderType.CASH: Decimal("49.50")})
    assert not short.balanced
    assert short.variance == Decimal("-0.50")


def test_unknown_band_and_sale_raise_not_found(box_office: BoxOfficeLedger) -> None:
    with pytest.raises(NotFoundError, match="band"):
        box_office.available("X")
    with pytest.raises(NotFoundError, match="sale"):
        box_office.refund("missing", 1)
