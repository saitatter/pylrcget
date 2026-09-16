from __future__ import annotations

import threading
from collections.abc import Callable

from core.lrclib_client import LrcLibAPI

from .contracts import (
    DownloadMode,
    LyricsProviderCapabilities,
    LyricsProviderResult,
    TrackLookupContext,
)


class LrclibProvider:
    """Provider adapter that keeps the existing LRCLIB lookup implementation."""

    provider_id = "lrclib"
    display_name = "LRCLIB"

    def __init__(
        self,
        instance: str,
        *,
        api: LrcLibAPI | None = None,
        notify: Callable[[str], None] | None = None,
        before_request: Callable[[], bool] | None = None,
        on_rate_limit: Callable[[float], None] | None = None,
    ) -> None:
        self.instance = instance
        self._api = api or LrcLibAPI(instance)
        self._notify = notify or (lambda _message: None)
        self._before_request = before_request
        self._on_rate_limit = on_rate_limit

    def capabilities(self) -> LyricsProviderCapabilities:
        return LyricsProviderCapabilities(
            plain=True,
            synced=True,
            search=True,
            isrc_lookup=False,
            authentication_required=False,
        )

    def lookup(
        self,
        track: TrackLookupContext,
        *,
        requested_mode: DownloadMode,
        cancel_event: threading.Event | None = None,
    ) -> LyricsProviderResult | None:
        del requested_mode
        # Import lazily because the legacy matcher is still hosted by the UI
        # service during this compatibility phase.
        from ui.services.lyrics_download_service import find_best_lyrics_match

        artist = next(iter(track.artists), "")
        title = (track.title or "").strip()
        artist = (artist or "").strip()
        album = (track.album or "").strip()
        label = f"{artist} - {title}".strip(" -") or track.file_path
        duration_s = round(track.duration_seconds) if track.duration_seconds else None

        def before_request() -> bool:
            if cancel_event is not None and cancel_event.is_set():
                return False
            return self._before_request is None or self._before_request()

        match = find_best_lyrics_match(
            self._api,
            notify=self._notify,
            track_id=int(track.track_id or 0),
            track_label=label,
            title=title,
            artist=artist,
            album=album,
            duration_s=duration_s,
            before_request=before_request,
            on_rate_limit=self._on_rate_limit,
        )
        if match is None:
            return None

        source = match.result
        provider_track_id = getattr(source, "id", None)
        return LyricsProviderResult(
            provider=self.provider_id,
            provider_track_id=str(provider_track_id) if provider_track_id is not None else None,
            plain_lyrics=getattr(source, "plain_lyrics", None),
            synced_lyrics=getattr(source, "synced_lyrics", None),
            instrumental=bool(getattr(source, "instrumental", False)),
            match_score=float(match.score),
            match_method=match.query_label,
            remote_title=getattr(source, "track_name", None),
            remote_artist=getattr(source, "artist_name", None),
            remote_album=getattr(source, "album_name", None),
            remote_duration_seconds=(
                float(source.duration) if getattr(source, "duration", None) is not None else None
            ),
            remote_isrc=getattr(source, "isrc", None),
            diagnostics={"query_label": match.query_label},
        )
