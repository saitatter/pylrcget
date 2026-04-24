from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import sqlite3
import time

from PySide6.QtCore import QObject, QThread, Signal

from core.lrclib_client import LrcLibAPI
from db.queries import get_track_by_id
from ui.services.lyrics_match_retry import (
    LyricsMatchCandidate,
    RetrySearchQuery,
    build_retry_search_queries,
    choose_best_candidate,
)


RELAXED_RETRY_ACCEPT_SCORE = 90
MAX_PARALLEL_QUERY_WORKERS = 3


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

            for idx, track_id in enumerate(self.track_ids, start=1):
                if self.isInterruptionRequested():
                    break

                try:
                    track = get_track_by_id(db, track_id)
                except (sqlite3.Error, KeyError, TypeError):
                    self.progress.emit(idx, total, f"Track {track_id}", "Track no longer exists; skipped.")
                    continue
                if track is None:
                    self.progress.emit(idx, total, f"Track {track_id}", "Track no longer exists; skipped.")
                    continue
                title = (track.title or "").strip()
                artist = (track.artist_name or "").strip()
                album = (track.album_name or "").strip()
                label = f"{artist} - {title}".strip(" -") or f"Track {track_id}"
                best: LyricsMatchCandidate | None = None

                queries = build_retry_search_queries(artist=artist, title=title, album=album)
                query_workers = min(MAX_PARALLEL_QUERY_WORKERS, max(1, len(queries)))
                self.progress.emit(idx - 1, total, label, f"Trying relaxed search ({query_workers} at a time)...")
                with ThreadPoolExecutor(max_workers=query_workers) as executor:
                    pending = {}
                    next_query_index = 0

                    def submit_next_query() -> None:
                        nonlocal next_query_index
                        if next_query_index >= len(queries):
                            return
                        query = queries[next_query_index]
                        next_query_index += 1
                        pending[
                            executor.submit(
                                self._search_retry_query,
                                track_id,
                                label,
                                artist,
                                title,
                                album,
                                query,
                            )
                        ] = query

                    for _ in range(query_workers):
                        submit_next_query()

                    while pending and not self.isInterruptionRequested():
                        done, _ = wait(pending, return_when=FIRST_COMPLETED)
                        should_stop = False
                        for future in done:
                            query = pending.pop(future)
                            try:
                                candidate = future.result()
                            except Exception as exc:
                                self.progress.emit(
                                    idx - 1,
                                    total,
                                    label,
                                    f"{query.label} failed: {type(exc).__name__}",
                                )
                            else:
                                if candidate is not None and (best is None or candidate.score > best.score):
                                    best = candidate
                                should_stop = best is not None and best.score >= RELAXED_RETRY_ACCEPT_SCORE

                            if should_stop:
                                for pending_future in pending:
                                    pending_future.cancel()
                                pending.clear()
                                break
                            submit_next_query()

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

    def _search_retry_query(
        self,
        track_id: int,
        label: str,
        artist: str,
        title: str,
        album: str,
        query: RetrySearchQuery,
    ) -> LyricsMatchCandidate | None:
        api = LrcLibAPI(self.lrclib_instance)
        results = api.search_lyrics(
            query=query.query or None,
            track_name=query.title or None,
            artist_name=query.artist or None,
            album_name=query.album or None,
        )
        return choose_best_candidate(
            track_id=track_id,
            track_label=label,
            artist=artist,
            title=title,
            album=album,
            query_label=query.label,
            results=results,
        )
