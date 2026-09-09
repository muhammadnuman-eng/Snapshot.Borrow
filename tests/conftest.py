from __future__ import annotations

from pathlib import Path

import pytest

from lumenstage.storage.store import JsonDocumentStore


@pytest.fixture()
def store(tmp_path: Path) -> JsonDocumentStore:
    return JsonDocumentStore(tmp_path / "store.json")
