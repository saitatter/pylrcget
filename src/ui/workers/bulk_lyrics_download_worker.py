from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import sqlite3
import time
from typing import TypedDict

from PySide6.QtCore import QObject, QThread, Signal
from core.lrclib_client import LrcLibAPI

from db.queries import get_config, get_track_by_id
from ui.services.download_modes import normalize_download_mode
from ui.services.lyrics_download_service import (
    LyricsDownloadMatch,
    apply_lyrics_match_to_track,
    find_best_lyrics_match,
)

MAX_PARALLEL_DOWNLOAD_WORKERS = 4


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
        self._completed_count = 0

    def run(self) -> None:
        total = len(self.track_ids)
        self._started_at = time.perf_counter()
        ok_count = 0
        fail_count = 0
        cancelled = False
        completed = 0
        jobs: list[_DownloadJob] = []
        db = None
        try:
            db = sqlite3.connect(self.db_path, timeout=15.0)
            db.row_factory = sqlite3.Row
            config = get_config(db)

            for track_id in self.track_ids:
                if self.isInterruptionRequested():
                    cancelled = True
                    break
                try:
                    track = get_track_by_id(db, track_id)
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
                    jobs.append(
                        _DownloadJob(
                            track_id=int(track_id),
                            label=label,
                            title=title,
                            artist=artist,
                            album=(track.album_name or "").strip(),
                            duration_s=int(round(track.duration or 0.0)) or None,
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
                with ThreadPoolExecutor(max_workers=worker_count) as executor:
                    pending = {executor.submit(self._fetch_job_match, job): job for job in jobs}
                    while pending and not self.isInterruptionRequested():
                        done, _ = wait(pending, return_when=FIRST_COMPLETED)
                        for future in done:
                            job = pending.pop(future)
                            completed += 1
                            self._completed_count = completed
                            try:
                                result = future.result()
                            except Exception as exc:
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

                            ok, msg, _updated = apply_lyrics_match_to_track(
                                db,
                                track_id=job.track_id,
                                match=result.match,
                                download_mode=self.download_mode,
                                notify=lambda _status: None,
                                config=config,
                            )
                            if ok:
                                ok_count += 1
                            else:
                                fail_count += 1
                            self.itemFinished.emit(job.track_id, bool(ok), job.label, msg)
                            self.progress.emit(completed, total, job.label, msg, self._elapsed())

                    if self.isInterruptionRequested():
                        cancelled = True
                        for pending_future in pending:
                            pending_future.cancel()
        finally:
            if db is not None:
                db.close()

        stats: BulkDownloadStats = {
            "total": total,
            "ok": ok_count,
            "failed": fail_count,
            "cancelled": cancelled,
        }
        if cancelled:
            self.finishedBatch.emit(False, "Lyrics download cancelled.", stats)
        else:
            self.finishedBatch.emit(True, f"Finished lyrics download. Success: {ok_count}, Failed: {fail_count}.", stats)

    def _fetch_job_match(self, job: _DownloadJob) -> _DownloadFetchResult:
        api = LrcLibAPI(self.lrclib_instance)

        def _notify(status: str) -> None:
            self.progress.emit(self._completed_count, len(self.track_ids), job.label, status, self._elapsed())

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
        except Exception as exc:
            return _DownloadFetchResult(job=job, error=str(exc))

    def _elapsed(self) -> float:
        if not self._started_at:
            return 0.0
        return time.perf_counter() - self._started_at
