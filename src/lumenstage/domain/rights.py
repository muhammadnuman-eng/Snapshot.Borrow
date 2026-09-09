"""Performance-rights authorization and royalty accounting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

from lumenstage.errors import ConflictError, NotFoundError, ValidationError, WorkflowError

CENT = Decimal("0.01")


def _money(value: Decimal | str | int, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValidationError(f"{field_name} must be a decimal amount") from exc
    if not amount.is_finite() or amount < 0:
        raise ValidationError(f"{field_name} must be finite and non-negative")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


class RightType(StrEnum):
    STAGE = "stage"
    STREAM = "stream"
    RECORDING = "recording"
    PROMOTIONAL = "promotional"


@dataclass(frozen=True, slots=True)
class RightsGrant:
    """A rightsholder's bounded permission to exploit one production."""

    id: str
    production_id: str
    rightsholder: str
    right_type: RightType
    territories: frozenset[str]
    valid_from: datetime
    valid_until: datetime
    currency: str = "USD"
    royalty_rate: Decimal = Decimal("0")
    minimum_royalty: Decimal = Decimal("0")
    max_performances: int | None = None
    max_audience: int | None = None
    active: bool = True

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.id, "id"),
            (self.production_id, "production_id"),
            (self.rightsholder, "rightsholder"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f"{field_name} must be a non-empty string")
        if self.valid_from.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValidationError("rights dates must be timezone-aware")
        if self.valid_until < self.valid_from:
            raise ValidationError("valid_until must not precede valid_from")
        normalized = frozenset(item.strip().upper() for item in self.territories if item.strip())
        if not normalized:
            raise ValidationError("at least one territory is required")
        object.__setattr__(self, "territories", normalized)
        currency = self.currency.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValidationError("currency must be a three-letter code")
        object.__setattr__(self, "currency", currency)
        rate = Decimal(str(self.royalty_rate))
        if not rate.is_finite() or rate < 0 or rate > 1:
            raise ValidationError("royalty_rate must be between 0 and 1")
        object.__setattr__(self, "royalty_rate", rate)
        object.__setattr__(self, "minimum_royalty", _money(self.minimum_royalty, "minimum_royalty"))
        for value, field_name in (
            (self.max_performances, "max_performances"),
            (self.max_audience, "max_audience"),
        ):
            if value is not None and (isinstance(value, bool) or value < 1):
                raise ValidationError(f"{field_name} must be a positive integer")

    def covers(self, request: RightsRequest) -> bool:
        return (
            self.active
            and request.production_id == self.production_id
            and request.right_type == self.right_type
            and request.territory in self.territories
            and self.valid_from <= request.occurs_at <= self.valid_until
            and (self.max_audience is None or request.audience <= self.max_audience)
        )

    def royalty_for(self, gross_receipts: Decimal) -> Decimal:
        variable = _money(gross_receipts, "gross_receipts") * self.royalty_rate
        return max(self.minimum_royalty, variable).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class RightsRequest:
    performance_id: str
    production_id: str
    right_type: RightType
    territory: str
    occurs_at: datetime
    audience: int
    gross_receipts: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.performance_id.strip() or not self.production_id.strip():
            raise ValidationError("performance_id and production_id are required")
        territory = self.territory.strip().upper()
        if len(territory) not in {2, 3} or not territory.isalpha():
            raise ValidationError("territory must be a two or three-letter code")
        object.__setattr__(self, "territory", territory)
        if self.occurs_at.tzinfo is None:
            raise ValidationError("occurs_at must be timezone-aware")
        if isinstance(self.audience, bool) or self.audience < 0:
            raise ValidationError("audience must be a non-negative integer")
        object.__setattr__(self, "gross_receipts", _money(self.gross_receipts, "gross_receipts"))


