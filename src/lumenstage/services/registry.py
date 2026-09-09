"""Discoverable registry for JSON-backed catalog services."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from lumenstage.errors import NotFoundError, ValidationError
from lumenstage.services.base import EntityService
from lumenstage.services.box_office import BoxOfficeService
from lumenstage.services.cast_member import CastMemberService
from lumenstage.services.department import DepartmentService
from lumenstage.services.department_tag import DepartmentTagService
from lumenstage.services.director_note import DirectorNoteService
from lumenstage.services.licensing import LicensingService
from lumenstage.services.performance import PerformanceService
from lumenstage.services.preview_hold import PreviewHoldService
from lumenstage.services.production import ProductionService
from lumenstage.services.program import ProgramService
from lumenstage.services.prop_asset import PropAssetService
from lumenstage.services.rehearsal_slot import RehearsalSlotService
from lumenstage.services.role_track import RoleTrackService
from lumenstage.services.showbook import ShowbookService
from lumenstage.services.sound_cue import SoundCueService
from lumenstage.services.staging_review import StagingReviewService
from lumenstage.storage.store import JsonDocumentStore


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    resource: str
    collection: str
    label: str
    service_type: type[EntityService[Any]]
    aliases: tuple[str, ...] = ()


DEFINITIONS = (
    ServiceDefinition("box-office", "box_office", "box office snapshot", BoxOfficeService),
    ServiceDefinition("cast-members", "cast_members", "cast member", CastMemberService),
    ServiceDefinition("departments", "departments", "department", DepartmentService),
    ServiceDefinition("department-tags", "department_tags", "department tag", DepartmentTagService),
    ServiceDefinition("director-notes", "director_notes", "director note", DirectorNoteService),
    ServiceDefinition("licenses", "licenses", "license", LicensingService, ("licensing",)),
    ServiceDefinition("performances", "performances", "performance", PerformanceService),
    ServiceDefinition("preview-holds", "preview_holds", "preview hold", PreviewHoldService),
    ServiceDefinition("productions", "productions", "production", ProductionService),
    ServiceDefinition("programs", "programs", "program", ProgramService),
    ServiceDefinition("prop-assets", "prop_assets", "prop asset", PropAssetService, ("props",)),
    ServiceDefinition("rehearsal-slots", "rehearsal_slots", "rehearsal slot", RehearsalSlotService),
    ServiceDefinition("role-tracks", "role_tracks", "role track", RoleTrackService),
    ServiceDefinition("showbooks", "showbooks", "showbook", ShowbookService),
    ServiceDefinition("sound-cues", "sound_cues", "sound cue", SoundCueService),
    ServiceDefinition("staging-reviews", "staging_reviews", "staging review", StagingReviewService),
)


class ServiceRegistry:
    """Resolve stable API resource names without exposing implementation imports."""

    def __init__(self, definitions: tuple[ServiceDefinition, ...] = DEFINITIONS) -> None:
        self._definitions = definitions
        self._by_name: dict[str, ServiceDefinition] = {}
        for definition in definitions:
            names = (definition.resource, definition.collection, *definition.aliases)
            for name in names:
                normalized = self.normalize(name)
                existing = self._by_name.get(normalized)
                if existing is not None and existing != definition:
                    raise ValidationError(f"duplicate service resource name: {name}")
                self._by_name[normalized] = definition

    def __iter__(self) -> Iterator[ServiceDefinition]:
        return iter(self._definitions)

    @property
    def resources(self) -> tuple[str, ...]:
        return tuple(definition.resource for definition in self._definitions)

    def definition(self, resource: str) -> ServiceDefinition:
        try:
            return self._by_name[self.normalize(resource)]
        except KeyError as exc:
            raise NotFoundError(f"resource not found: {resource}") from exc

    def service(self, resource: str, store: JsonDocumentStore) -> EntityService[Any]:
        return self.definition(resource).service_type(store)

    @staticmethod
    def normalize(resource: str) -> str:
        return resource.strip().lower().replace("_", "-")


registry = ServiceRegistry()
