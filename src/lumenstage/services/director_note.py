"""Application service for director notes."""

from __future__ import annotations

from lumenstage.models.director_note import DirectorNote
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class DirectorNoteService(EntityService[DirectorNote]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, DirectorNote, "director_notes", "director note")

    def resolve(self, note_id: str, resolver_id: str, *, resolution: str = "") -> DirectorNote:
        note = self.get(note_id)
        note.resolve(resolver_id, resolution=resolution)
        return self.repo.save(note)

    def unresolved(self, *, priority: str | None = None) -> list[DirectorNote]:
        notes = [note for note in self.list(status="active") if not note.resolved]
        if priority:
            notes = [note for note in notes if note.priority == priority]
        return notes

    def for_target(self, target_type: str, target_id: str) -> list[DirectorNote]:
        return [
            note
            for note in self.list()
            if note.target_type == target_type and note.target_id == target_id
        ]
