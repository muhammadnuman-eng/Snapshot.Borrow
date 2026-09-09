from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from lumenstage.errors import ConflictError, StorageError, ValidationError
from lumenstage.storage.migrations import (
    Migration,
    MigrationRegistry,
    add_field,
    compose,
    rename_collection,
    transform_collection,
)
from lumenstage.storage.query import (
    AllOf,
    Between,
    Contains,
    Equals,
    Exists,
    InSet,
    Negate,
    Query,
    aggregate,
    update_matching,
)
from lumenstage.storage.store import JsonDocumentStore


@pytest.fixture()
def store(tmp_path: Path) -> JsonDocumentStore:
    return JsonDocumentStore(tmp_path / "lumenstage.json")


def test_revision_changes_after_atomic_writes(store: JsonDocumentStore) -> None:
    assert store.revision == 0
    store.write_collection("productions", [{"id": "p1", "name": "Hamlet"}])
    assert store.revision == 1
    store.mutate_collection("productions", lambda rows: rows.append({"id": "p2"}))
    assert store.revision == 2


def test_mutation_rejects_stale_revision(store: JsonDocumentStore) -> None:
    store.write_collection("productions", [])
    with pytest.raises(ConflictError, match="expected 0, found 1"):
        store.mutate_collection("productions", lambda rows: rows.clear(), expected_revision=0)


def test_store_rejects_duplicate_ids(store: JsonDocumentStore) -> None:
    with pytest.raises(ValidationError, match="duplicate id"):
        store.write_collection("productions", [{"id": "same"}, {"id": "same"}])


def test_store_rejects_path_like_collection_names(store: JsonDocumentStore) -> None:
    with pytest.raises(ValidationError, match="simple identifier"):
        store.write_collection("../outside", [])


def test_transaction_commits_multiple_collections(store: JsonDocumentStore) -> None:
    with store.transaction(expected_revision=0) as transaction:
        transaction.append("productions", {"id": "p1", "name": "Hamlet"})
        transaction.append("performances", {"id": "f1", "production_id": "p1"})
        transaction.set_schema_version(2)
    assert store.schema_version == 2
    assert store.revision == 1
    assert store.read_collection("productions")[0]["name"] == "Hamlet"
    assert store.read_collection("performances")[0]["production_id"] == "p1"


def test_transaction_rolls_back_on_exception(store: JsonDocumentStore) -> None:
    store.write_collection("productions", [{"id": "p1"}])
    with pytest.raises(RuntimeError), store.transaction() as transaction:
        transaction.append("productions", {"id": "p2"})
        raise RuntimeError("cancel")
    assert store.read_collection("productions") == [{"id": "p1"}]
    assert store.revision == 1


def test_transaction_supports_upsert_delete_and_rename(store: JsonDocumentStore) -> None:
    with store.transaction() as transaction:
        assert transaction.upsert("shows", {"id": "s1", "name": "First"})
        assert not transaction.upsert("shows", {"id": "s1", "name": "Updated"})
        transaction.append("shows", {"id": "s2"})
        assert transaction.delete("shows", "s2")
        assert not transaction.delete("shows", "missing")
        transaction.rename_collection("shows", "productions")
    assert store.read_collection("productions") == [{"id": "s1", "name": "Updated"}]


def test_completed_transaction_cannot_commit_again(store: JsonDocumentStore) -> None:
    with store.transaction() as transaction:
        transaction.write_collection("shows", [])
        transaction.commit()
        with pytest.raises(StorageError, match="already completed"):
            transaction.commit()


def test_backup_and_restore_roundtrip(store: JsonDocumentStore, tmp_path: Path) -> None:
    store.write_collection("productions", [{"id": "p1", "name": "Original"}])
    backup = store.backup_to(tmp_path / "backups" / "snapshot.json")
    store.write_collection("productions", [{"id": "p2", "name": "Replacement"}])
    restored_revision = store.restore_from(backup)
    assert restored_revision == 3
    assert store.read_collection("productions")[0]["name"] == "Original"


