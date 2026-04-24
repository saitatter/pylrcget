from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import sqlite3
import threading

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
MAX_PARALLEL_RETRY_WORKERS = 4
RETRY_CANCEL_POLL_INTERVAL_S = 0.05


@dataclass(frozen=True)
class _RetryTrack:
    id: int
    label: str
    artist: str
    title: str
    album: str


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
        self._thread_local = threading.local()

    def run(self) -> None:
        total = len(self.track_ids)
        candidates: list[LyricsMatchCandidate] = []
        retry_tracks: list[_RetryTrack] = []
        completed = 0
        db = None
        try:
            db = sqlite3.connect(self.db_path, timeout=15.0)
            db.row_factory = sqlite3.Row

            for track_id in self.track_ids:
                if self.isInterruptionRequested():
                    break

                try:
                    track = get_track_by_id(db, track_id)
                except (sqlite3.Error, KeyError, TypeError):
                    completed += 1
                    self.progress.emit(completed, total, "Retry search", "Track no longer exists; skipped.")
                    continue
                if track is None:
                    completed += 1
                    self.progress.emit(completed, total, "Retry search", "Track no longer exists; skipped.")
                    continue
                title = (track.title or "").strip()
                artist = (track.artist_name or "").strip()
                album = (track.album_name or "").strip()
                label = f"{artist} - {title}".strip(" -") or f"Track {track_id}"
                retry_tracks.append(_RetryTrack(int(track_id), label, artist, title, album))

            if db is not None:
                db.close()
                db = None

            worker_count = min(MAX_PARALLEL_RETRY_WORKERS, max(1, len(retry_tracks)))
            self.progress.emit(completed, total, "Retry search", f"Searching failed tracks ({worker_count} at a time)...")
            cancelled = False
            executor = ThreadPoolExecutor(max_workers=worker_count)
            pending = {}
            try:
                pending = {executor.submit(self._search_retry_track, track): track for track in retry_tracks}
                while pending:
                    if self.isInterruptionRequested():
                        cancelled = True
                        break
                    done, _ = wait(
                        pending,
                        timeout=RETRY_CANCEL_POLL_INTERVAL_S,
                        return_when=FIRST_COMPLETED,
                    )
                    if not done:
                        continue
                    for future in done:
                        if self.isInterruptionRequested():
                            cancelled = True
                            break
                        track = pending.pop(future)
                        completed += 1
                        try:
                            candidate = future.result()
                        except Exception as exc:
                            self.progress.emit(
                                completed,
                                total,
                                "Retry search",
                                f"{track.label} failed: {type(exc).__name__}",
                            )
                            continue
                        if candidate is not None:
                            candidates.append(candidate)
                        status = f"{completed}/{total} failed tracks searched"
                        self.progress.emit(completed, total, "Retry search", status)

                if self.isInterruptionRequested():
                    cancelled = True
            finally:
                if cancelled or self.isInterruptionRequested():
                    for pending_future in pending:
                        pending_future.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
                else:
                    executor.shutdown(wait=True)

            self.finishedSearch.emit(candidates, "")
        except Exception as exc:
            self.finishedSearch.emit(candidates, str(exc))
        finally:
            if db is not None:
                db.close()

    def _search_retry_track(self, track: _RetryTrack) -> LyricsMatchCandidate | None:
        best: LyricsMatchCandidate | None = None
        api = self._api_for_current_thread()
        for query in build_retry_search_queries(artist=track.artist, title=track.title, album=track.album):
            if self.isInterruptionRequested():
                break
            try:
                candidate = self._search_retry_query(api, track, query)
            except Exception:
                continue
            if candidate is not None and (best is None or candidate.score > best.score):
                best = candidate
            if best is not None and best.score >= RELAXED_RETRY_ACCEPT_SCORE:
                break
        return best

    def _search_retry_query(
        self,
        api: LrcLibAPI,
        track: _RetryTrack,
        query: RetrySearchQuery,
    ) -> LyricsMatchCandidate | None:
        results = api.search_lyrics(
            query=query.query or None,
            track_name=query.title or None,
            artist_name=query.artist or None,
            album_name=query.album or None,
        )
        return choose_best_candidate(
            track_id=track.id,
            track_label=track.label,
            artist=track.artist,
            title=track.title,
            album=track.album,
            query_label=query.label,
            results=results,
        )

    def _api_for_current_thread(self) -> LrcLibAPI:
        api = getattr(self._thread_local, "api", None)
        if api is None:
            api = LrcLibAPI(self.lrclib_instance)
            self._thread_local.api = api
        return api
