"""Coordinate publishing rehearsal_slots across performances."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from lumenstage.models.rehearsal_slot import RehearsalSlot
from lumenstage.utils.timeutil import parse_iso, utc_now


class RehearsalSlotCoordinator:
    def rehearsal_slotd_at(self, item: RehearsalSlot) -> datetime:
        raw = item.metadata.get("publish_at")
        return parse_iso(str(raw)) if raw else item.created_at

    def upcoming(
        self, rehearsal_slots: Iterable[RehearsalSlot], *, within_hours: int = 48
    ) -> list[RehearsalSlot]:
        now, horizon = utc_now(), utc_now() + timedelta(hours=within_hours)
        result = [s for s in rehearsal_slots if now <= self.rehearsal_slotd_at(s) <= horizon]
        return sorted(result, key=self.rehearsal_slotd_at)

    def overlaps(self, a: RehearsalSlot, b: RehearsalSlot, *, window_minutes: int = 30) -> bool:
        return (
            abs((self.rehearsal_slotd_at(a) - self.rehearsal_slotd_at(b)).total_seconds())
            <= window_minutes * 60
        )

    def group_by_day(
        self, rehearsal_slots: Iterable[RehearsalSlot]
    ) -> dict[str, list[RehearsalSlot]]:
        buckets: dict[str, list[RehearsalSlot]] = {}
        for item in rehearsal_slots:
            buckets.setdefault(self.rehearsal_slotd_at(item).date().isoformat(), []).append(item)
        return dict(sorted(buckets.items()))
