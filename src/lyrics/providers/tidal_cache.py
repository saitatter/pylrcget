from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable

from db.query_modules.remote_mapping_queries import (
    get_remote_track_mapping,
    upsert_remote_track_mapping,
)

from .contracts import TrackLookupContext
from .matching import (
    MatchQuality,
    TrackMatchScore,
    local_metadata_fingerprint,
)
from .tidal import TidalCatalogueClient, TidalTrack, TidalTrackResolution


class CachedTidalCatalogueResolver:
    """Add a DB-backed local-to-TIDAL mapping cache to the catalogue resolver."""

    provider_id = "tidal"

    def __init__(
        self,
        client: TidalCatalogueClient,
        db: sqlite3.Connection,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client = client
        self.db = db
        self._clock = clock

    def resolve_track(self, local: TrackLookupContext) -> TidalTrackResolution | None:
        fingerprint = local_metadata_fingerprint(local)
        if local.track_id is not None:
            mapping = get_remote_track_mapping(self.db, local.track_id, self.provider_id)
            if mapping is not None and mapping["local_metadata_fingerprint"] == fingerprint:
                return self._resolution_from_mapping(mapping)

        resolution = self.client.resolve_track(local)
        if resolution is None or local.track_id is None:
            return resolution

        track = resolution.track
        upsert_remote_track_mapping(
            self.db,
            track_id=local.track_id,
            provider=self.provider_id,
            provider_track_id=track.provider_track_id,
            match_method=resolution.score.method,
            match_score=resolution.score.score,
            remote_isrc=track.isrc,
            remote_title=track.title,
            remote_artist=" & ".join(track.artists) or None,
            remote_album=track.album,
            remote_duration=track.duration_seconds,
            verified_at=self._clock(),
            local_metadata_fingerprint=fingerprint,
        )
        return resolution

    @staticmethod
    def _resolution_from_mapping(mapping: sqlite3.Row) -> TidalTrackResolution:
        track = TidalTrack(
            provider_track_id=str(mapping["provider_track_id"]),
            title=mapping["remote_title"],
            artists=tuple(
                part.strip()
                for part in str(mapping["remote_artist"] or "").split(" & ")
                if part.strip()
            ),
            album=mapping["remote_album"],
            album_artist=None,
            duration_seconds=(
                float(mapping["remote_duration"])
                if mapping["remote_duration"] is not None
                else None
            ),
            track_number=None,
            isrc=mapping["remote_isrc"],
        )
        method = str(mapping["match_method"])
        quality = MatchQuality.EXACT_ID if method == "exact isrc" else _quality_from_score(mapping["match_score"])
        score = TrackMatchScore(
            score=float(mapping["match_score"]),
            quality=quality,
            method=method,
            diagnostics={"cache_hit": True},
        )
        return TidalTrackResolution(track=track, score=score)


def _quality_from_score(score: float) -> MatchQuality:
    numeric_score = float(score)
    if numeric_score >= 80:
        return MatchQuality.HIGH
    if numeric_score >= 60:
        return MatchQuality.MEDIUM
    if numeric_score >= 35:
        return MatchQuality.LOW
    return MatchQuality.REJECT
