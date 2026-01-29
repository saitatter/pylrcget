# ui/lyrics_download_worker.py
from __future__ import annotations

import sqlite3
from PySide6.QtCore import QThread, Signal

from lrclib import LrcLibAPI  # pip install lrclibapi

from db.database import (
    get_track_by_id,
    update_track_synced_lyrics,
    update_track_plain_lyrics,
    update_track_instrumental,
)

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

    def __init__(self, db_path: str, track_id: int, lrclib_instance: str = "https://lrclib.net", parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.track_id = track_id
        self.lrclib_instance = (lrclib_instance or "https://lrclib.net").rstrip("/")
        if not self.lrclib_instance.endswith("/api"):
            self.lrclib_instance += "/api"

    def run(self):
        try:
            self.progress.emit("Reading track metadata...")
            db = sqlite3.connect(self.db_path)
            db.row_factory = sqlite3.Row

            track = get_track_by_id(db, self.track_id)
            title = (track.title or "").strip()
            artist = (track.artist_name or "").strip()
            album = (track.album_name or "").strip()
            duration_s = int(round(track.duration or 0.0))

            if not title or not artist:
                db.close()
                self.finished.emit(False, "Missing title/artist; cannot search lyrics.", self.track_id)
                return

            self.progress.emit("Querying LRCLIB...")
            api = LrcLibAPI(user_agent="lrcget-python/0.1", base_url=self.lrclib_instance)

            lyrics = api.get_lyrics(
                track_name=title,
                artist_name=artist,
                album_name=album or None,
                duration=duration_s or None,
            )

            synced = _strip_empty(getattr(lyrics, "synced_lyrics", None))
            plain = _strip_empty(getattr(lyrics, "plain_lyrics", None))

            # dacă există synced, îl salvăm + derivăm plain din el (ca în Vue)
            if synced:
                if not plain:
                    plain = _strip_empty(_strip_timestamps(synced))
                self.progress.emit("Saving synced + plain lyrics...")
                update_track_synced_lyrics(db, self.track_id, synced, plain or "")
                db.close()
                self.finished.emit(True, "Downloaded synced lyrics.", self.track_id)
                return

            # altfel, doar plain
            if plain:
                self.progress.emit("Saving plain lyrics...")
                update_track_plain_lyrics(db, self.track_id, plain)
                db.close()
                self.finished.emit(True, "Downloaded plain lyrics.", self.track_id)
                return

            # instrumental (LRCLIB poate returna ceva gen [au: instrumental] în synced)
            # dacă vrei: detectezi aici; momentan doar "not found"
            db.close()
            self.finished.emit(False, "No lyrics found on LRCLIB for this track.", self.track_id)

        except Exception as e:
            self.finished.emit(False, f"Download failed: {e}", self.track_id)
