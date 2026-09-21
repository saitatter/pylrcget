from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from core.lrclib_client import LrcLibAPI

from .contracts import (
    DownloadMode,
    LyricsProviderCapabilities,
    LyricsProviderResult,
    LyricsSearchContext,
    LyricsSearchResult,
    TrackLookupContext,
)
from .diagnostics import (
    build_lookup_diagnostics,
    log_lookup_diagnostics,
    lyrics_result_type,
)

logger = logging.getLogger(__name__)


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

        started_at = time.perf_counter()
        try:
            match = find_best_lyrics_match(
                self._api,
                notify=self._notify,
                provider_label=self.display_name,
                track_id=int(track.track_id or 0),
                track_label=label,
                title=title,
                artist=artist,
                album=album,
                duration_s=duration_s,
                before_request=before_request,
                on_rate_limit=self._on_rate_limit,
            )
        except Exception as error:
            diagnostics = build_lookup_diagnostics(
                provider=self.provider_id,
                track_id=track.track_id,
                lookup_method="lrclib",
                isrc_lookup="not_supported",
                candidate_count=0,
                selected_remote_id=None,
                score=None,
                reason=type(error).__name__,
                result_type="error",
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
            )
            log_lookup_diagnostics(logger, diagnostics)
            raise
        if match is None:
            diagnostics = build_lookup_diagnostics(
                provider=self.provider_id,
                track_id=track.track_id,
                lookup_method="lrclib",
                isrc_lookup="not_supported",
                candidate_count=0,
                selected_remote_id=None,
                score=None,
                reason="no_match",
                result_type="no_match",
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
            )
            log_lookup_diagnostics(logger, diagnostics)
            return None

        source = match.result
        provider_track_id = getattr(source, "id", None)
        diagnostics = build_lookup_diagnostics(
            provider=self.provider_id,
            track_id=track.track_id,
            lookup_method=match.query_label,
            isrc_lookup="not_supported",
            candidate_count=1,
            selected_remote_id=str(provider_track_id) if provider_track_id is not None else None,
            score=match.score,
            reason="match",
            result_type=lyrics_result_type(
                getattr(source, "plain_lyrics", None),
                getattr(source, "synced_lyrics", None),
            ),
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
        )
        log_lookup_diagnostics(logger, diagnostics)
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
            diagnostics={"query_label": match.query_label, **diagnostics},
        )

    def search(
        self,
        context: LyricsSearchContext,
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[LyricsSearchResult]:
        if cancel_event is not None and cancel_event.is_set():
            return []
        results = self._api.search_lyrics(
            query=context.query or None,
            track_name=context.title or None,
            artist_name=context.artist or None,
            album_name=context.album or None,
        )
        return [
            LyricsSearchResult(
                provider=self.provider_id,
                provider_track_id=str(result.id) if result.id is not None else None,
                title=result.track_name,
                artist=result.artist_name,
                album=result.album_name,
                duration_seconds=float(result.duration) if result.duration is not None else None,
                instrumental=bool(result.instrumental),
                plain_lyrics=result.plain_lyrics,
                synced_lyrics=result.synced_lyrics,
            )
            for result in results
        ]
