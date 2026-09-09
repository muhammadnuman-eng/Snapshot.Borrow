from lumenstage.utils.pagination import paginate
from lumenstage.utils.slugify import slugify


def test_slugify() -> None:
    assert slugify("Hello World!") == "hello-world"


def test_paginate() -> None:
    page = paginate(list(range(10)), page=2, page_size=3)
    assert page.items == [3, 4, 5]
