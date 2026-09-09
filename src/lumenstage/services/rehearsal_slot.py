"""Application service for rehearsal bookings."""

from __future__ import annotations

from lumenstage.models.rehearsal_slot import RehearsalSlot
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class RehearsalSlotService(EntityService[RehearsalSlot]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, RehearsalSlot, "rehearsal_slots", "rehearsal slot")

    def conflicts_for(self, candidate: RehearsalSlot) -> list[RehearsalSlot]:
        conflicts: list[RehearsalSlot] = []
        for existing in self.list(status="active"):
            if existing.id == candidate.id or not existing.overlaps(candidate):
                continue
            if existing.room_id == candidate.room_id or existing.shared_participants(candidate):
                conflicts.append(existing)
        return conflicts

    def by_room(self, room_id: str) -> list[RehearsalSlot]:
        return [item for item in self.list() if item.room_id == room_id]

    def for_participant(self, participant_id: str) -> list[RehearsalSlot]:
        return [item for item in self.list() if participant_id in item.participant_ids]
