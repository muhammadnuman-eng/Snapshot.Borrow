from pathlib import Path

from lumenstage.models.department import Department
from lumenstage.storage.repository import Repository
from lumenstage.storage.store import JsonDocumentStore


def test_repository_roundtrip(tmp_path: Path) -> None:
    store = JsonDocumentStore(tmp_path / "store.json")
    repo = Repository(store, "departments", Department.to_dict, Department.from_dict, "department")
    saved = repo.save(Department.create("Metro", "metro"))
    assert repo.get(saved.id).name == "Metro"
