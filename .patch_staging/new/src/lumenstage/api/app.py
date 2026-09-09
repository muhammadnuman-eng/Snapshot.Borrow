"""Dependency-free WSGI API application for LumenStage."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlsplit

from lumenstage.api.router import Router, normalize_path
from lumenstage.api.routes import catalog, day_packs, health, productions, showbooks
from lumenstage.config.settings import Settings
from lumenstage.errors import (
    ConflictError,
    LumenStageError,
    NotFoundError,
    ValidationError,
)
from lumenstage.storage.store import JsonDocumentStore


class Request:
    def __init__(
        self,
        method: str,
        target: str,
        body: bytes = b"",
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        split = urlsplit(target)
        self.method = method.strip().upper()
        self.target = target
        self.path = normalize_path(split.path or "/")
        self.body = body
        self.query = parse_qs(split.query, keep_blank_values=True)
        self.headers = {key.lower(): value for key, value in (headers or {}).items()}

    def json(self) -> dict[str, Any]:
        if not self.body:
            return {}
        content_type = self.headers.get("content-type", "application/json").split(";", 1)[0]
        if content_type != "application/json":
            raise ValidationError("request content type must be application/json")
        try:
            payload = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("request body must contain valid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise ValidationError("request JSON root must be an object")
        return payload

    def query_one(self, name: str, default: str | None = None) -> str | None:
        values = self.query.get(name)
        return values[-1] if values else default


class Response:
    def __init__(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        headers: Iterable[tuple[str, str]] = (),
        suppress_body: bool = False,
    ) -> None:
        self.status = status
        self.payload = payload
        self.headers = list(headers)
        self.suppress_body = suppress_body

    def to_wsgi(self):
        body = json.dumps(self.payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        reason = HTTPStatus(self.status).phrase
        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(0 if self.suppress_body else len(body))),
            *self.headers,
        ]
        content = b"" if self.suppress_body else body
        return f"{self.status} {reason}", headers, lambda: [content]


def build_router() -> Router:
    router = Router()
    router.add("GET", "/health", health.get_health)
    router.add("GET", "/showbooks", showbooks.list_showbooks, name="legacy_showbook_list")
    router.add("POST", "/showbooks", showbooks.create_showbook, name="legacy_showbook_create")
    router.add("GET", "/productions", productions.list_productions, name="legacy_production_list")
    router.add(
        "POST", "/productions", productions.create_production, name="legacy_production_create"
    )
    router.add(
        "POST",
        "/api/productions/{production_id}/day-packs",
        day_packs.build_day_pack,
        name="day_pack_build",
    )
    router.add(
        "GET",
        "/api/productions/{production_id}/day-packs",
        day_packs.list_day_packs,
        name="day_pack_list",
    )
    router.add("GET", "/api/day-packs/{pack_id}", day_packs.get_day_pack, name="day_pack_get")
    router.add(
        "POST",
        "/api/day-packs/{pack_id}/publish",
        day_packs.publish_day_pack,
        name="day_pack_publish",
    )
    router.add("GET", "/api/resources", catalog.list_resource_types)
    router.add("GET", "/api/{resource}", catalog.list_resources)
    router.add("POST", "/api/{resource}", catalog.create_resource)
    router.add("GET", "/api/{resource}/{item_id}", catalog.get_resource)
    router.add("PATCH", "/api/{resource}/{item_id}", catalog.update_resource)
    router.add("DELETE", "/api/{resource}/{item_id}", catalog.delete_resource)
    return router


def create_app(settings: Settings | None = None) -> LumenStageApp:
    return LumenStageApp(settings or Settings())


class LumenStageApp:
    def __init__(self, settings: Settings, *, router: Router | None = None) -> None:
        self.settings = settings
        self.settings.ensure_dirs()
        self.store = JsonDocumentStore(settings.data_dir / "store.json")
        self.router = router or build_router()

    def handle(self, request: Request) -> Response:
        requested_method = "GET" if request.method == "HEAD" else request.method
        match = self.router.resolve(requested_method, request.path)
        if match is None:
            allowed = self.router.allowed_methods(request.path)
            if allowed:
                return Response(
                    405,
                    {"error": "method not allowed", "allowed": list(allowed)},
                    headers=(("Allow", ", ".join(allowed)),),
                )
            return Response(404, {"error": "not found", "path": request.path})
        try:
            body = request.json() if request.method in {"POST", "PUT", "PATCH"} else {}
            status, payload = match.route.handler(
                body,
                self.settings,
                self.store,
                params=match.params,
                query=request.query,
            )
            return Response(status, payload, suppress_body=request.method == "HEAD")
        except ValidationError as exc:
            return Response(400, {"error": str(exc), "type": "validation_error"})
        except NotFoundError as exc:
            return Response(404, {"error": str(exc), "type": "not_found"})
        except ConflictError as exc:
            return Response(409, {"error": str(exc), "type": "conflict"})
        except LumenStageError as exc:
            return Response(422, {"error": str(exc), "type": "domain_error"})

    def __call__(self, environ: dict[str, Any], start_response: Callable) -> list[bytes]:
        try:
            size = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            size = 0
        body = environ["wsgi.input"].read(size) if size else b""
        query_string = environ.get("QUERY_STRING", "")
        target = environ.get("PATH_INFO", "/")
        if query_string:
            target = f"{target}?{query_string}"
        headers = {
            key[5:].replace("_", "-"): str(value)
            for key, value in environ.items()
            if key.startswith("HTTP_")
        }
        if environ.get("CONTENT_TYPE"):
            headers["content-type"] = str(environ["CONTENT_TYPE"])
        response = self.handle(
            Request(environ.get("REQUEST_METHOD", "GET"), target, body, headers=headers)
        )
        status_line, response_headers, body_iter = response.to_wsgi()
        start_response(status_line, response_headers)
        return list(body_iter())
