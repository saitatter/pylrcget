# ui/lyrics_download_worker.py
from __future__ import annotations

import logging
import sqlite3
from PySide6.QtCore import QThread, Signal

from lrclib import LrcLibAPI  # pip install lrclibapi

from core.embed_lyrics import embed_lyrics_for_track
from core.lyrics_sidecar import export_lyrics_sidecars
from db.database import get_track_by_id, get_config, update_track_plain_lyrics, update_track_synced_lyrics
from db.models import Config, Track

logger = logging.getLogger(__name__)

def _strip_empty(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    return s or None

def _strip_timestamps(lrc: str) -> str:
    # plainLyrics = remove [mm:ss.xx]
    out_lines = []
    for line in lrc.splitlines():
        # remove leading [..] blocks
        while line.startswith("[") and "]" in line:
            line = line.split("]", 1)[1].lstrip()
        out_lines.append(line)
    return "\n".join(out_lines).strip()

class LyricsDownloadWorker(QThread):
    progress = Signal(str)
    finished = Signal(bool, str, int)  # ok, msg, track_id

    def __init__(
        self,
        db_path: str,
        track_id: int,
        lrclib_instance: str = "https://lrclib.net",
        *,
        download_mode: str = "prefer_synced",
        parent=None,
    ):
        super().__init__(parent)
        self.db_path = db_path
        self.track_id = track_id
        self.lrclib_instance = (lrclib_instance or "https://lrclib.net").rstrip("/")
        if not self.lrclib_instance.endswith("/api"):
            self.lrclib_instance += "/api"
        self.download_mode = (download_mode or "prefer_synced").strip() or "prefer_synced"

    def run(self):
        ok, msg, track_id, _ = download_track_lyrics(
            self.db_path,
            self.track_id,
            self.lrclib_instance,
            download_mode=self.download_mode,
            progress_callback=self.progress.emit,
        )
        self.finished.emit(ok, msg, track_id)


def download_track_lyrics(
    db_path: str,
    track_id: int,
    lrclib_instance: str,
    *,
    download_mode: str = "prefer_synced",
    progress_callback=None,
    db: sqlite3.Connection | None = None,
    config: Config | None = None,
    track=None,
) -> tuple[bool, str, int, str]:
    mode = (download_mode or "prefer_synced").strip() or "prefer_synced"
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

        notify("Querying LRCLIB...")
        api = LrcLibAPI(user_agent="lrcget-python/0.1", base_url=lrclib_instance)

        lyrics = api.get_lyrics(
            track_name=title,
            artist_name=artist,
            album_name=album or None,
            duration=duration_s or None,
        )

        synced = _strip_empty(getattr(lyrics, "synced_lyrics", None))
        plain = _strip_empty(getattr(lyrics, "plain_lyrics", None))

        if mode == "plain_only":
            if plain:
                notify("Saving plain lyrics...")
                track = update_track_plain_lyrics(db, track_id, plain)
                _sync_track_outputs(db, track, notify, config=config)
                return True, "Downloaded plain lyrics.", track_id, title_for_ui
            if synced:
                derived_plain = _strip_empty(_strip_timestamps(synced))
                if derived_plain:
                    notify("Saving plain lyrics derived from synced lyrics...")
                    track = update_track_plain_lyrics(db, track_id, derived_plain)
                    _sync_track_outputs(db, track, notify, config=config)
                    return True, "Downloaded plain lyrics.", track_id, title_for_ui
            return False, "No plain lyrics found on LRCLIB for this track.", track_id, title_for_ui

        if synced:
            if not plain:
                plain = _strip_empty(_strip_timestamps(synced))
            notify("Saving synced + plain lyrics...")
            track = update_track_synced_lyrics(db, track_id, synced, plain or "")
            _sync_track_outputs(db, track, notify, config=config)
            return True, "Downloaded synced lyrics.", track_id, title_for_ui

        if plain:
            if mode == "synced_only":
                return False, "Only plain lyrics were found; synced-only mode is enabled.", track_id, title_for_ui
            notify("Saving plain lyrics...")
            track = update_track_plain_lyrics(db, track_id, plain)
            _sync_track_outputs(db, track, notify, config=config)
            return True, "Downloaded plain lyrics.", track_id, title_for_ui

        return False, "No lyrics found on LRCLIB for this track.", track_id, title_for_ui
    except Exception as e:
        return False, f"Download failed: {e}", track_id, title_for_ui
    finally:
        if owns_db and db is not None:
            db.close()


def _sync_track_outputs(
    db: sqlite3.Connection,
    track: Track,
    notify,
    *,
    config: Config | None = None,
) -> None:
    config = config or get_config(db)

    if config.save_lyrics_sidecars:
        try:
            notify("Writing lyrics sidecar files...")
            export_lyrics_sidecars(track, config)
        except Exception as exc:
            logger.warning("Failed to export lyrics sidecars for track %s: %s", track.id, exc)

    if config.try_embed_lyrics:
        try:
            notify("Embedding lyrics into the audio file...")
            embed_lyrics_for_track(track)
        except Exception as exc:
            logger.warning("Failed to embed lyrics for track %s: %s", track.id, exc)
