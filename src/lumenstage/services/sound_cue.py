"""Application service for production sound cues."""

from __future__ import annotations

from lumenstage.models.sound_cue import SoundCue
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class SoundCueService(EntityService[SoundCue]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, SoundCue, "sound_cues", "sound cue")

    def ordered(self) -> list[SoundCue]:
        return sorted(self.list(status="active"), key=lambda cue: (cue.cue_number, cue.name))

    def mark_ready(self, cue_id: str) -> SoundCue:
        cue = self.get(cue_id)
        cue.mark_ready()
        return self.repo.save(cue)

    def unresolved(self) -> list[SoundCue]:
        return [cue for cue in self.ordered() if not cue.ready]
