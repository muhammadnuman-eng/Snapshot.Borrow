"""Pagination utilities."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    items: Sequence[T]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1


def paginate(items: Sequence[T], *, page: int = 1, page_size: int = 50) -> Page[T]:
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 50
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return Page(items=items[start:end], total=total, page=page, page_size=page_size)
