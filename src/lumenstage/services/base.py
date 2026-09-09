"""Shared service operations for JSON-backed catalog entities."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from lumenstage.errors import ValidationError
from lumenstage.models.base import CatalogEntity
from lumenstage.storage.repository import Repository
from lumenstage.storage.store import JsonDocumentStore
from lumenstage.utils.slugify import slugify

EntityT = TypeVar("EntityT", bound=CatalogEntity)


class EntityService(Generic[EntityT]):
    """Reusable CRUD and query behavior with domain-safe updates."""

    def __init__(
        self,
        store: JsonDocumentStore,
        entity_type: type[EntityT],
        collection: str,
        label: str,
    ) -> None:
        self.entity_type = entity_type
        self.repo: Repository[EntityT] = Repository(
            store,
            collection,
            entity_type.to_dict,
            entity_type.from_dict,
            label,
        )

    def create(self, name: str, slug: str, **kwargs: Any) -> EntityT:
        normalized = slugify(slug)
        if any(existing.slug == normalized for existing in self.repo.list()):
            raise ValidationError(f"duplicate slug: {slug}")
        item = self.entity_type.create(name, slug, **kwargs)
        return self.repo.save(item)

    def get(self, item_id: str) -> EntityT:
        return self.repo.get(item_id)

    def get_by_slug(self, slug: str) -> EntityT:
        normalized = slugify(slug)
        for item in self.repo.list():
            if item.slug == normalized:
                return item
        from lumenstage.errors import NotFoundError

        raise NotFoundError(f"{self.repo.label} not found: {normalized}")

    def list(
        self,
        *,
        status: str | None = None,
        query: str | None = None,
        tags: list[str] | None = None,
    ) -> list[EntityT]:
        rows = self.repo.list()
        if status:
            rows = [row for row in rows if row.status == status]
        if query:
            rows = [row for row in rows if row.matches(query)]
        if tags:
            required = {tag.strip().lower() for tag in tags}
            rows = [row for row in rows if required.issubset(row.tags)]
        return sorted(rows, key=lambda row: (row.name.lower(), row.id))

    def update(self, item_id: str, **changes: Any) -> EntityT:
        item = self.repo.get(item_id)
        if changes.get("name") is not None:
            item.rename(str(changes["name"]))
        if changes.get("status") is not None:
            item.set_status(str(changes["status"]))
        if changes.get("tags") is not None:
            tags = changes["tags"]
            if not isinstance(tags, list):
                raise ValidationError("tags must be a list")
            normalized = item.normalize_tags(str(tag) for tag in tags)
            if normalized != item.tags:
                item.tags = normalized
                item.touch()
        if changes.get("metadata") is not None:
            metadata = changes["metadata"]
            if not isinstance(metadata, dict):
                raise ValidationError("metadata must be an object")
            item.merge_metadata(metadata)
        if changes.get("note") is not None:
            item.add_note(str(changes["note"]))
        return self.repo.save(item)

    def archive(self, item_id: str, *, note: str | None = None) -> EntityT:
        item = self.repo.get(item_id)
        item.set_status("archived")
        if note:
            item.add_note(note)
        return self.repo.save(item)

    def delete(self, item_id: str) -> None:
        self.repo.delete(item_id)

    def count(self, *, status: str | None = None) -> int:
        return len(self.list(status=status))
