"""Small dependency-free router with typed path parameters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from lumenstage.errors import ConflictError, ValidationError

Handler = Callable[..., tuple[int, dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    template: str
    handler: Handler
    name: str

    def __post_init__(self) -> None:
        method = self.method.strip().upper()
        if not method.isalpha():
            raise ValidationError("route method must contain only letters")
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "template", normalize_path(self.template))
        if not self.name.strip():
            raise ValidationError("route name is required")
        parameters = self.parameter_names
        if len(parameters) != len(set(parameters)):
            raise ValidationError(f"duplicate route parameter in {self.template}")

    @property
    def segments(self) -> tuple[str, ...]:
        return split_path(self.template)

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return tuple(
            segment[1:-1]
            for segment in self.segments
            if segment.startswith("{") and segment.endswith("}")
        )

    @property
    def specificity(self) -> tuple[int, int]:
        static = sum(not segment.startswith("{") for segment in self.segments)
        return static, len(self.segments)

    def match(self, path: str) -> dict[str, str] | None:
        candidate = split_path(path)
        if len(candidate) != len(self.segments):
            return None
        parameters: dict[str, str] = {}
        for expected, actual in zip(self.segments, candidate, strict=True):
            if expected.startswith("{") and expected.endswith("}"):
                value = unquote(actual)
                if not value or value in {".", ".."}:
                    return None
                parameters[expected[1:-1]] = value
            elif expected != actual:
                return None
        return parameters


@dataclass(frozen=True, slots=True)
class RouteMatch:
    route: Route
    params: dict[str, str]


class Router:
    def __init__(self) -> None:
        self._routes: list[Route] = []

    @property
    def routes(self) -> tuple[Route, ...]:
        return tuple(self._routes)

    def add(self, method: str, template: str, handler: Handler, *, name: str = "") -> Route:
        route = Route(method, template, handler, name or handler.__name__)
        for existing in self._routes:
            if existing.method == route.method and existing.template == route.template:
                raise ConflictError(f"route already registered: {route.method} {route.template}")
        self._routes.append(route)
        self._routes.sort(key=lambda item: item.specificity, reverse=True)
        return route

    def resolve(self, method: str, path: str) -> RouteMatch | None:
        normalized_method = method.upper()
        for route in self._routes:
            if route.method != normalized_method:
                continue
            parameters = route.match(path)
            if parameters is not None:
                return RouteMatch(route, parameters)
        return None

    def allowed_methods(self, path: str) -> tuple[str, ...]:
        return tuple(
            sorted(route.method for route in self._routes if route.match(path) is not None)
        )


def normalize_path(path: str) -> str:
    if not isinstance(path, str) or not path:
        raise ValidationError("route path is required")
    if not path.startswith("/"):
        raise ValidationError("route path must start with /")
    normalized = "/" + "/".join(segment for segment in path.split("/") if segment)
    return normalized or "/"


def split_path(path: str) -> tuple[str, ...]:
    normalized = normalize_path(path)
    return tuple(segment for segment in normalized.split("/") if segment)
