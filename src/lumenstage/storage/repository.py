"""Generic repository over JSON collections."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, TypeVar

from lumenstage.errors import NotFoundError, ValidationError
from lumenstage.storage.store import JsonDocumentStore

T = TypeVar("T")


class Repository(Generic[T]):
    def __init__(
        self,
        store: JsonDocumentStore,
        collection: str,
        to_dict: Callable[[T], dict[str, Any]],
        from_dict: Callable[[dict[str, Any]], T],
        label: str,
    ) -> None:
        self.store = store
        self.collection = collection
        self.to_dict = to_dict
        self.from_dict = from_dict
        self.label = label

    def list(self) -> list[T]:
        return [self.from_dict(row) for row in self.store.read_collection(self.collection)]

    def get(self, item_id: str) -> T:
        for row in self.store.read_collection(self.collection):
            if row.get("id") == item_id:
                return self.from_dict(row)
        raise NotFoundError(f"{self.label} not found: {item_id}")

    def save(self, item: T) -> T:
        payload = self.to_dict(item)
        if not payload.get("id"):
            raise ValidationError("id is required")

        def save_row(rows: list[dict[str, Any]]) -> None:
            for index, row in enumerate(rows):
                if row.get("id") == payload["id"]:
                    rows[index] = payload
                    return
            rows.append(payload)

        self.store.mutate_collection(self.collection, save_row)
        return item

    def delete(self, item_id: str) -> None:
        def delete_row(rows: list[dict[str, Any]]) -> None:
            for index, row in enumerate(rows):
                if row.get("id") == item_id:
                    rows.pop(index)
                    return
            raise NotFoundError(f"{self.label} not found: {item_id}")

        self.store.mutate_collection(self.collection, delete_row)

    def count(self) -> int:
        return len(self.store.read_collection(self.collection))
