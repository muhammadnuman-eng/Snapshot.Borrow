"""PreviewHold enforcement helpers."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from lumenstage.errors import WorkflowError
from lumenstage.models.preview_hold import PreviewHold
from lumenstage.utils.timeutil import parse_iso, utc_now


class PreviewHoldChecker:
    def __init__(self, grace_minutes: int = 15) -> None:
        self.grace_minutes = grace_minutes

    def lift_time(self, preview_hold: PreviewHold) -> datetime:
        raw = preview_hold.metadata.get("lift_at")
        return parse_iso(str(raw)) if raw else preview_hold.created_at

    def is_lifted(self, preview_hold: PreviewHold, *, now: datetime | None = None) -> bool:
        return (now or utc_now()) >= self.lift_time(preview_hold)

    def assert_publishable(
        self, preview_holds: Iterable[PreviewHold], *, now: datetime | None = None
    ) -> None:
        active = [e for e in preview_holds if not self.is_lifted(e, now=now)]
        if active:
            raise WorkflowError("preview_hold still active:" + ",".join(e.name for e in active))

    def with_grace(self, preview_hold: PreviewHold) -> datetime:
        return self.lift_time(preview_hold) + timedelta(minutes=self.grace_minutes)
