"""Application service for role and understudy tracks."""

from __future__ import annotations

from lumenstage.models.role_track import RoleTrack
from lumenstage.services.base import EntityService
from lumenstage.storage.store import JsonDocumentStore


class RoleTrackService(EntityService[RoleTrack]):
    def __init__(self, store: JsonDocumentStore) -> None:
        super().__init__(store, RoleTrack, "role_tracks", "role track")

    def assign_primary(self, role_track_id: str, cast_member_id: str) -> RoleTrack:
        track = self.get(role_track_id)
        track.assign_primary(cast_member_id)
        return self.repo.save(track)

    def add_understudy(self, role_track_id: str, cast_member_id: str) -> RoleTrack:
        track = self.get(role_track_id)
        track.add_understudy(cast_member_id)
        return self.repo.save(track)

    def uncovered(self) -> list[RoleTrack]:
        return [track for track in self.list(status="active") if not track.is_covered()]

    def for_cast_member(self, cast_member_id: str) -> list[RoleTrack]:
        return [
            track
            for track in self.list()
            if cast_member_id == track.primary_cast_id or cast_member_id in track.understudy_ids
        ]
