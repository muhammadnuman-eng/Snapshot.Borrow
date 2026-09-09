"""JSON document persistence."""

from __future__ import annotations

import json
import shutil
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, TypeVar

from lumenstage.errors import ConflictError, StorageError, ValidationError

ResultT = TypeVar("ResultT")


class JsonDocumentStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "revision": 0, "collections": {}}
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = (
                json.loads(raw)
                if raw.strip()
                else {"schema_version": 1, "revision": 0, "collections": {}}
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(f"cannot read store: {exc}") from exc
        if not isinstance(data, dict):
            raise StorageError("store root must be an object")
        if "collections" not in data or not isinstance(data["collections"], dict):
            raise StorageError("store.collections must be an object")
        if isinstance(data.get("revision", 0), bool) or not isinstance(
            data.get("revision", 0), int
        ):
            raise StorageError("store.revision must be an integer")
        if data.get("revision", 0) < 0:
            raise StorageError("store.revision must be non-negative")
        data.setdefault("schema_version", 1)
        data.setdefault("revision", 0)
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        try:
            serialized = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)
            tmp.write_text(serialized, encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            raise StorageError(f"cannot write store: {exc}") from exc

    def list_collections(self) -> list[str]:
        with self._lock:
            return sorted(self._read()["collections"].keys())

    def read_collection(self, name: str) -> list[dict[str, Any]]:
        self._validate_collection_name(name)
        with self._lock:
            rows = self._read()["collections"].get(name, [])
            if not isinstance(rows, list):
                raise StorageError(f"collection {name!r} must be a list")
            if any(not isinstance(row, dict) for row in rows):
                raise StorageError(f"collection {name!r} contains a non-object row")
            return deepcopy(rows)

    def write_collection(self, name: str, rows: list[dict[str, Any]]) -> None:
        self._validate_collection_name(name)
        self._validate_rows(rows)
        with self._lock:
            data = self._read()
            data["collections"][name] = deepcopy(rows)
            data["revision"] = int(data.get("revision", 0)) + 1
            self._write(data)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._read())

    @property
    def revision(self) -> int:
        with self._lock:
            return int(self._read().get("revision", 0))

    @property
    def schema_version(self) -> int:
        with self._lock:
            return int(self._read().get("schema_version", 1))

    def mutate_collection(
        self,
        name: str,
        mutator: Any,
        *,
        expected_revision: int | None = None,
    ) -> ResultT:
        """Apply a collection mutation under one lock and one atomic write."""
        self._validate_collection_name(name)
        with self._lock:
            data = self._read()
            revision = int(data.get("revision", 0))
            if expected_revision is not None and revision != expected_revision:
                raise ConflictError(
                    f"store revision changed: expected {expected_revision}, found {revision}"
                )
            existing = data["collections"].get(name, [])
            if not isinstance(existing, list):
                raise StorageError(f"collection {name!r} must be a list")
            rows = deepcopy(existing)
            result = mutator(rows)
            self._validate_rows(rows)
            data["collections"][name] = rows
            data["revision"] = revision + 1
            self._write(data)
            return result

    def replace_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        expected_revision: int | None = None,
    ) -> int:
        """Atomically replace the whole store after validating its shape."""
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("collections"), dict):
            raise ValidationError("snapshot must contain a collections object")
        with self._lock:
            current = self._read()
            current_revision = int(current.get("revision", 0))
            if expected_revision is not None and current_revision != expected_revision:
                raise ConflictError(
                    f"store revision changed: expected {expected_revision}, "
                    f"found {current_revision}"
                )
            candidate = deepcopy(snapshot)
            for rows in candidate["collections"].values():
                self._validate_rows(rows)
            candidate["revision"] = current_revision + 1
            candidate.setdefault("schema_version", current.get("schema_version", 1))
            self._write(candidate)
            return int(candidate["revision"])

    def backup_to(self, destination: Path) -> Path:
        """Create a verified JSON backup without exposing the live file."""
        with self._lock:
            snapshot = self._read()
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_text(
                json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                decoded = json.loads(temporary.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise StorageError(f"cannot verify backup: {exc}") from exc
            if decoded != snapshot:
                raise StorageError("backup verification mismatch")
            temporary.replace(destination)
            return destination

    def restore_from(self, source: Path) -> int:
        """Restore a backup while preserving the live revision sequence."""
        try:
            snapshot = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(f"cannot read backup: {exc}") from exc
        return self.replace_snapshot(snapshot)

    def copy_to(self, destination: Path) -> Path:
        """Copy the current store file after flushing a valid snapshot."""
        with self._lock:
            if not self.path.exists():
                self._write(self._read())
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.path, destination)
            return destination

    def transaction(self, *, expected_revision: int | None = None) -> Any:
        from lumenstage.storage.transaction import StoreTransaction

        return StoreTransaction(self, expected_revision=expected_revision)

    @staticmethod
    def _validate_collection_name(name: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("collection name is required")
        if name != name.strip() or any(char in name for char in "/\\"):
            raise ValidationError("collection name must be a simple identifier")

    @staticmethod
    def _validate_rows(rows: object) -> None:
        if not isinstance(rows, list):
            raise ValidationError("collection rows must be a list")
        ids: set[str] = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValidationError(f"row {index} must be an object")
            item_id = row.get("id")
            if item_id is not None:
                normalized = str(item_id)
                if normalized in ids:
                    raise ValidationError(f"duplicate id in collection: {normalized}")
                ids.add(normalized)
