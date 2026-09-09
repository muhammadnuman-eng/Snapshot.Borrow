from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from lumenstage.audit import (
    REDACTED,
    AuditAction,
    AuditActor,
    AuditEntry,
    AuditOutcome,
    AuditPolicy,
    AuditQuery,
    AuditTrail,
)
from lumenstage.errors import ConflictError, NotFoundError, ValidationError


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2027, 1, 4, 10, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self.value
        self.value += timedelta(seconds=1)
        return value


ACTOR = AuditActor("user-1", "Alex Manager", role="producer")


@pytest.fixture()
def trail() -> AuditTrail:
    return AuditTrail("prod-1", clock=Clock())


def entry(action: AuditAction, **overrides: object) -> AuditEntry:
    values: dict[str, object] = {
        "actor": ACTOR,
        "action": action,
        "resource_type": "production",
        "resource_id": "prod-1",
    }
    if action == AuditAction.CREATE:
        values["after"] = {"name": "Hamlet", "status": "draft"}
    elif action == AuditAction.UPDATE:
        values["before"] = {"name": "Hamlet", "status": "draft"}
        values["after"] = {"name": "Hamlet", "status": "active"}
    elif action == AuditAction.DELETE:
        values["before"] = {"name": "Hamlet", "status": "active"}
    values.update(overrides)
    return AuditEntry(**values)  # type: ignore[arg-type]


def test_actor_requires_identity() -> None:
    with pytest.raises(ValidationError, match="actor id"):
        AuditActor("", "Person")
    assert AuditActor.from_dict(ACTOR.to_dict()) == ACTOR


def test_policy_redacts_nested_secrets_and_limits_large_values() -> None:
    policy = AuditPolicy(max_string_length=16)
    result = policy.sanitize({"password": "hidden", "nested": {"api_key": "key"}, "note": "x" * 20})
    assert result["password"] == REDACTED
    assert result["nested"]["api_key"] == REDACTED
    assert result["note"] == "x" * 16 + "...[4 chars omitted]"


def test_record_builds_a_linked_hash_chain(trail: AuditTrail) -> None:
    first = trail.record(entry(AuditAction.CREATE))
    second = trail.record(entry(AuditAction.UPDATE))
    assert first.id == "AUD-00000001"
    assert second.sequence == 2
    assert second.previous_hash == first.digest
    assert second.digest == second.expected_digest()
    verification = trail.verify()
    assert verification.valid
    assert verification.checked == 2


def test_event_shape_rules_are_enforced(trail: AuditTrail) -> None:
    with pytest.raises(ValidationError, match="requires after"):
        trail.record(entry(AuditAction.CREATE, after=None))
    with pytest.raises(ValidationError, match="before and after"):
        trail.record(entry(AuditAction.UPDATE, before=None))
    with pytest.raises(ValidationError, match="observable change"):
        trail.record(entry(AuditAction.UPDATE, before={"x": 1}, after={"x": 1}))
    with pytest.raises(ValidationError, match="requires before"):
        trail.record(entry(AuditAction.DELETE, before=None))


def test_record_sanitizes_state_before_hashing() -> None:
    trail = AuditTrail("scope", policy=AuditPolicy(max_string_length=16), clock=Clock())
    event = trail.record(
        entry(
            AuditAction.CREATE,
            after={"name": "Hamlet", "token": "do-not-store", "blob": b"123"},
        )
    )
    assert event.after["token"] == REDACTED
    assert event.after["blob"] == "[BYTES:3]"
    assert trail.verify().valid


def test_chronological_order_is_required(trail: AuditTrail) -> None:
    later = datetime(2027, 1, 5, tzinfo=UTC)
    trail.record(entry(AuditAction.CREATE, occurred_at=later))
    with pytest.raises(ConflictError, match="chronological"):
        trail.record(entry(AuditAction.UPDATE, occurred_at=later - timedelta(days=1)))


def test_record_many_rolls_back_on_invalid_entry(trail: AuditTrail) -> None:
    with pytest.raises(ValidationError):
        trail.record_many(
            [
                entry(AuditAction.CREATE),
                entry(AuditAction.UPDATE, before={"same": True}, after={"same": True}),
            ]
        )
    assert trail.events == ()
    assert trail.verify().valid


def test_read_capture_is_policy_controlled() -> None:
    default = AuditTrail("scope", clock=Clock())
    assert default.record_read(ACTOR, "showbook", "book-1") is None
    enabled = AuditTrail("scope", policy=AuditPolicy(capture_reads=True), clock=Clock())
    event = enabled.record_read(ACTOR, "showbook", "book-1")
    assert event is not None
    assert event.action == AuditAction.READ


def test_query_filters_every_supported_dimension(trail: AuditTrail) -> None:
    start = datetime(2027, 1, 4, 9, tzinfo=UTC)
    trail.record(entry(AuditAction.CREATE, correlation_id="request-1"))
    trail.record(
        entry(
            AuditAction.UPDATE,
            actor=AuditActor("user-2", "Sam Director"),
            outcome=AuditOutcome.DENIED,
            reason="approval missing",
            correlation_id="request-2",
        )
    )
    result = trail.query(
        AuditQuery(
            actor_ids=frozenset({"user-2"}),
            actions=frozenset({AuditAction.UPDATE}),
            outcomes=frozenset({AuditOutcome.DENIED}),
            resource_types=frozenset({"production"}),
            resource_id="prod-1",
            correlation_id="request-2",
            starts_at=start,
            ends_at=start + timedelta(days=1),
            text="approval",
        )
    )
    assert len(result) == 1
    assert result[0].actor.id == "user-2"


