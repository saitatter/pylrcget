"""Sequential AI sync with per-track drafts, progress and cancellation."""

from __future__ import annotations

import os
import sqlite3
from collections import deque
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from core.utils import plain_text_from_lrc
from db.models import Track
from ui.workers.ai.ai_sync_worker import AiSyncWorker


def batch_lyrics_source(track: Track) -> str:
    if track.dirty_lyrics_present:
        return (track.dirty_txt_lyrics or plain_text_from_lrc(track.dirty_lrc_lyrics or "")).strip()
    return (track.txt_lyrics or plain_text_from_lrc(track.lrc_lyrics or "")).strip()


def lyrics_revision(track: Track) -> tuple:
    return tuple(getattr(track, field) for field in (
        "dirty_lyrics_present", "dirty_txt_lyrics", "dirty_lrc_lyrics", "txt_lyrics", "lrc_lyrics",
    ))


class AIBatchSyncController(QObject):
    def __init__(
        self, *, get_track: Callable[[int], Track], playback_path: Callable[[Track], str],
        store_result: Callable[[int, str], bool], overlay,
        progress_text: Callable[[str], str] = str, parent=None,
    ) -> None:
        super().__init__(parent)
        self._get_track = get_track
        self._playback_path = playback_path
        self._store_result = store_result
        self._overlay = overlay
        self._progress_text = progress_text
        self._pending: deque[int] = deque()
        self._worker = None
        self.busy = False
        self._cancelled = False
        self._settings: dict = {}
        self._total = self._done = self._succeeded = self._failed = self._skipped = 0

    def start(self, track_ids: list[int], settings: dict) -> bool:
        if self.busy or not track_ids:
            return False
        self._pending = deque(dict.fromkeys(int(track_id) for track_id in track_ids))
        self._total = len(self._pending)
        self._done = self._succeeded = self._failed = self._skipped = 0
        self._settings = dict(settings)
        self._cancelled = False
        self.busy = True
        self._overlay.start_batch("Selected tracks", self._total)
        QTimer.singleShot(0, self._advance)
        return True

    def cancel(self) -> None:
        self._cancelled = True
        self._pending.clear()
        if self._worker is not None:
            self._worker.requestInterruption()

    def shutdown(self) -> bool:
        self.cancel()
        return self._worker is None or self._worker.wait(5000)

    def _advance(self) -> None:
        if not self.busy:
            return
        if self._cancelled or not self._pending:
            self.busy = False
            self._overlay.finish_batch(
                f"{self._succeeded} draft(s) ready, {self._failed} failed, "
                f"{self._skipped} skipped, {self._total - self._done} remaining."
                + (" Cancelled." if self._cancelled else " Save drafts to apply lyrics."),
                cancelled=self._cancelled,
            )
            return
        self._track_id = self._pending.popleft()
        self._label = f"Track {self._track_id}"
        try:
            track = self._get_track(self._track_id)
            self._label = track.title or self._label
            self._source = batch_lyrics_source(track)
            self._revision = lyrics_revision(track)
            path = self._playback_path(track)
            if track.instrumental or not self._source or not os.path.isfile(path):
                reason = "Instrumental" if track.instrumental else (
                    "No lyrics to synchronize" if not self._source else "Audio file not found"
                )
                self._skipped += 1
                self._record(f"Skipped: {reason}", False)
                QTimer.singleShot(0, self._advance)
                return
            self._result_seen = False
            worker = AiSyncWorker(
                path, self._source,
                device=str(self._settings.get("device") or "auto"),
                language=str(self._settings.get("language") or "auto"),
                enable_fuzzy=bool(self._settings.get("enable_fuzzy", True)),
                fuzzy_threshold=int(self._settings.get("fuzzy_threshold", 60)),
                enable_demucs_candidate=bool(self._settings.get("enable_demucs_candidate", True)),
                parent=self,
            )
            worker.progress.connect(self._progress)
            worker.completed.connect(self._completed)
            worker.finished.connect(self._finished)
            self._worker = worker
            self._progress("Starting AI Sync")
            worker.start()
        except (sqlite3.Error, OSError, ValueError, TypeError, AttributeError) as exc:
            self._failed += 1
            self._record(str(exc), False)
            QTimer.singleShot(0, self._advance)

    def _progress(self, message: str) -> None:
        # Stage messages use the same worker protocol as single-track sync.
        display = self._progress_text(str(message).split("|", 3)[-1])
        self._overlay.update_progress(self._done, self._total, self._label, display)

    def _completed(self, ok: bool, message: str, lrc: str) -> None:
        self._result_seen = True
        if self._cancelled:
            return
        if ok:
            try:
                current = self._get_track(self._track_id)
                if current.instrumental or lyrics_revision(current) != self._revision:
                    ok, message = False, "Lyrics changed during sync; current edits were kept."
                elif not lrc.strip():
                    ok, message = False, "AI returned no synchronized lyrics."
                else:
                    ok = self._store_result(self._track_id, lrc)
                    message = "Draft ready; save to apply." if ok else "Could not store AI draft."
            except (sqlite3.Error, OSError, ValueError, AttributeError) as exc:
                ok, message = False, str(exc)
        if ok:
            self._succeeded += 1
        else:
            self._failed += 1
        self._record(message, ok)

    def _record(self, message: str, ok: bool) -> None:
        self._done += 1
        self._overlay.append_result(self._label, message, ok)
        self._overlay.update_progress(self._done, self._total, self._label, message)

    def _finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        if not self._result_seen and not self._cancelled:
            self._failed += 1
            self._record("AI worker stopped without a result.", False)
        QTimer.singleShot(0, self._advance)
