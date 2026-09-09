"""Generic HTTP operations for all catalog resources."""

from __future__ import annotations

from typing import Any

from lumenstage.config.settings import Settings
from lumenstage.errors import ValidationError
from lumenstage.services.registry import registry
from lumenstage.storage.store import JsonDocumentStore
from lumenstage.utils.pagination import paginate


def _one(query: dict[str, list[str]], name: str, default: str = "") -> str:
    values = query.get(name, [])
    return values[-1] if values else default


def _positive_int(value: str, name: str, default: int) -> int:
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValidationError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise ValidationError(f"{name} must be positive")
    return parsed


def list_resources(
    _: dict[str, Any],
    settings: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str],
    query: dict[str, list[str]],
):
    definition = registry.definition(params["resource"])
    service = registry.service(definition.resource, store)
    tags = [tag.strip() for tag in query.get("tag", []) if tag.strip()]
    records = service.list(
        status=_one(query, "status") or None,
        query=_one(query, "q") or None,
        tags=tags or None,
    )
    page_number = _positive_int(_one(query, "page"), "page", 1)
    requested_size = _positive_int(_one(query, "page_size"), "page_size", 50)
    page = paginate(
        records, page=page_number, page_size=min(requested_size, settings.max_page_size)
    )
    return 200, {
        "resource": definition.resource,
        "items": [item.to_dict() for item in page.items],
        "pagination": {
            "page": page.page,
            "page_size": page.page_size,
            "pages": page.pages,
            "total": page.total,
            "has_next": page.has_next,
            "has_prev": page.has_prev,
        },
        "store_revision": store.revision,
    }


def create_resource(
    body: dict[str, Any],
    _: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str],
    query: dict[str, list[str]],
):
    del query
    definition = registry.definition(params["resource"])
    tags = body.get("tags") or []
    metadata = body.get("metadata") or {}
    if not isinstance(tags, list):
        raise ValidationError("tags must be a list")
    if not isinstance(metadata, dict):
        raise ValidationError("metadata must be an object")
    item = registry.service(definition.resource, store).create(
        str(body.get("name", "")),
        str(body.get("slug", "")),
        tags=tags,
        metadata=metadata,
    )
    return 201, {"resource": definition.resource, "item": item.to_dict()}


def get_resource(
    _: dict[str, Any],
    __: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str],
    query: dict[str, list[str]],
):
    del query
    definition = registry.definition(params["resource"])
    item = registry.service(definition.resource, store).get(params["item_id"])
    return 200, {"resource": definition.resource, "item": item.to_dict()}


def update_resource(
    body: dict[str, Any],
    _: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str],
    query: dict[str, list[str]],
):
    del query
    definition = registry.definition(params["resource"])
    allowed = {"name", "status", "tags", "metadata", "note"}
    unknown = set(body) - allowed
    if unknown:
        raise ValidationError(f"unsupported update fields: {sorted(unknown)}")
    if not body:
        raise ValidationError("update body must not be empty")
    item = registry.service(definition.resource, store).update(params["item_id"], **body)
    return 200, {"resource": definition.resource, "item": item.to_dict()}


def delete_resource(
    _: dict[str, Any],
    __: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str],
    query: dict[str, list[str]],
):
    del query
    definition = registry.definition(params["resource"])
    service = registry.service(definition.resource, store)
    service.get(params["item_id"])
    service.delete(params["item_id"])
    return 200, {"resource": definition.resource, "deleted": params["item_id"]}


def list_resource_types(
    _: dict[str, Any],
    __: Settings,
    store: JsonDocumentStore,
    *,
    params: dict[str, str],
    query: dict[str, list[str]],
):
    del params, query
    return 200, {
        "resources": [
            {
                "name": definition.resource,
                "collection": definition.collection,
                "label": definition.label,
                "count": len(store.read_collection(definition.collection)),
            }
            for definition in registry
        ]
    }
