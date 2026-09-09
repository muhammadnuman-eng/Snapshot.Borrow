"""Application service for performance programs."""

from __future__ import annotations

from lumenstage.models.program import Program
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class ProgramService(EntityService[Program]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, Program, "programs", "program")

    def publish(self, program_id: str) -> Program:
        program = self.get(program_id)
        program.publish()
        return self.repo.save(program)

    def drafts(self) -> list[Program]:
        return [program for program in self.list(status="active") if not program.published]

    def published(self) -> list[Program]:
        return [program for program in self.list(status="active") if program.published]
