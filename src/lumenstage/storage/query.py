"""In-process query expressions for JSON collections."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, Self

from lumenstage.errors import ValidationError

Row = dict[str, Any]


class Predicate(Protocol):
    def __call__(self, row: Mapping[str, Any]) -> bool: ...


def resolve(row: Mapping[str, Any], path: str, *, default: Any = None) -> Any:
    """Resolve a dot-separated path from nested dictionaries."""
    current: Any = row
    for segment in path.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return default
        current = current[segment]
    return current


@dataclass(frozen=True, slots=True)
class Equals:
    path: str
    expected: Any
    case_sensitive: bool = True

    def __call__(self, row: Mapping[str, Any]) -> bool:
        actual = resolve(row, self.path)
        if not self.case_sensitive and isinstance(actual, str) and isinstance(self.expected, str):
            return actual.casefold() == self.expected.casefold()
        return actual == self.expected


@dataclass(frozen=True, slots=True)
class Contains:
    path: str
    expected: Any
    case_sensitive: bool = False

    def __call__(self, row: Mapping[str, Any]) -> bool:
        actual = resolve(row, self.path)
        if isinstance(actual, str):
            needle = str(self.expected)
            return (
                needle in actual if self.case_sensitive else needle.casefold() in actual.casefold()
            )
        if isinstance(actual, Sequence):
            return self.expected in actual
        if isinstance(actual, Mapping):
            return self.expected in actual
        return False


@dataclass(frozen=True, slots=True)
class InSet:
    path: str
    values: frozenset[Any]

    def __call__(self, row: Mapping[str, Any]) -> bool:
        return resolve(row, self.path) in self.values


@dataclass(frozen=True, slots=True)
class Between:
    path: str
    minimum: Any | None = None
    maximum: Any | None = None
    inclusive: bool = True

    def __call__(self, row: Mapping[str, Any]) -> bool:
        value = resolve(row, self.path)
        if value is None:
            return False
        try:
            if self.minimum is not None:
                if self.inclusive and value < self.minimum:
                    return False
                if not self.inclusive and value <= self.minimum:
                    return False
            if self.maximum is not None:
                if self.inclusive and value > self.maximum:
                    return False
                if not self.inclusive and value >= self.maximum:
                    return False
        except TypeError:
            return False
        return True


@dataclass(frozen=True, slots=True)
class Exists:
    path: str
    truthy: bool = False

    def __call__(self, row: Mapping[str, Any]) -> bool:
        marker = object()
        value = resolve(row, self.path, default=marker)
        return bool(value) if self.truthy else value is not marker


@dataclass(frozen=True, slots=True)
class AllOf:
    predicates: tuple[Predicate, ...]

    def __call__(self, row: Mapping[str, Any]) -> bool:
        return all(predicate(row) for predicate in self.predicates)


@dataclass(frozen=True, slots=True)
class AnyOf:
    predicates: tuple[Predicate, ...]

    def __call__(self, row: Mapping[str, Any]) -> bool:
        return any(predicate(row) for predicate in self.predicates)


@dataclass(frozen=True, slots=True)
class Negate:
    predicate: Predicate

    def __call__(self, row: Mapping[str, Any]) -> bool:
        return not self.predicate(row)


@dataclass(frozen=True, slots=True)
class SortKey:
    path: str
    descending: bool = False
    missing_last: bool = True


@dataclass(slots=True)
class QueryResult:
    rows: list[Row]
    total: int
    offset: int
    limit: int | None

    @property
    def has_more(self) -> bool:
        return self.limit is not None and self.offset + len(self.rows) < self.total


@dataclass(slots=True)
class Query:
    predicates: list[Predicate] = field(default_factory=list)
    sort_keys: list[SortKey] = field(default_factory=list)
    selected_fields: tuple[str, ...] | None = None
    offset_value: int = 0
    limit_value: int | None = None

    def where(self, predicate: Predicate) -> Self:
        self.predicates.append(predicate)
        return self

    def order_by(
        self,
        path: str,
        *,
        descending: bool = False,
        missing_last: bool = True,
    ) -> Self:
        self.sort_keys.append(SortKey(path, descending, missing_last))
        return self

    def select(self, *paths: str) -> Self:
        if not paths or any(not path.strip() for path in paths):
            raise ValidationError("select requires non-empty field paths")
        self.selected_fields = tuple(paths)
        return self

    def offset(self, count: int) -> Self:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValidationError("offset must be a non-negative integer")
        self.offset_value = count
        return self

    def limit(self, count: int | None) -> Self:
        if count is not None and (
            isinstance(count, bool) or not isinstance(count, int) or count < 1
        ):
            raise ValidationError("limit must be a positive integer or None")
        self.limit_value = count
        return self

    def execute(self, rows: Iterable[Mapping[str, Any]]) -> QueryResult:
        matched = [dict(row) for row in rows if all(rule(row) for rule in self.predicates)]
        for sort_key in reversed(self.sort_keys):
            matched.sort(
                key=lambda row, key=sort_key: self._sortable(
                    resolve(row, key.path), missing_last=key.missing_last
                ),
                reverse=sort_key.descending,
            )
        total = len(matched)
        stop = None if self.limit_value is None else self.offset_value + self.limit_value
        page = matched[self.offset_value : stop]
        if self.selected_fields is not None:
            page = [{path: resolve(row, path) for path in self.selected_fields} for row in page]
        return QueryResult(page, total, self.offset_value, self.limit_value)

    @staticmethod
    def _sortable(value: Any, *, missing_last: bool) -> tuple[int, str, Any]:
        missing = value is None
        bucket = 1 if (missing and missing_last) else 0
        type_name = type(value).__name__
        comparable = value if isinstance(value, int | float | str) else repr(value)
        return bucket, type_name, comparable


@dataclass(slots=True)
class AggregateRow:
    key: Any
    count: int
    total: Decimal
    minimum: Decimal | None
    maximum: Decimal | None


def aggregate(
    rows: Iterable[Mapping[str, Any]],
    *,
    group_by: str,
    value_path: str | None = None,
) -> list[AggregateRow]:
    buckets: dict[Any, list[Decimal]] = defaultdict(list)
    counts: dict[Any, int] = defaultdict(int)
    for row in rows:
        key = resolve(row, group_by)
        counts[key] += 1
        if value_path is None:
            continue
        value = resolve(row, value_path)
        if value is None:
            continue
        try:
            buckets[key].append(Decimal(str(value)))
        except InvalidOperation as exc:
            raise ValidationError(f"{value_path} contains a non-numeric value") from exc
    result: list[AggregateRow] = []
    for key in sorted(counts, key=lambda item: (item is None, str(item))):
        values = buckets[key]
        result.append(
            AggregateRow(
                key=key,
                count=counts[key],
                total=sum(values, start=Decimal("0")),
                minimum=min(values, default=None),
                maximum=max(values, default=None),
            )
        )
    return result


def update_matching(
    rows: Iterable[Mapping[str, Any]],
    predicate: Predicate,
    updater: Callable[[Row], Row | None],
) -> tuple[list[Row], int]:
    """Return a copied collection with matching rows updated or removed."""
    result: list[Row] = []
    changed = 0
    for source in rows:
        row = dict(source)
        if not predicate(row):
            result.append(row)
            continue
        replacement = updater(row)
        changed += 1
        if replacement is not None:
            if not isinstance(replacement, dict):
                raise ValidationError("query updater must return a row or None")
            result.append(replacement)
    return result, changed
