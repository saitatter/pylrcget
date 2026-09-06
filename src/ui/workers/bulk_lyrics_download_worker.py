from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import TypedDict

from PySide6.QtCore import QObject, QThread, Signal

from core.lrclib_client import LrcLibAPI
from db.queries import get_tracks_for_bulk_download
from ui.services.download_modes import normalize_download_mode
from ui.services.lyrics_download_service import (
    LyricsDownloadMatch,
    find_best_lyrics_match,
    invalid_lrclib_duration_message,
    is_valid_lrclib_duration,
)
from ui.services.lyrics_match_retry import LyricsMatchCandidate

MAX_PARALLEL_DOWNLOAD_WORKERS = 4
DOWNLOAD_CANCEL_POLL_INTERVAL_S = 0.05


class BulkDownloadStats(TypedDict):
    total: int
    ok: int
    failed: int
    cancelled: bool


@dataclass(frozen=True)
class _DownloadJob:
    track_id: int
    label: str
    title: str
    artist: str
    album: str
    duration_s: int | None


@dataclass(frozen=True)
class _DownloadFetchResult:
    job: _DownloadJob
    match: LyricsDownloadMatch | None = None
    error: str = ""


class BulkLyricsDownloadWorker(QThread):
    progress = Signal(int, int, str, str, float)  # current, total, track label, status, elapsed seconds
    itemFinished = Signal(int, bool, str, str)  # track_id, ok, track label, message
    finishedBatch = Signal(bool, str, dict)  # ok, message, stats dict

    def __init__(
        self,
        db_path: str,
        track_ids: list[int],
        lrclib_instance: str,
        *,
        download_mode: str = "prefer_synced",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.track_ids = [int(t) for t in track_ids]
        self.lrclib_instance = lrclib_instance
        self.download_mode = normalize_download_mode(download_mode)
        self._started_at = 0.0
        self._thread_local = threading.local()

    def run(self) -> None:
        total = len(self.track_ids)
        self._started_at = time.perf_counter()
        ok_count = 0
        fail_count = 0
        cancelled = False
        completed = 0
        jobs: list[_DownloadJob] = []
        candidates: list[LyricsMatchCandidate] = []
        db = None
        try:
            db = sqlite3.connect(self.db_path, timeout=15.0)
            db.row_factory = sqlite3.Row

            tracks_by_id = get_tracks_for_bulk_download(db, self.track_ids)
            for track_id in self.track_ids:
                if self.isInterruptionRequested():
                    cancelled = True
                    break
                try:
                    track = tracks_by_id.get(int(track_id))
                    if track is None:
                        raise KeyError(f"Track not found: {track_id}")
                    title = (track.title or "").strip()
                    artist = (track.artist_name or "").strip()
                    label = f"{artist} - {title}".strip(" -") or f"Track {track_id}"
                    if not title or not artist:
                        fail_count += 1
                        completed += 1
                        msg = "Missing title/artist; cannot search lyrics."
                        self.itemFinished.emit(int(track_id), False, label, msg)
                        self.progress.emit(completed, total, label, msg, self._elapsed())
                        continue
                    duration_s = round(track.duration or 0.0) or None
                    if duration_s is not None and not is_valid_lrclib_duration(duration_s):
                        fail_count += 1
                        completed += 1
                        msg = invalid_lrclib_duration_message(duration_s)
                        self.itemFinished.emit(int(track_id), False, label, msg)
                        self.progress.emit(completed, total, label, msg, self._elapsed())
                        continue
                    jobs.append(
                        _DownloadJob(
                            track_id=int(track_id),
                            label=label,
                            title=title,
                            artist=artist,
                            album=(track.album_name or "").strip(),
                            duration_s=duration_s,
                        )
                    )
                except (sqlite3.Error, AttributeError, TypeError) as exc:
                    fail_count += 1
                    completed += 1
                    label = f"Track {track_id}"
                    msg = f"Failed to read track metadata: {exc}"
                    self.itemFinished.emit(int(track_id), False, label, msg)
                    self.progress.emit(completed, total, label, msg, self._elapsed())

            worker_count = min(MAX_PARALLEL_DOWNLOAD_WORKERS, max(1, len(jobs)))
            if jobs and not cancelled:
                self.progress.emit(
                    completed,
                    total,
                    "Lyrics download",
                    f"Searching LRCLIB ({worker_count} at a time)...",
                    self._elapsed(),
                )
                executor = ThreadPoolExecutor(max_workers=worker_count)
                pending = {}
                try:
                    pending = {executor.submit(self._fetch_job_match, job): job for job in jobs}
                    while pending:
                        if self.isInterruptionRequested():
                            cancelled = True
                            break
                        done, _ = wait(
                            pending,
                            timeout=DOWNLOAD_CANCEL_POLL_INTERVAL_S,
                            return_when=FIRST_COMPLETED,
                        )
                        if not done:
                            continue
                        for future in done:
                            if self.isInterruptionRequested():
                                cancelled = True
                                break
                            job = pending.pop(future)
                            completed += 1
                            try:
                                result = future.result()
                            except Exception as exc:  # noqa: BLE001
                                result = _DownloadFetchResult(job=job, error=str(exc))

                            if result.error:
                                fail_count += 1
                                msg = f"Download failed: {result.error}"
                                self.itemFinished.emit(job.track_id, False, job.label, msg)
                                self.progress.emit(completed, total, job.label, msg, self._elapsed())
                                continue
                            if result.match is None:
                                fail_count += 1
                                msg = "No lyrics found on LRCLIB for this track."
                                self.itemFinished.emit(job.track_id, False, job.label, msg)
                                self.progress.emit(completed, total, job.label, msg, self._elapsed())
                                continue

                            candidate = self._candidate_from_match(job, result.match)
                            if candidate is not None:
                                candidates.append(candidate)
                                ok_count += 1
                                msg = f"Candidate found. Match: {candidate.score}%."
                            else:
                                fail_count += 1
                                msg = "No usable lyrics found on LRCLIB for this track."
                            self.itemFinished.emit(job.track_id, candidate is not None, job.label, msg)
                            self.progress.emit(completed, total, job.label, msg, self._elapsed())

                    if self.isInterruptionRequested():
                        cancelled = True
                finally:
                    if cancelled or self.isInterruptionRequested():
                        cancelled = True
                        for pending_future in pending:
                            pending_future.cancel()
                        executor.shutdown(wait=False, cancel_futures=True)
                    else:
                        executor.shutdown(wait=True)
        finally:
            if db is not None:
                db.close()

        stats: BulkDownloadStats = {
            "total": total,
            "ok": ok_count,
            "failed": fail_count,
            "cancelled": cancelled,
            "candidates": candidates,
            "requires_review": bool(candidates) and not cancelled,
        }
        if cancelled:
            self.finishedBatch.emit(False, "Lyrics download cancelled.", stats)
        else:
            self.finishedBatch.emit(True, f"Finished lyrics download. Success: {ok_count}, Failed: {fail_count}.", stats)

    def _fetch_job_match(self, job: _DownloadJob) -> _DownloadFetchResult:
        api = self._api_for_current_thread()

        def _notify(status: str) -> None:
            if self.isInterruptionRequested():
                return
            self.progress.emit(-1, len(self.track_ids), job.label, status, self._elapsed())

        try:
            match = find_best_lyrics_match(
                api,
                notify=_notify,
                track_id=job.track_id,
                track_label=job.label,
                title=job.title,
                artist=job.artist,
                album=job.album,
                duration_s=job.duration_s,
            )
            return _DownloadFetchResult(job=job, match=match)
        except Exception as exc:  # noqa: BLE001
            return _DownloadFetchResult(job=job, error=str(exc))

    def _api_for_current_thread(self) -> LrcLibAPI:
        api = getattr(self._thread_local, "api", None)
        if api is None:
            api = LrcLibAPI(self.lrclib_instance)
            self._thread_local.api = api
        return api

    def _elapsed(self) -> float:
        if not self._started_at:
            return 0.0
        return time.perf_counter() - self._started_at

    def _candidate_from_match(self, job: _DownloadJob, match: LyricsDownloadMatch) -> LyricsMatchCandidate | None:
        result = match.result
        synced = str(getattr(result, "synced_lyrics", "") or "")
        plain = str(getattr(result, "plain_lyrics", "") or "")
        if not synced and not plain:
            return None
        return LyricsMatchCandidate(
            track_id=job.track_id,
            track_label=job.label,
            query_label=match.query_label,
            score=int(match.score),
            artist_name=str(getattr(result, "artist_name", "") or job.artist),
            track_name=str(getattr(result, "track_name", "") or job.title),
            album_name=str(getattr(result, "album_name", "") or job.album),
            duration=int(getattr(result, "duration", 0) or job.duration_s or 0),
            kind="Synced" if synced else "Plain",
            plain_lyrics=plain,
            synced_lyrics=synced,
        )