def test_query_rejects_reversed_window() -> None:
    with pytest.raises(ValidationError, match="precede"):
        AuditQuery(
            starts_at=datetime(2027, 2, 1, tzinfo=UTC),
            ends_at=datetime(2027, 1, 1, tzinfo=UTC),
        )


def test_cursor_pagination_is_stable(trail: AuditTrail) -> None:
    trail.record(entry(AuditAction.CREATE))
    trail.record(entry(AuditAction.UPDATE))
    trail.record(entry(AuditAction.DELETE))
    first = trail.page(limit=2)
    assert [event.sequence for event in first.events] == [1, 2]
    assert first.next_sequence == 2
    assert first.has_more
    second = trail.page(after_sequence=first.next_sequence or 0, limit=2)
    assert [event.sequence for event in second.events] == [3]
    assert second.next_sequence is None
    with pytest.raises(ValidationError, match="between"):
        trail.page(limit=1001)


def test_changes_returns_nested_field_paths(trail: AuditTrail) -> None:
    event = trail.record(
        entry(
            AuditAction.UPDATE,
            before={"name": "Hamlet", "metadata": {"venue": "A", "year": 2026}},
            after={"name": "Hamlet", "metadata": {"venue": "B", "open": True}},
        )
    )
    changes = {change.path: change for change in trail.changes(event.id)}
    assert set(changes) == {"metadata.open", "metadata.venue", "metadata.year"}
    assert changes["metadata.venue"].before == "A"
    with pytest.raises(NotFoundError):
        trail.changes("missing")


def test_state_at_replays_successful_mutations_only(trail: AuditTrail) -> None:
    trail.record(entry(AuditAction.CREATE))
    trail.record(entry(AuditAction.UPDATE))
    trail.record(
        entry(
            AuditAction.UPDATE,
            before={"name": "Hamlet", "status": "active"},
            after={"name": "Hamlet", "status": "cancelled"},
            outcome=AuditOutcome.DENIED,
        )
    )
    assert trail.state_at("PRODUCTION", "prod-1", sequence=1)["status"] == "draft"
    assert trail.state_at("production", "prod-1")["status"] == "active"
    trail.record(entry(AuditAction.DELETE))
    assert trail.state_at("production", "prod-1") is None


def test_lineage_excludes_unrelated_resources(trail: AuditTrail) -> None:
    trail.record(entry(AuditAction.CREATE))
    trail.record(
        entry(
            AuditAction.CREATE,
            resource_type="showbook",
            resource_id="book-1",
            after={"name": "Book"},
        )
    )
    assert [event.id for event in trail.lineage("production", "prod-1")] == ["AUD-00000001"]


def test_verifier_detects_payload_chain_and_sequence_tampering(trail: AuditTrail) -> None:
    trail.record(entry(AuditAction.CREATE))
    trail.record(entry(AuditAction.UPDATE))
    trail._events[0] = replace(trail.events[0], reason="tampered")
    verification = trail.verify()
    assert not verification.valid
    assert "digest mismatch" in verification.issues[0]
    trail._events[1] = replace(trail.events[1], sequence=9)
    assert any("event sequence" in issue for issue in trail.verify().issues)


def test_summary_groups_actions_outcomes_resources_actors_and_days(trail: AuditTrail) -> None:
    trail.record(entry(AuditAction.CREATE))
    trail.record(entry(AuditAction.UPDATE, outcome=AuditOutcome.DENIED))
    summary = trail.summary()
    assert summary.total == 2
    assert summary.by_action == {"create": 1, "update": 1}
    assert summary.by_outcome == {"success": 1, "denied": 1}
    assert summary.by_resource == {"production": 2}
    assert summary.by_actor == {"user-1": 2}
    assert summary.by_day == {"2027-01-04": 2}


def test_export_import_round_trip_preserves_and_verifies_chain(trail: AuditTrail) -> None:
    trail.record(entry(AuditAction.CREATE))
    trail.record(entry(AuditAction.UPDATE))
    exported = trail.export_ndjson()
    restored = AuditTrail.import_ndjson(exported)
    assert restored.scope == "prod-1"
    assert restored.events == trail.events
    assert restored.verify().valid


def test_import_rejects_tampered_event_and_count(trail: AuditTrail) -> None:
    trail.record(entry(AuditAction.CREATE))
    lines = trail.export_ndjson().splitlines()
    event = json.loads(lines[1])
    event["reason"] = "changed"
    with pytest.raises(ConflictError, match="integrity"):
        AuditTrail.import_ndjson("\n".join([lines[0], json.dumps(event)]))
    header = json.loads(lines[0])
    header["count"] = 2
    with pytest.raises(ValidationError, match="count mismatch"):
        AuditTrail.import_ndjson("\n".join([json.dumps(header), lines[1]]))


def test_import_rejects_empty_or_unknown_format() -> None:
    with pytest.raises(ValidationError, match="empty"):
        AuditTrail.import_ndjson("")
    with pytest.raises(ValidationError, match="unsupported"):
        AuditTrail.import_ndjson('{"format":"other","scope":"x","count":0}')


def test_clock_must_be_timezone_aware() -> None:
    trail = AuditTrail("scope", clock=lambda: datetime(2027, 1, 1))
    with pytest.raises(ValidationError, match="timezone-aware"):
        trail.record(entry(AuditAction.CREATE))