@dataclass(frozen=True, slots=True)
class RightsDecision:
    allowed: bool
    reason: str
    grant_id: str | None = None
    royalty_due: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class RightsUsage:
    request: RightsRequest
    grant_id: str
    royalty_due: Decimal
    approved_by: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not self.approved_by.strip():
            raise ValidationError("approved_by is required")
        if self.recorded_at.tzinfo is None:
            raise ValidationError("recorded_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RightsExposure:
    currency: str
    usage_count: int
    audience: int
    gross_receipts: Decimal
    royalty_due: Decimal


class RightsLedger:
    """Select grants, reserve performance uses, and calculate royalties."""

    def __init__(self) -> None:
        self._grants: dict[str, RightsGrant] = {}
        self._usage: list[RightsUsage] = []

    @property
    def grants(self) -> tuple[RightsGrant, ...]:
        return tuple(sorted(self._grants.values(), key=lambda grant: grant.id))

    @property
    def usage(self) -> tuple[RightsUsage, ...]:
        return tuple(self._usage)

    def add_grant(self, grant: RightsGrant) -> None:
        if grant.id in self._grants:
            raise ConflictError(f"rights grant already exists: {grant.id}")
        self._grants[grant.id] = grant

    def replace_grant(self, grant: RightsGrant) -> None:
        if grant.id not in self._grants:
            raise NotFoundError(f"rights grant not found: {grant.id}")
        self._grants[grant.id] = grant

    def require_grant(self, grant_id: str) -> RightsGrant:
        try:
            return self._grants[grant_id]
        except KeyError as exc:
            raise NotFoundError(f"rights grant not found: {grant_id}") from exc

    def uses_for(self, grant_id: str) -> list[RightsUsage]:
        self.require_grant(grant_id)
        return [usage for usage in self._usage if usage.grant_id == grant_id]

    def remaining_performances(self, grant_id: str) -> int | None:
        grant = self.require_grant(grant_id)
        if grant.max_performances is None:
            return None
        return max(0, grant.max_performances - len(self.uses_for(grant_id)))

    def eligible_grants(self, request: RightsRequest) -> list[RightsGrant]:
        result = []
        for grant in self._grants.values():
            if not grant.covers(request):
                continue
            remaining = self.remaining_performances(grant.id)
            if remaining is None or remaining > 0:
                result.append(grant)
        return sorted(
            result,
            key=lambda grant: (
                grant.royalty_for(request.gross_receipts),
                grant.valid_until,
                grant.id,
            ),
        )

    def quote(self, request: RightsRequest) -> RightsDecision:
        eligible = self.eligible_grants(request)
        if eligible:
            grant = eligible[0]
            return RightsDecision(
                True,
                "covered",
                grant.id,
                grant.royalty_for(request.gross_receipts),
            )
        reasons = self._rejection_reasons(request)
        return RightsDecision(False, "; ".join(reasons) or "no matching rights grant")

    def authorize(
        self,
        request: RightsRequest,
        approved_by: str,
        *,
        recorded_at: datetime | None = None,
    ) -> RightsUsage:
        duplicate = next(
            (
                usage
                for usage in self._usage
                if usage.request.performance_id == request.performance_id
                and usage.request.right_type == request.right_type
            ),
            None,
        )
        if duplicate is not None:
            raise ConflictError(
                f"rights already authorized for performance: {request.performance_id}"
            )
        decision = self.quote(request)
        if not decision.allowed or decision.grant_id is None:
            raise WorkflowError(f"rights request denied: {decision.reason}")
        usage = RightsUsage(
            request=request,
            grant_id=decision.grant_id,
            royalty_due=decision.royalty_due,
            approved_by=approved_by,
            recorded_at=recorded_at or datetime.now(UTC),
        )
        self._usage.append(usage)
        return usage

    def revoke(self, performance_id: str, right_type: RightType) -> RightsUsage:
        for usage in self._usage:
            if (
                usage.request.performance_id == performance_id
                and usage.request.right_type == right_type
            ):
                self._usage.remove(usage)
                return usage
        raise NotFoundError(f"rights usage not found for performance: {performance_id}")

    def exposure(self, *, production_id: str | None = None) -> list[RightsExposure]:
        selected = [
            usage
            for usage in self._usage
            if production_id is None or usage.request.production_id == production_id
        ]
        currencies = sorted({self.require_grant(usage.grant_id).currency for usage in selected})
        reports = []
        for currency in currencies:
            rows = [
                usage
                for usage in selected
                if self.require_grant(usage.grant_id).currency == currency
            ]
            reports.append(
                RightsExposure(
                    currency=currency,
                    usage_count=len(rows),
                    audience=sum(row.request.audience for row in rows),
                    gross_receipts=sum((row.request.gross_receipts for row in rows), Decimal("0")),
                    royalty_due=sum((row.royalty_due for row in rows), Decimal("0")),
                )
            )
        return reports

    def expiring_between(self, starts_at: datetime, ends_at: datetime) -> list[RightsGrant]:
        if starts_at.tzinfo is None or ends_at.tzinfo is None:
            raise ValidationError("expiry range must be timezone-aware")
        if ends_at < starts_at:
            raise ValidationError("expiry range end must not precede start")
        return sorted(
            (grant for grant in self._grants.values() if starts_at <= grant.valid_until <= ends_at),
            key=lambda grant: grant.valid_until,
        )

    def _rejection_reasons(self, request: RightsRequest) -> list[str]:
        production = [
            grant for grant in self._grants.values() if grant.production_id == request.production_id
        ]
        if not production:
            return ["no grant for production"]
        if not any(grant.right_type == request.right_type for grant in production):
            return [f"{request.right_type.value} rights unavailable"]
        matching_type = [grant for grant in production if grant.right_type == request.right_type]
        reasons = []
        if not any(request.territory in grant.territories for grant in matching_type):
            reasons.append(f"territory {request.territory} not covered")
        if not any(
            grant.valid_from <= request.occurs_at <= grant.valid_until for grant in matching_type
        ):
            reasons.append("performance outside licensed window")
        if any(
            grant.max_audience is not None and request.audience > grant.max_audience
            for grant in matching_type
        ):
            reasons.append("audience exceeds licensed capacity")
        if matching_type and all(
            self.remaining_performances(grant.id) == 0 for grant in matching_type
        ):
            reasons.append("performance allowance exhausted")
        return reasons
