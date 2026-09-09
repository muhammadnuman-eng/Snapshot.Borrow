"""Plan licensing windows and partner feeds."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from lumenstage.models.licensing import Licensing


@dataclass(slots=True)
class LicensingSlot:
    partner_slug: str
    production_id: str
    priority: int = 0
    regions: list[str] = field(default_factory=list)


class LicensingPlanner:
    def __init__(self, partners: Iterable[Licensing]) -> None:
        self.partners = list(partners)

    def eligible_partners(self, tags: Iterable[str]) -> list[Licensing]:
        tag_set = {t.lower() for t in tags}
        result = []
        for partner in self.partners:
            required = {str(t).lower() for t in partner.metadata.get("required_tags", [])}
            if not required or required.issubset(tag_set):
                result.append(partner)
        return sorted(result, key=lambda p: p.name.lower())

    def build_slots(self, production_id: str, tags: Iterable[str]) -> list[LicensingSlot]:
        return [
            LicensingSlot(
                partner.slug, production_id, idx, list(partner.metadata.get("regions", []))
            )
            for idx, partner in enumerate(self.eligible_partners(tags))
        ]
