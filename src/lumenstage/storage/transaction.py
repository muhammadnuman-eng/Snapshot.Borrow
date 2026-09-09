"""Multi-collection transactions for the JSON document store."""

from __future__ import annotations

from copy import deepcopy
from types import TracebackType
from typing import Any, Self

from lumenstage.errors import ConflictError, StorageError, ValidationError


class StoreTransaction:
    """Hold the store lock and commit multiple collection changes atomically."""

    def __init__(self, store: Any, *, expected_revision: int | None = None) -> None:
        self.store = store
        self.expected_revision = expected_revision
        self._data: dict[str, Any] | None = None
        self._start_revision: int | None = None
        self._committed = False
        self._entered = False

    def __enter__(self) -> Self:
        if self._entered:
            raise StorageError("transaction cannot be entered twice")
        self.store._lock.acquire()
        self._entered = True
        try:
            self._data = self.store._read()
            self._start_revision = int(self._data.get("revision", 0))
            if (
                self.expected_revision is not None
                and self._start_revision != self.expected_revision
            ):
                raise ConflictError(
                    f"store revision changed: expected {self.expected_revision}, "
                    f"found {self._start_revision}"
                )
            self._data = deepcopy(self._data)
            return self
        except Exception:
            self.store._lock.release()
            self._entered = False
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            if exc_type is None and not self._committed:
                self.commit()
        finally:
            if self._entered:
                self.store._lock.release()
                self._entered = False
        return False

    @property
    def start_revision(self) -> int:
        self._require_active()
        assert self._start_revision is not None
        return self._start_revision

    def list_collections(self) -> list[str]:
        data = self._require_active()
        return sorted(data["collections"])

    def read_collection(self, name: str) -> list[dict[str, Any]]:
        data = self._require_active()
        self.store._validate_collection_name(name)
        rows = data["collections"].get(name, [])
        self.store._validate_rows(rows)
        return deepcopy(rows)

    def write_collection(self, name: str, rows: list[dict[str, Any]]) -> None:
        data = self._require_active()
        self.store._validate_collection_name(name)
        self.store._validate_rows(rows)
        data["collections"][name] = deepcopy(rows)

    def append(self, collection: str, row: dict[str, Any]) -> None:
        rows = self.read_collection(collection)
        if not isinstance(row, dict):
            raise ValidationError("transaction row must be an object")
        rows.append(deepcopy(row))
        self.write_collection(collection, rows)

    def upsert(self, collection: str, row: dict[str, Any], *, key: str = "id") -> bool:
        if not isinstance(row, dict):
            raise ValidationError("transaction row must be an object")
        value = row.get(key)
        if value is None:
            raise ValidationError(f"transaction row requires {key}")
        rows = self.read_collection(collection)
        for index, existing in enumerate(rows):
            if existing.get(key) == value:
                rows[index] = deepcopy(row)
                self.write_collection(collection, rows)
                return False
        rows.append(deepcopy(row))
        self.write_collection(collection, rows)
        return True

    def delete(self, collection: str, value: object, *, key: str = "id") -> bool:
        rows = self.read_collection(collection)
        kept = [row for row in rows if row.get(key) != value]
        changed = len(kept) != len(rows)
        if changed:
            self.write_collection(collection, kept)
        return changed

    def rename_collection(self, source: str, destination: str) -> None:
        data = self._require_active()
        self.store._validate_collection_name(source)
        self.store._validate_collection_name(destination)
        if source not in data["collections"]:
            raise StorageError(f"collection not found: {source}")
        if destination in data["collections"]:
            raise ConflictError(f"collection already exists: {destination}")
        data["collections"][destination] = data["collections"].pop(source)

    def set_schema_version(self, version: int) -> None:
        data = self._require_active()
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValidationError("schema version must be a positive integer")
        data["schema_version"] = version

    def rollback(self) -> None:
        self._require_active()
        self._data = None
        self._committed = True

    def commit(self) -> int:
        data = self._require_active()
        if self._committed:
            raise StorageError("transaction already completed")
        assert self._start_revision is not None
        for rows in data["collections"].values():
            self.store._validate_rows(rows)
        data["revision"] = self._start_revision + 1
        self.store._write(data)
        self._committed = True
        return int(data["revision"])

    def _require_active(self) -> dict[str, Any]:
        if not self._entered or self._data is None:
            raise StorageError("transaction is not active")
        return self._data