def test_restore_rejects_invalid_backup(store: JsonDocumentStore, tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not json", encoding="utf-8")
    with pytest.raises(StorageError, match="cannot read backup"):
        store.restore_from(invalid)


def sample_rows() -> list[dict[str, object]]:
    return [
        {
            "id": "p1",
            "name": "Hamlet",
            "status": "active",
            "tags": ["classic", "tragedy"],
            "metadata": {"capacity": 300, "venue": "Main"},
        },
        {
            "id": "p2",
            "name": "The Tempest",
            "status": "active",
            "tags": ["classic"],
            "metadata": {"capacity": 120, "venue": "Studio"},
        },
        {
            "id": "p3",
            "name": "New Work",
            "status": "archived",
            "tags": ["new"],
            "metadata": {"capacity": 80, "venue": "Studio"},
        },
    ]


def test_query_filters_sorts_projects_and_paginates() -> None:
    query = (
        Query()
        .where(
            AllOf(
                (
                    Equals("status", "active"),
                    Contains("tags", "classic"),
                    Between("metadata.capacity", minimum=100),
                    Exists("metadata.venue", truthy=True),
                )
            )
        )
        .order_by("metadata.capacity", descending=True)
        .select("id", "metadata.capacity")
        .offset(0)
        .limit(1)
    )
    result = query.execute(sample_rows())
    assert result.total == 2
    assert result.has_more
    assert result.rows == [{"id": "p1", "metadata.capacity": 300}]


def test_query_combinators_handle_case_and_negation() -> None:
    query = Query().where(
        AllOf(
            (
                Contains("name", "TEMPEST"),
                InSet("status", frozenset({"active", "preview"})),
                Negate(Equals("metadata.venue", "Main")),
            )
        )
    )
    assert [row["id"] for row in query.execute(sample_rows()).rows] == ["p2"]


def test_query_validates_pagination_values() -> None:
    with pytest.raises(ValidationError):
        Query().offset(-1)
    with pytest.raises(ValidationError):
        Query().limit(0)


def test_aggregate_groups_numeric_values() -> None:
    result = aggregate(sample_rows(), group_by="metadata.venue", value_path="metadata.capacity")
    assert result[0].key == "Main"
    assert result[0].total == Decimal("300")
    assert result[1].key == "Studio"
    assert result[1].count == 2
    assert result[1].minimum == Decimal("80")
    assert result[1].maximum == Decimal("120")


def test_update_matching_can_change_and_remove_rows() -> None:
    updated, changed = update_matching(
        sample_rows(),
        Equals("status", "archived"),
        lambda row: None if row["id"] == "p3" else row,
    )
    assert changed == 1
    assert [row["id"] for row in updated] == ["p1", "p2"]


def test_migration_registry_plans_dry_runs_and_commits(store: JsonDocumentStore) -> None:
    store.write_collection("shows", [{"id": "p1", "metadata": {}}])
    registry = MigrationRegistry(
        [
            Migration(1, 2, "rename shows", rename_collection("shows", "productions")),
            Migration(
                2,
                3,
                "add planning stage",
                compose(add_field("productions", "metadata.stage", "planning")),
            ),
        ]
    )
    dry_run = registry.migrate(store, dry_run=True)
    assert dry_run.changed
    assert dry_run.final_version == 3
    assert store.schema_version == 1
    report = registry.migrate(store)
    assert [step.name for step in report.steps] == ["rename shows", "add planning stage"]
    assert store.schema_version == 3
    assert store.read_collection("productions")[0]["metadata"]["stage"] == "planning"


def test_transform_migration_can_filter_and_rewrite_rows(store: JsonDocumentStore) -> None:
    store.write_collection("notes", [{"id": "n1", "keep": True}, {"id": "n2", "keep": False}])

    def keep_and_mark(row: dict[str, object]) -> dict[str, object] | None:
        if not row["keep"]:
            return None
        return {**row, "migrated": True}

    registry = MigrationRegistry(
        [Migration(1, 2, "filter notes", transform_collection("notes", keep_and_mark))]
    )
    registry.migrate(store)
    assert store.read_collection("notes") == [{"id": "n1", "keep": True, "migrated": True}]


def test_store_file_is_stable_json(store: JsonDocumentStore) -> None:
    store.write_collection("productions", [{"id": "p1", "name": "ليلة الافتتاح"}])
    decoded = json.loads(store.path.read_text(encoding="utf-8"))
    assert decoded["collections"]["productions"][0]["name"] == "ليلة الافتتاح"
