from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal

from tests import test_support as _test_support  # noqa: F401
from db.queries import get_config, get_track_by_id, set_config
from db.database import add_tracks, initialize_database
from tests.test_support import make_fs_track, qt_app, touch_text
from ui.controllers.lyrics_download_controller import LyricsDownloadController
from ui.services.lyrics_match_retry import LyricsMatchCandidate


class _FakeOverlay:
    def __init__(self) -> None:
        self.started: list[tuple[str, int]] = []
        self.progress: list[tuple[int, int, str, str]] = []
        self.results: list[tuple[str, str, bool]] = []
        self.finished: list[tuple[str, bool]] = []
        self.retry_failed_counts: list[int] = []

    def start_batch(self, mode_label: str, total: int) -> None:
        self.started.append((mode_label, total))

    def update_progress(self, current: int, total: int, track_label: str, status: str) -> None:
        self.progress.append((current, total, track_label, status))

    def append_result(self, track_label: str, message: str, ok: bool) -> None:
        self.results.append((track_label, message, ok))

    def finish_batch(self, message: str, *, cancelled: bool = False) -> None:
        self.finished.append((message, cancelled))

    def show_retry_failed(self, count: int) -> None:
        self.retry_failed_counts.append(int(count))


class _FakeWorker(QObject):
    progress = Signal(int, int, str, str, float)
    itemFinished = Signal(int, bool, str, str)
    finishedBatch = Signal(bool, str, object)
    instances: list["_FakeWorker"] = []

    def __init__(self, db_path: str, track_ids: list[int], lrclib_instance: str, *, download_mode: str = "prefer_synced", parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.track_ids = list(track_ids)
        self.lrclib_instance = lrclib_instance
        self.download_mode = download_mode
        self._running = False
        self.interrupted = False
        self.started = False
        type(self).instances.append(self)

    def start(self) -> None:
        self.started = True
        self._running = True

    def isRunning(self) -> bool:
        return self._running

    def requestInterruption(self) -> None:
        self.interrupted = True

    @classmethod
    def reset(cls) -> None:
        cls.instances = []


class _FakeMatchDialog:
    selected: list[LyricsMatchCandidate] = []

    def __init__(self, candidates, parent=None):
        del parent
        self.candidates = list(candidates)

    def exec(self):
        return True

    def selected_candidates(self):
        return list(self.selected)


class LyricsDownloadControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = qt_app()

    def setUp(self) -> None:
        _FakeWorker.reset()

    def _make_controller(self, app_state, overlay: _FakeOverlay, *, current_track_id=None):
        statuses: list[tuple[str, int | None]] = []
        notifications: list[tuple[str, str]] = []
        download_states: dict[int, str] = {}
        refreshed: list[str] = []

        app_state.notify = lambda message, level: notifications.append((message, level))

        controller = LyricsDownloadController(
            app_state,
            overlay,
            normalize_lrclib_base=lambda url: f"{url.rstrip('/')}/api",
            show_status=lambda message, timeout=None: statuses.append((message, timeout)),
            current_player_track_id=lambda: current_track_id,
            set_track_lyrics_views=lambda track: refreshed.append(f"lyrics:{track.id}"),
            refresh_visible_library_view=lambda: refreshed.append("view"),
            refresh_history=lambda: refreshed.append("history"),
            set_track_download_state=lambda track_id, state: download_states.__setitem__(int(track_id), state),
            get_track_download_state=lambda track_id: download_states.get(int(track_id), "idle"),
        )
        return controller, statuses, notifications, download_states, refreshed

    def test_download_missing_uses_current_configured_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                app_state = SimpleNamespace(db=db, db_path=str(Path(tmp) / "pylrcget.db.sqlite3"))
                overlay = _FakeOverlay()

                for mode, label in (
                    ("prefer_synced", "Prefer synced"),
                    ("synced_only", "Synced only"),
                    ("plain_only", "Plain only"),
                ):
                    config = replace(get_config(db), download_lyrics_mode=mode)
                    set_config(db, config)
                    controller, statuses, notifications, download_states, _ = self._make_controller(app_state, overlay)
                    overlay.started.clear()
                    statuses.clear()
                    notifications.clear()
                    download_states.clear()
                    _FakeWorker.reset()

                    with (
                        self.subTest(mode=mode),
                        patch("ui.controllers.lyrics_download_controller.BulkLyricsDownloadWorker", _FakeWorker),
                        patch("ui.controllers.lyrics_download_controller.get_track_ids_for_download_mode", return_value=[11, 11, 12]) as ids_mock,
                    ):
                        controller.download_missing()

                    self.assertEqual(ids_mock.call_args[0][1], mode)
                    self.assertEqual(len(_FakeWorker.instances), 1)
                    worker = _FakeWorker.instances[0]
                    self.assertEqual(worker.track_ids, [11, 12])
                    self.assertEqual(worker.download_mode, mode)
                    self.assertTrue(worker.started)
                    self.assertEqual(overlay.started[-1], (label, 2))
                    self.assertEqual(download_states, {11: "loading", 12: "loading"})
                    self.assertFalse(notifications)
                    self.assertIn("Starting lyrics download...", statuses[-1][0])
            finally:
                db.close()

    def test_cancel_requests_interruption_on_active_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                app_state = SimpleNamespace(db=db, db_path=str(Path(tmp) / "pylrcget.db.sqlite3"))
                overlay = _FakeOverlay()
                controller, *_ = self._make_controller(app_state, overlay)

                with patch("ui.controllers.lyrics_download_controller.BulkLyricsDownloadWorker", _FakeWorker):
                    controller.start_downloads([21], mode_override="plain_only")
                    self.assertEqual(len(_FakeWorker.instances), 1)
                    worker = _FakeWorker.instances[0]
                    self.assertFalse(worker.interrupted)
                    controller.cancel()
                    self.assertTrue(worker.interrupted)
            finally:
                db.close()

    def test_download_missing_reports_mode_specific_semantics_when_nothing_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                app_state = SimpleNamespace(db=db, db_path=str(Path(tmp) / "pylrcget.db.sqlite3"))
                overlay = _FakeOverlay()

                config = replace(get_config(db), download_lyrics_mode="plain_only")
                set_config(db, config)
                controller, statuses, notifications, *_ = self._make_controller(app_state, overlay)

                with patch("ui.controllers.lyrics_download_controller.get_track_ids_for_download_mode", return_value=[]):
                    controller.download_missing()

                self.assertFalse(overlay.started)
                self.assertIn(
                    (
                        "No tracks are missing lyrics for Plain only. Tracks count as missing when they do not have plain lyrics yet.",
                        "info",
                    ),
                    notifications,
                )
                self.assertIn(
                    (
                        "No tracks are missing lyrics for Plain only. Tracks count as missing when they do not have plain lyrics yet.",
                        4000,
                    ),
                    statuses,
                )
            finally:
                db.close()

    def test_progress_and_finish_flow_updates_overlay_and_notifications(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                app_state = SimpleNamespace(db=db, db_path=str(Path(tmp) / "pylrcget.db.sqlite3"))
                overlay = _FakeOverlay()
                controller, statuses, notifications, download_states, refreshed = self._make_controller(app_state, overlay)

                with (
                    patch("ui.controllers.lyrics_download_controller.BulkLyricsDownloadWorker", _FakeWorker),
                    patch("ui.controllers.lyrics_download_controller.QTimer.singleShot"),
                ):
                    controller.start_downloads([31, 32], mode_override="synced_only")
                    worker = _FakeWorker.instances[0]

                    worker.progress.emit(1, 2, "Artist - Song", "Querying LRCLIB...", 0.5)
                    worker.itemFinished.emit(31, True, "Artist - Song", "Downloaded synced lyrics.")
                    worker.finishedBatch.emit(True, "Finished lyrics download. Success: 1, Failed: 0.", {"ok": 1, "failed": 0, "cancelled": False})

                self.assertEqual(overlay.progress[-1], (1, 2, "Artist - Song", "Querying LRCLIB..."))
                self.assertEqual(overlay.results[-1], ("Artist - Song", "Downloaded synced lyrics.", True))
                self.assertEqual(overlay.finished[-1], ("Finished lyrics download. Success: 1, Failed: 0.", False))
                self.assertEqual(download_states[31], "success")
                self.assertEqual(download_states[32], "idle")
                self.assertIn(("Lyrics downloaded successfully.", "success"), notifications)
                self.assertIn("view", refreshed)
                self.assertIn("history", refreshed)
                self.assertEqual(statuses[-1], ("Finished lyrics download. Success: 1, Failed: 0.", 4000))
            finally:
                db.close()

    def test_failed_batch_exposes_manual_retry_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                app_state = SimpleNamespace(db=db, db_path=str(Path(tmp) / "pylrcget.db.sqlite3"))
                overlay = _FakeOverlay()
                controller, _, notifications, download_states, _ = self._make_controller(app_state, overlay)

                with (
                    patch("ui.controllers.lyrics_download_controller.BulkLyricsDownloadWorker", _FakeWorker),
                    patch("ui.controllers.lyrics_download_controller.QTimer.singleShot"),
                ):
                    controller.start_downloads([41, 42], mode_override="prefer_synced")
                    worker = _FakeWorker.instances[0]

                    worker.itemFinished.emit(41, False, "Artist - Missing", "No lyrics found on LRCLIB for this track.")
                    worker.itemFinished.emit(42, True, "Artist - Found", "Downloaded synced lyrics.")
                    worker.finishedBatch.emit(
                        True,
                        "Finished lyrics download. Success: 1, Failed: 1.",
                        {"ok": 1, "failed": 1, "cancelled": False},
                    )

                self.assertEqual(overlay.retry_failed_counts[-1], 1)
                self.assertEqual(download_states[41], "error")
                self.assertIn(("Finished lyrics download. Success: 1, Failed: 1.", "warning"), notifications)
            finally:
                db.close()

    def test_batch_candidates_require_review_before_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "candidate.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Air Supply", album="Greatest Hits", title="All Out Of Love")])
                track_id = int(db.execute("SELECT id FROM tracks LIMIT 1").fetchone()["id"])
                app_state = SimpleNamespace(db=db, db_path=str(Path(tmp) / "pylrcget.db.sqlite3"))
                overlay = _FakeOverlay()
                controller, _, notifications, download_states, refreshed = self._make_controller(app_state, overlay)
                candidate = LyricsMatchCandidate(
                    track_id=track_id,
                    track_label="Air Supply - All Out Of Love",
                    query_label="exact metadata",
                    score=100,
                    artist_name="Air Supply",
                    track_name="All Out of Love",
                    album_name="Lost in Love",
                    duration=240,
                    kind="Synced",
                    plain_lyrics="plain text",
                    synced_lyrics="[00:01.00]plain text",
                )
                _FakeMatchDialog.selected = [candidate]

                with (
                    patch("ui.controllers.lyrics_download_controller.BulkLyricsDownloadWorker", _FakeWorker),
                    patch("ui.controllers.lyrics_download_controller.BatchLyricsMatchDialog", _FakeMatchDialog),
                    patch("ui.controllers.lyrics_download_controller.QTimer.singleShot"),
                ):
                    controller.start_downloads([track_id], mode_override="prefer_synced")
                    worker = _FakeWorker.instances[0]
                    worker.itemFinished.emit(track_id, True, candidate.track_label, "Candidate found. Match: 100%.")

                    before_apply = get_track_by_id(db, track_id)
                    self.assertIsNone(before_apply.lrc_lyrics)
                    self.assertIsNone(before_apply.txt_lyrics)

                    worker.finishedBatch.emit(
                        True,
                        "Finished lyrics search. Candidates: 1, Failed: 0.",
                        {"total": 1, "ok": 1, "failed": 0, "cancelled": False, "candidates": [candidate]},
                    )

                after_apply = get_track_by_id(db, track_id)
                self.assertEqual(after_apply.lrc_lyrics, "[00:01.00]plain text")
                self.assertEqual(after_apply.txt_lyrics, "plain text")
                self.assertEqual(download_states[track_id], "success")
                self.assertIn(("Applied lyrics to 1 downloaded track.", "success"), notifications)
                self.assertIn("view", refreshed)
                self.assertIn("history", refreshed)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
