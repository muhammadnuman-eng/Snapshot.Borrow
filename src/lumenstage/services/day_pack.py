"""Persisted production day pack operations."""

from __future__ import annotations

from lumenstage.domain.day_pack import DayPackAssembler, parse_calendar_date
from lumenstage.errors import ConflictError, NotFoundError, ValidationError
from lumenstage.models.day_pack import DayPack
from lumenstage.services.performance import PerformanceService
from lumenstage.services.production import ProductionService
from lumenstage.services.prop_asset import PropAssetService
from lumenstage.services.rehearsal_slot import RehearsalSlotService
from lumenstage.services.role_track import RoleTrackService
from lumenstage.services.sound_cue import SoundCueService
from lumenstage.storage.store import JsonDocumentStore

COLLECTION = "day_packs"


class DayPackService:
    def __init__(self, store: JsonDocumentStore) -> None:
        self.store = store
        self._assembler = DayPackAssembler()

    def build(
        self,
        production_id: str,
        date: str,
        *,
        publish: bool = False,
    ) -> tuple[DayPack, bool]:
        """Build or rebuild a day pack. Returns the pack and whether it was newly created."""
        normalized_date = parse_calendar_date(date)
        production = ProductionService(self.store).get(production_id)
        snapshot = self._assembler.assemble(
            production,
            date=normalized_date,
            performances=PerformanceService(self.store).list(),
            rehearsal_slots=RehearsalSlotService(self.store).list(),
            sound_cues=SoundCueService(self.store).list(),
            role_tracks=RoleTrackService(self.store).list(),
            prop_assets=PropAssetService(self.store).list(),
        )
        existing = self._find_by_production_date(production_id, normalized_date)
        if existing is None:
            pack = DayPack.create(
                production_id,
                normalized_date,
                str(snapshot["timezone"]),
                snapshot=snapshot,
            )
            if publish:
                pack.publish()
            self._save(pack)
            return pack, True

        if existing.status == "published":
            raise ConflictError("published day packs cannot be rebuilt")
        existing.apply_snapshot(snapshot)
        if publish:
            existing.publish()
        self._save(existing)
        return existing, False

    def get(self, pack_id: str) -> DayPack:
        for row in self.store.read_collection(COLLECTION):
            if row.get("id") == pack_id:
                return DayPack.from_dict(row)
        raise NotFoundError(f"day pack not found: {pack_id}")

    def list(
        self,
        production_id: str,
        *,
        date: str | None = None,
        status: str | None = None,
    ) -> list[DayPack]:
        rows = [DayPack.from_dict(row) for row in self.store.read_collection(COLLECTION)]
        filtered = [row for row in rows if row.production_id == production_id]
        if date is not None:
            normalized = parse_calendar_date(date)
            filtered = [row for row in filtered if row.date == normalized]
        if status is not None:
            normalized_status = status.strip().lower()
            if normalized_status not in DayPack.ALLOWED_STATUSES:
                raise ValidationError(f"invalid status: {status}")
            filtered = [row for row in filtered if row.status == normalized_status]
        return sorted(filtered, key=lambda row: (row.date, row.version, row.id))

    def publish(self, pack_id: str) -> DayPack:
        pack = self.get(pack_id)
        if pack.status == "published":
            raise ConflictError("day pack is already published")
        pack.publish()
        self._save(pack)
        return pack

    def _find_by_production_date(self, production_id: str, date: str) -> DayPack | None:
        for row in self.store.read_collection(COLLECTION):
            if row.get("production_id") == production_id and row.get("date") == date:
                return DayPack.from_dict(row)
        return None

    def _save(self, pack: DayPack) -> None:
        payload = pack.to_dict()

        def write_row(rows: list[dict]) -> None:
            for index, row in enumerate(rows):
                if row.get("id") == payload["id"]:
                    rows[index] = payload
                    return
            rows.append(payload)

        self.store.mutate_collection(COLLECTION, write_row)
