from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import sqlite3
import time
from typing import Callable

from requests import exceptions as requests_exceptions

from core.lrclib_client import LrcLibAPI, LrcLibError, NotFoundError, RateLimitError, ServerError

from core.embed_lyrics import embed_lyrics_for_track
from core.lyrics_sidecar import export_lyrics_sidecars
from db.database import get_config, get_track_by_id, update_track_plain_lyrics, update_track_synced_lyrics
from db.models import Config, Track
from ui.services.download_modes import normalize_download_mode
from ui.services.lyrics_match_retry import build_retry_search_queries, choose_best_candidate

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]
_RETRYABLE_API_ERRORS = (RateLimitError, ServerError, requests_exceptions.Timeout, requests_exceptions.ConnectionError)
_MAX_LRCLIB_RETRIES = 3
_INITIAL_BACKOFF_S = 0.5
_LRC_TIMESTAMP_RE = re.compile(r"\[(?:\d+:)?\d+:\d+(?:\.\d+)?\]")
LRCLIB_MIN_DURATION_S = 1
LRCLIB_MAX_DURATION_S = 3600


@dataclass(frozen=True)
class TrackOutputSyncResult:
    sidecar_paths: tuple[str, ...] = ()
    sidecar_error: Exception | None = None
    embedded: bool = False
    embed_error: Exception | None = None


