"""Versioned schema migrations for LumenStage JSON stores."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from lumenstage.errors import ConflictError, StorageError, ValidationError
from lumenstage.storage.store import JsonDocumentStore

Snapshot = dict[str, Any]
MigrationFunction = Callable[[Snapshot], Snapshot]


@dataclass(frozen=True, slots=True)
class Migration:
    from_version: int
    to_version: int
    name: str
    apply: MigrationFunction

    def __post_init__(self) -> None:
        if self.from_version < 1 or self.to_version != self.from_version + 1:
            raise ValidationError("migrations must advance exactly one positive version")
        if not self.name.strip():
            raise ValidationError("migration name is required")


@dataclass(slots=True)
class MigrationStepReport:
    name: str
    from_version: int
    to_version: int
    collections_before: int
    collections_after: int
    records_before: int
    records_after: int


@dataclass(slots=True)
class MigrationReport:
    initial_version: int
    target_version: int
    final_version: int
    dry_run: bool
    steps: list[MigrationStepReport] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.initial_version != self.final_version


class MigrationRegistry:
    def __init__(self, migrations: Iterable[Migration] = ()) -> None:
        self._by_version: dict[int, Migration] = {}
        for migration in migrations:
            self.register(migration)

    def register(self, migration: Migration) -> None:
        if migration.from_version in self._by_version:
            existing = self._by_version[migration.from_version]
            raise ConflictError(
                f"migration from version {migration.from_version} already registered: "
                f"{existing.name}"
            )
        self._by_version[migration.from_version] = migration

    @property
    def latest_version(self) -> int:
        if not self._by_version:
            return 1
        return max(migration.to_version for migration in self._by_version.values())

    def plan(self, current_version: int, target_version: int | None = None) -> list[Migration]:
        target = self.latest_version if target_version is None else target_version
        if current_version < 1 or target < 1:
            raise ValidationError("schema versions must be positive")
        if target < current_version:
            raise ValidationError("downgrade migrations are not supported")
        plan: list[Migration] = []
        cursor = current_version
        while cursor < target:
            migration = self._by_version.get(cursor)
            if migration is None:
                raise StorageError(f"no migration registered from schema version {cursor}")
            plan.append(migration)
            cursor = migration.to_version
        return plan

    def migrate(
        self,
        store: JsonDocumentStore,
        *,
        target_version: int | None = None,
        dry_run: bool = False,
    ) -> MigrationReport:
        snapshot = store.snapshot()
        initial_version = int(snapshot.get("schema_version", 1))
        target = self.latest_version if target_version is None else target_version
        report = MigrationReport(initial_version, target, initial_version, dry_run)
        candidate = deepcopy(snapshot)
        for migration in self.plan(initial_version, target):
            before_collections, before_records = _snapshot_size(candidate)
            migrated = migration.apply(deepcopy(candidate))
            _validate_snapshot(migrated)
            migrated["schema_version"] = migration.to_version
            after_collections, after_records = _snapshot_size(migrated)
            report.steps.append(
                MigrationStepReport(
                    migration.name,
                    migration.from_version,
                    migration.to_version,
                    before_collections,
                    after_collections,
                    before_records,
                    after_records,
                )
            )
            candidate = migrated
            report.final_version = migration.to_version
        if report.changed and not dry_run:
            store.replace_snapshot(candidate, expected_revision=int(snapshot.get("revision", 0)))
        return report


def rename_collection(source: str, destination: str) -> MigrationFunction:
    def apply(snapshot: Snapshot) -> Snapshot:
        collections = snapshot["collections"]
        if source not in collections:
            return snapshot
        if destination in collections:
            raise ConflictError(f"migration destination already exists: {destination}")
        collections[destination] = collections.pop(source)
        return snapshot

    return apply


def add_field(collection: str, path: str, default: Any) -> MigrationFunction:
    segments = path.split(".")
    if not segments or any(not segment for segment in segments):
        raise ValidationError("migration field path is invalid")

    def apply(snapshot: Snapshot) -> Snapshot:
        for row in snapshot["collections"].get(collection, []):
            cursor = row
            for segment in segments[:-1]:
                nested = cursor.setdefault(segment, {})
                if not isinstance(nested, dict):
                    raise StorageError(f"cannot traverse non-object migration path: {path}")
                cursor = nested
            cursor.setdefault(segments[-1], deepcopy(default))
        return snapshot

    return apply


def transform_collection(
    collection: str,
    transform: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> MigrationFunction:
    def apply(snapshot: Snapshot) -> Snapshot:
        rows = snapshot["collections"].get(collection, [])
        transformed: list[dict[str, Any]] = []
        for row in rows:
            replacement = transform(deepcopy(row))
            if replacement is None:
                continue
            if not isinstance(replacement, dict):
                raise ValidationError("migration transform must return an object or None")
            transformed.append(replacement)
        snapshot["collections"][collection] = transformed
        return snapshot

    return apply


def compose(*functions: MigrationFunction) -> MigrationFunction:
    def apply(snapshot: Snapshot) -> Snapshot:
        candidate = snapshot
        for function in functions:
            candidate = function(candidate)
            _validate_snapshot(candidate)
        return candidate

    return apply


def _validate_snapshot(snapshot: object) -> None:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("collections"), dict):
        raise ValidationError("migration must return a snapshot with collections")
    for collection, rows in snapshot["collections"].items():
        if not isinstance(collection, str) or not isinstance(rows, list):
            raise ValidationError("migration produced an invalid collection")
        if any(not isinstance(row, dict) for row in rows):
            raise ValidationError(f"migration produced an invalid row in {collection}")


def _snapshot_size(snapshot: Snapshot) -> tuple[int, int]:
    collections = snapshot["collections"]
    return len(collections), sum(len(rows) for rows in collections.values())
