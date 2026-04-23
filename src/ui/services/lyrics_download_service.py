from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import sqlite3
import time
from typing import Callable

from lrclib import LrcLibAPI
from lrclib.exceptions import APIError, NotFoundError, RateLimitError, ServerError
from requests import exceptions as requests_exceptions

from core.embed_lyrics import embed_lyrics_for_track
from core.lyrics_sidecar import export_lyrics_sidecars
from db.database import get_config, get_track_by_id, update_track_plain_lyrics, update_track_synced_lyrics
from db.models import Config, Track
from ui.services.download_modes import normalize_download_mode

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]
_RETRYABLE_API_ERRORS = (RateLimitError, ServerError, requests_exceptions.Timeout, requests_exceptions.ConnectionError)
_MAX_LRCLIB_RETRIES = 3
_INITIAL_BACKOFF_S = 0.5
_LRC_TIMESTAMP_RE = re.compile(r"\[(?:\d+:)?\d+:\d+(?:\.\d+)?\]")


@dataclass(frozen=True)
class TrackOutputSyncResult:
    sidecar_paths: tuple[str, ...] = ()
    sidecar_error: Exception | None = None
    embedded: bool = False
    embed_error: Exception | None = None


def _strip_empty(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    return s or None


def _strip_timestamps(lrc: str) -> str:
    lines: list[str] = []
    for line in lrc.splitlines():
        cleaned = _LRC_TIMESTAMP_RE.sub("", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines).strip()


def _should_retry_lrclib_error(exc: Exception) -> bool:
    if isinstance(exc, NotFoundError):
        return False
    if isinstance(exc, _RETRYABLE_API_ERRORS):
        return True
    if isinstance(exc, APIError):
        status_code = int(getattr(exc, "status_code", 0) or 0)
        return status_code == 429 or status_code >= 500
    return False


def fetch_lyrics_with_retry(
    api: LrcLibAPI,
    *,
    notify: ProgressCallback,
    title: str,
    artist: str,
    album: str | None,
    duration_s: int | None,
):
    backoff_s = _INITIAL_BACKOFF_S
    last_error: Exception | None = None
    for attempt in range(1, _MAX_LRCLIB_RETRIES + 1):
        try:
            notify(f"Querying LRCLIB... (attempt {attempt}/{_MAX_LRCLIB_RETRIES})")
            return api.get_lyrics(
                track_name=title,
                artist_name=artist,
                album_name=album or None,
                duration=duration_s or None,
            )
        except Exception as exc:
            last_error = exc
            if not _should_retry_lrclib_error(exc) or attempt >= _MAX_LRCLIB_RETRIES:
                raise
            logger.warning("Retrying LRCLIB request for %s - %s after %s: %s", artist, title, type(exc).__name__, exc)
            notify(f"LRCLIB request failed ({type(exc).__name__}); retrying in {backoff_s:.1f}s...")
            time.sleep(backoff_s)
            backoff_s *= 2
    if last_error is not None:
        raise last_error


def sync_track_outputs(
    db: sqlite3.Connection,
    track: Track,
    notify: ProgressCallback,
    *,
    config: Config | None = None,
) -> None:
    config = config or get_config(db)
    sync_track_outputs_with_result(track, config, notify=notify)


def sync_track_outputs_with_result(
    track: Track,
    config: Config,
    *,
    notify: ProgressCallback | None = None,
) -> TrackOutputSyncResult:
    notify_cb = notify or (lambda _msg: None)

    sidecar_paths: tuple[str, ...] = ()
    sidecar_error: Exception | None = None
    embedded = False
    embed_error: Exception | None = None

    if config.save_lyrics_sidecars:
        try:
            notify_cb("Writing lyrics sidecar files...")
            sidecar_paths = tuple(export_lyrics_sidecars(track, config))
        except (OSError, PermissionError, ValueError) as exc:
            sidecar_error = exc
            logger.warning("Failed to export lyrics sidecars for track %s: %s", track.id, exc)

    if config.try_embed_lyrics:
        try:
            notify_cb("Embedding lyrics into the audio file...")
            embed_lyrics_for_track(track)
            embedded = True
        except (OSError, ValueError) as exc:
            embed_error = exc
            logger.warning("Failed to embed lyrics for track %s: %s", track.id, exc)

    return TrackOutputSyncResult(
        sidecar_paths=sidecar_paths,
        sidecar_error=sidecar_error,
        embedded=embedded,
        embed_error=embed_error,
    )


def download_track_lyrics(
    db_path: str,
    track_id: int,
    lrclib_instance: str,
    *,
    download_mode: str = "prefer_synced",
    progress_callback: ProgressCallback | None = None,
    db: sqlite3.Connection | None = None,
    config: Config | None = None,
    track: Track | None = None,
    api: LrcLibAPI | None = None,
) -> tuple[bool, str, int, str]:
    mode = normalize_download_mode(download_mode)
    notify = progress_callback or (lambda _msg: None)
    owns_db = db is None
    title_for_ui = ""
    try:
        if db is None:
            notify("Opening database...")
            db = sqlite3.connect(db_path, timeout=15.0)
            db.row_factory = sqlite3.Row

        notify("Reading track metadata...")

        track = track or get_track_by_id(db, track_id)
        title = (track.title or "").strip()
        artist = (track.artist_name or "").strip()
        album = (track.album_name or "").strip()
        title_for_ui = f"{artist} - {title}".strip(" -")
        duration_s = int(round(track.duration or 0.0))

        if not title or not artist:
            return False, "Missing title/artist; cannot search lyrics.", track_id, title_for_ui

        api_instance = api or LrcLibAPI(user_agent="pylrcget", base_url=lrclib_instance)
        lyrics = fetch_lyrics_with_retry(
            api_instance,
            notify=notify,
            title=title,
            artist=artist,
            album=album or None,
            duration_s=duration_s or None,
        )

        synced = _strip_empty(getattr(lyrics, "synced_lyrics", None))
        plain = _strip_empty(getattr(lyrics, "plain_lyrics", None))

        if mode == "plain_only":
            if plain:
                notify("Saving plain lyrics...")
                track = update_track_plain_lyrics(db, track_id, plain)
                sync_track_outputs(db, track, notify, config=config)
                return True, "Downloaded plain lyrics.", track_id, title_for_ui
            if synced:
                derived_plain = _strip_empty(_strip_timestamps(synced))
                if derived_plain:
                    notify("Saving plain lyrics derived from synced lyrics...")
                    track = update_track_plain_lyrics(db, track_id, derived_plain)
                    sync_track_outputs(db, track, notify, config=config)
                    return True, "Downloaded plain lyrics.", track_id, title_for_ui
            return False, "No plain lyrics found on LRCLIB for this track.", track_id, title_for_ui

        if synced:
            if not plain:
                plain = _strip_empty(_strip_timestamps(synced))
            notify("Saving synced + plain lyrics...")
            track = update_track_synced_lyrics(db, track_id, synced, plain or "")
            sync_track_outputs(db, track, notify, config=config)
            return True, "Downloaded synced lyrics.", track_id, title_for_ui

        if plain:
            if mode == "synced_only":
                return False, "Only plain lyrics were found; synced-only mode is enabled.", track_id, title_for_ui
            notify("Saving plain lyrics...")
            track = update_track_plain_lyrics(db, track_id, plain)
            sync_track_outputs(db, track, notify, config=config)
            return True, "Downloaded plain lyrics.", track_id, title_for_ui

        return False, "No lyrics found on LRCLIB for this track.", track_id, title_for_ui
    except Exception as exc:
        return False, f"Download failed: {exc}", track_id, title_for_ui
    finally:
        if owns_db and db is not None:
            db.close()
