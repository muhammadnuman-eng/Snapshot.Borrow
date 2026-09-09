from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from lumenstage.api.app import LumenStageApp, Request, Response
from lumenstage.api.router import Router
from lumenstage.config.settings import Settings
from lumenstage.errors import ConflictError, ValidationError


@pytest.fixture()
def app(tmp_path: Path) -> LumenStageApp:
    return LumenStageApp(Settings(data_dir=tmp_path, max_page_size=2))


def send(
    app: LumenStageApp,
    method: str,
    target: str,
    payload: dict[str, object] | list[object] | None = None,
    *,
    content_type: str = "application/json",
):
    body = json.dumps(payload).encode() if payload is not None else b""
    return app.handle(Request(method, target, body, headers={"content-type": content_type}))


def test_request_parses_query_and_requires_object_json() -> None:
    request = Request("get", "/api/productions?q=hamlet&tag=classic&tag=drama")
    assert request.method == "GET"
    assert request.path == "/api/productions"
    assert request.query_one("q") == "hamlet"
    assert request.query["tag"] == ["classic", "drama"]
    with pytest.raises(ValidationError, match="root"):
        Request("POST", "/", b"[]").json()


def test_router_prefers_static_routes_and_extracts_parameters() -> None:
    def handler(*args, **kwargs):
        return 200, {}

    router = Router()
    router.add("GET", "/api/{resource}", handler, name="dynamic")
    router.add("GET", "/api/resources", handler, name="static")
    assert router.resolve("GET", "/api/resources").route.name == "static"  # type: ignore[union-attr]
    match = router.resolve("GET", "/api/production%20notes")
    assert match is not None
    assert match.params == {"resource": "production notes"}
    with pytest.raises(ConflictError, match="already registered"):
        router.add("GET", "/api/resources", handler)


def test_resource_catalog_lists_all_supported_types(app: LumenStageApp) -> None:
    response = send(app, "GET", "/api/resources")
    assert response.status == 200
    names = {item["name"] for item in response.payload["resources"]}
    assert {"productions", "showbooks", "sound-cues", "cast-members"}.issubset(names)


def test_catalog_create_get_update_and_delete(app: LumenStageApp) -> None:
    created = send(
        app,
        "POST",
        "/api/productions",
        {"name": "Hamlet", "slug": "hamlet", "tags": ["Classic"]},
    )
    assert created.status == 201
    item_id = created.payload["item"]["id"]
    fetched = send(app, "GET", f"/api/productions/{item_id}")
    assert fetched.payload["item"]["name"] == "Hamlet"
    updated = send(
        app,
        "PATCH",
        f"/api/productions/{item_id}",
        {"name": "Hamlet 2026", "note": "renamed after announcement"},
    )
    assert updated.payload["item"]["version"] == 3
    deleted = send(app, "DELETE", f"/api/productions/{item_id}")
    assert deleted.payload["deleted"] == item_id
    assert send(app, "GET", f"/api/productions/{item_id}").status == 404


def test_catalog_filters_and_caps_page_size(app: LumenStageApp) -> None:
    for index in range(3):
        send(
            app,
            "POST",
            "/api/showbooks",
            {
                "name": f"Book {index}",
                "slug": f"book-{index}",
                "tags": ["published" if index < 2 else "draft"],
            },
        )
    first = send(app, "GET", "/api/showbooks?tag=published&page_size=99")
    assert len(first.payload["items"]) == 2
    assert first.payload["pagination"]["page_size"] == 2
    assert first.payload["pagination"]["total"] == 2


def test_catalog_maps_validation_conflict_and_missing_errors(app: LumenStageApp) -> None:
    invalid = send(app, "POST", "/api/productions", {"name": "", "slug": ""})
    assert invalid.status == 400
    assert invalid.payload["type"] == "validation_error"
    send(app, "POST", "/api/productions", {"name": "One", "slug": "same"})
    duplicate = send(app, "POST", "/api/productions", {"name": "Two", "slug": "same"})
    assert duplicate.status == 400
    assert send(app, "GET", "/api/unknown").status == 404


def test_invalid_content_type_json_and_update_fields_return_400(app: LumenStageApp) -> None:
    wrong_type = send(
        app,
        "POST",
        "/api/productions",
        {"name": "One"},
        content_type="text/plain",
    )
    assert wrong_type.status == 400
    malformed = app.handle(Request("POST", "/api/productions", b"{"))
    assert malformed.status == 400
    created = send(app, "POST", "/api/productions", {"name": "One", "slug": "one"})
    item_id = created.payload["item"]["id"]
    unsupported = send(app, "PATCH", f"/api/productions/{item_id}", {"slug": "two"})
    assert unsupported.status == 400


def test_method_not_allowed_and_head_response(app: LumenStageApp) -> None:
    method = send(app, "PUT", "/api/productions")
    assert method.status == 405
    assert "GET" in method.payload["allowed"]
    response = send(app, "HEAD", "/health")
    status, headers, body = response.to_wsgi()
    assert status == "200 OK"
    assert ("Content-Length", "0") in headers
    assert list(body()) == [b""]


def test_wsgi_adapter_passes_query_body_and_status(app: LumenStageApp) -> None:
    payload = json.dumps({"name": "Macbeth", "slug": "macbeth"}).encode()
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/api/productions",
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(payload)),
        "CONTENT_TYPE": "application/json",
        "wsgi.input": io.BytesIO(payload),
    }
    captured: list[object] = []
    body = app(environ, lambda status, headers: captured.extend([status, headers]))
    assert captured[0] == "201 Created"
    assert json.loads(body[0])["item"]["name"] == "Macbeth"


def test_response_uses_real_http_reason_phrase() -> None:
    status, headers, body = Response(404, {"error": "missing"}).to_wsgi()
    assert status == "404 Not Found"
    assert ("Content-Type", "application/json; charset=utf-8") in headers
    assert json.loads(next(iter(body()))) == {"error": "missing"}
