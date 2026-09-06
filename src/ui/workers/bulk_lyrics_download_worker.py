from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import TypedDict

from PySide6.QtCore import QObject, QThread, Signal

from core.lrclib_client import LrcLibAPI
from core.utils import prepare_input
from db.queries import get_tracks_for_bulk_download
from ui.services.download_modes import normalize_download_mode
from ui.services.lyrics_download_service import (
    LyricsDownloadMatch,
    LyricsMatchCancelled,
    find_best_lyrics_match,
    invalid_lrclib_duration_message,
    is_valid_lrclib_duration,
)
from ui.services.lyrics_match_retry import LyricsMatchCandidate

MAX_PARALLEL_DOWNLOAD_WORKERS = 4
DOWNLOAD_MAX_PENDING_MULTIPLIER = 4
DOWNLOAD_CANCEL_POLL_INTERVAL_S = 0.05


class _SharedRateLimitCooldown:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._deadline = 0.0

    def wait(self, is_cancelled) -> bool:
        while True:
            if is_cancelled():
                return False
            with self._condition:
                remaining = self._deadline - time.monotonic()
                if remaining <= 0:
                    return not is_cancelled()
                self._condition.wait(timeout=min(remaining, DOWNLOAD_CANCEL_POLL_INTERVAL_S))

    def record(self, delay_s: float) -> None:
        deadline = time.monotonic() + max(0.0, float(delay_s))
        with self._condition:
            self._deadline = max(self._deadline, deadline)
            self._condition.notify_all()


class BulkDownloadStats(TypedDict):
    total: int
    ok: int
    failed: int
    cancelled: bool
    unique_lookup_keys: int
    deduplicated_tracks: int


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
    cancelled: bool = False


@dataclass(frozen=True)
class _DownloadLookupGroup:
    key: tuple[str, str, str, int | None]
    jobs: tuple[_DownloadJob, ...]

    @property
    def representative(self) -> _DownloadJob:
        return self.jobs[0]


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
        self._rate_limit_cooldown = _SharedRateLimitCooldown()

    def run(self) -> None:
        total = len(self.track_ids)
        self._started_at = time.perf_counter()
        self._rate_limit_cooldown = _SharedRateLimitCooldown()
        ok_count = 0
        fail_count = 0
        cancelled = False
        completed = 0
        jobs: list[_DownloadJob] = []
        lookup_groups: list[_DownloadLookupGroup] = []
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

            lookup_groups = self._group_jobs(jobs)
            worker_count = min(MAX_PARALLEL_DOWNLOAD_WORKERS, max(1, len(lookup_groups)))
            if lookup_groups and not cancelled:
                self.progress.emit(
                    completed,
                    total,
                    "Lyrics download",
                    f"Searching LRCLIB ({worker_count} at a time)...",
                    self._elapsed(),
                )
                executor = ThreadPoolExecutor(max_workers=worker_count)
                pending = {}
                next_job_index = 0
                max_pending = worker_count * DOWNLOAD_MAX_PENDING_MULTIPLIER

                def submit_available() -> None:
                    nonlocal next_job_index
                    while (
                        next_job_index < len(lookup_groups)
                        and len(pending) < max_pending
                        and not self.isInterruptionRequested()
                    ):
                        group = lookup_groups[next_job_index]
                        next_job_index += 1
                        pending[executor.submit(self._fetch_job_match, group.representative)] = group

                try:
                    submit_available()
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
                            group = pending.pop(future)
                            try:
                                result = future.result()
                            except Exception as exc:  # noqa: BLE001
                                result = _DownloadFetchResult(job=group.representative, error=str(exc))
                            if result.cancelled:
                                cancelled = True
                                break

                            for job in group.jobs:
                                completed += 1
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
                            break
                        submit_available()

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
            "unique_lookup_keys": len(lookup_groups),
            "deduplicated_tracks": max(0, len(jobs) - len(lookup_groups)),
            "candidates": candidates,
            "requires_review": bool(candidates) and not cancelled,
        }
        if cancelled:
            self.finishedBatch.emit(False, "Lyrics download cancelled.", stats)
        else:
            self.finishedBatch.emit(True, f"Finished lyrics download. Success: {ok_count}, Failed: {fail_count}.", stats)

    @staticmethod
    def _group_jobs(jobs: list[_DownloadJob]) -> list[_DownloadLookupGroup]:
        groups: dict[tuple[str, str, str, int | None], list[_DownloadJob]] = {}
        order: list[tuple[str, str, str, int | None]] = []
        for job in jobs:
            key = (
                prepare_input(job.artist),
                prepare_input(job.title),
                prepare_input(job.album),
                job.duration_s,
            )
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(job)
        return [_DownloadLookupGroup(key=key, jobs=tuple(groups[key])) for key in order]

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
                before_request=self._before_lrclib_request,
                on_rate_limit=self._record_lrclib_rate_limit,
            )
            return _DownloadFetchResult(job=job, match=match)
        except LyricsMatchCancelled:
            return _DownloadFetchResult(job=job, cancelled=True)
        except Exception as exc:  # noqa: BLE001
            return _DownloadFetchResult(job=job, error=str(exc))

    def _before_lrclib_request(self) -> bool:
        return self._rate_limit_cooldown.wait(self.isInterruptionRequested)

    def _record_lrclib_rate_limit(self, delay_s: float) -> None:
        self._rate_limit_cooldown.record(delay_s)

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
