from __future__ import annotations

import sqlite3
import time

from PySide6.QtCore import QObject, QThread, Signal

from core.lrclib_client import LrcLibAPI
from db.queries import get_track_by_id
from ui.services.lyrics_match_retry import (
    LyricsMatchCandidate,
    build_retry_search_queries,
    choose_best_candidate,
)


class LyricsRetrySearchWorker(QThread):
    progress = Signal(int, int, str, str)  # current, total, track label, status
    finishedSearch = Signal(list, str)  # list[LyricsMatchCandidate], error

    def __init__(
        self,
        db_path: str,
        track_ids: list[int],
        lrclib_instance: str,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.track_ids = [int(track_id) for track_id in track_ids]
        self.lrclib_instance = lrclib_instance

    def run(self) -> None:
        total = len(self.track_ids)
        candidates: list[LyricsMatchCandidate] = []
        db = None
        try:
            db = sqlite3.connect(self.db_path, timeout=15.0)
            db.row_factory = sqlite3.Row
            api = LrcLibAPI(self.lrclib_instance)

            for idx, track_id in enumerate(self.track_ids, start=1):
                if self.isInterruptionRequested():
                    break

                track = get_track_by_id(db, track_id)
                title = (track.title or "").strip()
                artist = (track.artist_name or "").strip()
                album = (track.album_name or "").strip()
                label = f"{artist} - {title}".strip(" -") or f"Track {track_id}"
                best: LyricsMatchCandidate | None = None

                queries = build_retry_search_queries(artist=artist, title=title, album=album)
                for query_idx, query in enumerate(queries, start=1):
                    if self.isInterruptionRequested():
                        break
                    self.progress.emit(idx - 1, total, label, f"Trying {query.label}...")
                    results = api.search_lyrics(
                        query=query.query or None,
                        track_name=query.title or None,
                        artist_name=query.artist or None,
                        album_name=query.album or None,
                    )
                    candidate = choose_best_candidate(
                        track_id=track_id,
                        track_label=label,
                        artist=artist,
                        title=title,
                        album=album,
                        query_label=query.label,
                        results=results,
                    )
                    if candidate is not None and (best is None or candidate.score > best.score):
                        best = candidate
                    if query_idx < len(queries):
                        time.sleep(0.15)

                if best is not None:
                    candidates.append(best)
                    self.progress.emit(idx, total, label, f"Best match: {best.score}%")
                else:
                    self.progress.emit(idx, total, label, "No relaxed match found.")
                if idx < total:
                    time.sleep(0.25)

            self.finishedSearch.emit(candidates, "")
        except Exception as exc:
            self.finishedSearch.emit(candidates, str(exc))
        finally:
            if db is not None:
                db.close()
