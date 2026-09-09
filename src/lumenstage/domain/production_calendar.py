"""Production calendar aggregation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from lumenstage.models.performance import Performance
from lumenstage.models.production import Production
from lumenstage.models.rehearsal_slot import RehearsalSlot


@dataclass(slots=True)
class CalendarEntry:
    day: str
    productions: list[str] = field(default_factory=list)
    performances: list[str] = field(default_factory=list)
    rehearsal_slots: list[str] = field(default_factory=list)


class ProductionCalendar:
    def __init__(
        self,
        productions: Iterable[Production] | None = None,
        performances: Iterable[Performance] | None = None,
        rehearsal_slots: Iterable[RehearsalSlot] | None = None,
    ) -> None:
        self.productions, self.performances, self.rehearsal_slots = (
            list(productions or []),
            list(performances or []),
            list(rehearsal_slots or []),
        )

    def entries(self) -> list[CalendarEntry]:
        days: dict[str, CalendarEntry] = {}
        for production in self.productions:
            days.setdefault(
                production.created_at.date().isoformat(),
                CalendarEntry(day=production.created_at.date().isoformat()),
            ).productions.append(production.id)
        for performance in self.performances:
            days.setdefault(
                performance.created_at.date().isoformat(),
                CalendarEntry(day=performance.created_at.date().isoformat()),
            ).performances.append(performance.id)
        for sched in self.rehearsal_slots:
            day = str(sched.metadata.get("publish_at") or sched.created_at.isoformat())[:10]
            days.setdefault(day, CalendarEntry(day=day)).rehearsal_slots.append(sched.id)
        return [days[k] for k in sorted(days.keys())]

    def count_by_day(self) -> dict[str, int]:
        return {
            e.day: len(e.productions) + len(e.performances) + len(e.rehearsal_slots)
            for e in self.entries()
        }