@dataclass(frozen=True)
class LyricsDownloadMatch:
    result: object
    score: int
    query_label: str


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
    if _is_lrclib_not_found(exc):
        return False
    if isinstance(exc, _RETRYABLE_API_ERRORS):
        return True
    if isinstance(exc, LrcLibError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def _is_lrclib_not_found(exc: Exception) -> bool:
    if isinstance(exc, NotFoundError):
        return True
    if not isinstance(exc, LrcLibError):
        return False
    message = f"{exc.reason} {exc.message}".casefold()
    return exc.status_code == 404 or "not found" in message or "notfound" in message


def is_valid_lrclib_duration(duration_s: int | None) -> bool:
    if duration_s is None or duration_s <= 0:
        return False
    return LRCLIB_MIN_DURATION_S <= int(duration_s) <= LRCLIB_MAX_DURATION_S


def invalid_lrclib_duration_message(duration_s: int) -> str:
    return (
        f"Invalid duration for LRCLIB ({duration_s}s); "
        f"must be between {LRCLIB_MIN_DURATION_S} and {LRCLIB_MAX_DURATION_S}. Skipped without request."
    )


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
                album_name=album or "",
                duration=duration_s or 0,
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


def find_best_lyrics_match(
    api: LrcLibAPI,
    *,
    notify: ProgressCallback,
    track_id: int,
    track_label: str,
    title: str,
    artist: str,
    album: str,
    duration_s: int | None,
) -> LyricsDownloadMatch | None:
    try:
        lyrics = fetch_lyrics_with_retry(
            api,
            notify=notify,
            title=title,
            artist=artist,
            album=album or None,
            duration_s=duration_s or None,
        )
        if _strip_empty(getattr(lyrics, "synced_lyrics", None)) or _strip_empty(getattr(lyrics, "plain_lyrics", None)):
            return LyricsDownloadMatch(lyrics, 100, "exact metadata")
        notify("Exact LRCLIB match has no usable lyrics; trying alternatives...")
    except Exception as exc:
        if not _is_lrclib_not_found(exc):
            raise
        notify("Exact LRCLIB match not found; trying alternatives...")

    best = None
    for query in build_retry_search_queries(artist=artist, title=title, album=album):
        try:
            notify(f"Searching LRCLIB with {query.label}...")
            results = api.search_lyrics(
                query=query.query or None,
                track_name=query.title or None,
                artist_name=query.artist or None,
                album_name=query.album or None,
            )
        except Exception as exc:
            logger.warning("Alternative LRCLIB search failed for %s via %s: %s", track_label, query.label, exc)
            if _should_retry_lrclib_error(exc):
                raise
            continue
        candidate = choose_best_candidate(
            track_id=track_id,
            track_label=track_label,
            artist=artist,
            title=title,
            album=album,
            query_label=query.label,
            results=results,
        )
        if candidate is not None and (best is None or candidate.score > best.score):
            best = candidate
        if best is not None and best.score >= 100:
            break

    if best is None:
        return None
    return LyricsDownloadMatch(best, int(best.score), best.query_label)


def sync_track_outputs(
    db: sqlite3.Connection,
    track: Track,
    notify: ProgressCallback,
    *,
    config: Config | None = None,
) -> None:
    config = config or get_config(db)
    result = sync_track_outputs_with_result(track, config, notify=notify)
    if result.sidecar_error:
        notify(f"Warning: sidecar export failed: {result.sidecar_error}")
    if result.embed_error:
        notify(f"Warning: lyrics embedding failed: {result.embed_error}")


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


def apply_lyrics_match_to_track(
    db: sqlite3.Connection,
    *,
    track_id: int,
    match: LyricsDownloadMatch,
    download_mode: str,
    notify: ProgressCallback,
    config: Config | None = None,
) -> tuple[bool, str, Track | None]:
    mode = normalize_download_mode(download_mode)
    lyrics = match.result
    synced = _strip_empty(getattr(lyrics, "synced_lyrics", None))
    plain = _strip_empty(getattr(lyrics, "plain_lyrics", None))
    score_note = f" Match: {match.score}%."

    if mode == "plain_only":
        if plain:
            notify("Saving plain lyrics...")
            update_track_plain_lyrics(db, track_id, plain)
            track = get_track_by_id(db, track_id)
            sync_track_outputs(db, track, notify, config=config)
            return True, f"Downloaded plain lyrics.{score_note}", track
        if synced:
            derived_plain = _strip_empty(_strip_timestamps(synced))
            if derived_plain:
                notify("Saving plain lyrics derived from synced lyrics...")
                update_track_plain_lyrics(db, track_id, derived_plain)
                track = get_track_by_id(db, track_id)
                sync_track_outputs(db, track, notify, config=config)
                return True, f"Downloaded plain lyrics.{score_note}", track
        return False, f"No plain lyrics found on LRCLIB for this track.{score_note}", None

    if synced:
        if not plain:
            plain = _strip_empty(_strip_timestamps(synced))
        notify("Saving synced + plain lyrics...")
        update_track_synced_lyrics(db, track_id, synced, plain or "")
        track = get_track_by_id(db, track_id)
        sync_track_outputs(db, track, notify, config=config)
        return True, f"Downloaded synced lyrics.{score_note}", track

    if plain:
        if mode == "synced_only":
            return False, f"Only plain lyrics were found; synced-only mode is enabled.{score_note}", None
        notify("Saving plain lyrics...")
        update_track_plain_lyrics(db, track_id, plain)
        track = get_track_by_id(db, track_id)
        sync_track_outputs(db, track, notify, config=config)
        return True, f"Downloaded plain lyrics.{score_note}", track

    return False, f"No lyrics found on LRCLIB for this track.{score_note}", None


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
        if not is_valid_lrclib_duration(duration_s):
            return False, invalid_lrclib_duration_message(duration_s), track_id, title_for_ui

        api_instance = api or LrcLibAPI(lrclib_instance)
        match = find_best_lyrics_match(
            api_instance,
            notify=notify,
            track_id=track_id,
            track_label=title_for_ui,
            title=title,
            artist=artist,
            album=album,
            duration_s=duration_s or None,
        )
        if match is None:
            return False, "No lyrics found on LRCLIB for this track.", track_id, title_for_ui
        ok, msg, _track = apply_lyrics_match_to_track(
            db,
            track_id=track_id,
            match=match,
            download_mode=mode,
            notify=notify,
            config=config,
        )
        return ok, msg, track_id, title_for_ui
    except Exception as exc:
        return False, f"Download failed: {exc}", track_id, title_for_ui
    finally:
        if owns_db and db is not None:
            db.close()
