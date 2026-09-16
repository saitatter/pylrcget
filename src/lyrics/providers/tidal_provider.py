from __future__ import annotations

import threading
import time
from typing import Protocol

from .contracts import (
    DownloadMode,
    LyricsProviderCapabilities,
    LyricsProviderResult,
    TrackLookupContext,
)
from .diagnostics import build_lookup_diagnostics, lyrics_result_type
from .tidal import TidalTrackResolution
from .tidal_transport import TidalLyricsTransport


class TidalCatalogueResolver(Protocol):
    def resolve_track(self, local: TrackLookupContext) -> TidalTrackResolution | None:
        ...


class TidalProvider:
    """Join official TIDAL catalogue resolution to a swappable lyrics transport."""

    provider_id = "tidal"
    display_name = "TIDAL"

    def __init__(
        self,
        catalogue_resolver: TidalCatalogueResolver,
        lyrics_transport: TidalLyricsTransport,
    ) -> None:
        self._catalogue_resolver = catalogue_resolver
        self._lyrics_transport = lyrics_transport

    def capabilities(self) -> LyricsProviderCapabilities:
        return LyricsProviderCapabilities(
            plain=True,
            synced=True,
            search=True,
            isrc_lookup=True,
            authentication_required=True,
        )

    def lookup(
        self,
        track: TrackLookupContext,
        *,
        requested_mode: DownloadMode,
        cancel_event: threading.Event | None = None,
    ) -> LyricsProviderResult | None:
        if cancel_event is not None and cancel_event.is_set():
            return None
        started_at = time.perf_counter()
        resolution = self._catalogue_resolver.resolve_track(track)
        if resolution is None:
            return None
        if cancel_event is not None and cancel_event.is_set():
            return None

        remote = resolution.track
        payload = self._lyrics_transport.get_lyrics(
            remote.provider_track_id,
            cancel_event=cancel_event,
            track=track,
            requested_mode=requested_mode,
        )
        if payload is None:
            return None

        diagnostics = build_lookup_diagnostics(
            provider=self.provider_id,
            track_id=track.track_id,
            lookup_method=resolution.score.method,
            isrc_lookup="hit" if track.isrc and remote.isrc else "not_requested",
            candidate_count=1,
            selected_remote_id=remote.provider_track_id,
            score=resolution.score.score,
            reason="lyrics_match",
            result_type=lyrics_result_type(payload.plain_lyrics, payload.synced_lyrics),
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
        )
        diagnostics.update(
            {
                "catalogue_diagnostics": dict(resolution.score.diagnostics),
                "transport_source": payload.source,
            }
        )
        return LyricsProviderResult(
            provider=self.provider_id,
            provider_track_id=remote.provider_track_id,
            plain_lyrics=payload.plain_lyrics,
            synced_lyrics=payload.synced_lyrics,
            instrumental=False,
            match_score=resolution.score.score,
            match_method=resolution.score.method,
            remote_title=remote.title,
            remote_artist=", ".join(remote.artists) if remote.artists else None,
            remote_album=remote.album,
            remote_duration_seconds=remote.duration_seconds,
            remote_isrc=remote.isrc,
            diagnostics=diagnostics,
        )
