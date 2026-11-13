from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal

from tests import test_support
from ui.controllers.ai_batch_sync_controller import (
    AIBatchSyncController,
    batch_lyrics_source,
)


class FakeWorker(QObject):
    progress = Signal(str)
    completed = Signal(bool, str, str)
    finished = Signal()

    def __init__(self, path, lyrics, *, parent=None, **settings):
        super().__init__(parent)
        self.path, self.lyrics, self.settings = path, lyrics, settings
        self.interrupted = False

    def start(self):
        pass

    def requestInterruption(self):
        self.interrupted = True

    def finish(self, ok=True, message="Ready", lrc="[00:01.00]Lyrics"):
        self.completed.emit(ok, message, lrc)
        self.finished.emit()


@pytest.fixture
def batch(tmp_path, monkeypatch):
    app = test_support.qt_app()
    path = tmp_path / "audio.wav"
    path.touch()
    tracks = {
        i: SimpleNamespace(
            title=f"Track {i}", instrumental=False, txt_lyrics=f"Lyrics {i}",
            lrc_lyrics="", dirty_lyrics_present=False, dirty_txt_lyrics="", dirty_lrc_lyrics="",
            file_path=str(path),
        ) for i in range(1, 5)
    }
    monkeypatch.setattr("ui.controllers.ai_batch_sync_controller.AiSyncWorker", FakeWorker)
    store = MagicMock(return_value=True)
    overlay = MagicMock()
    controller = AIBatchSyncController(
        get_track=tracks.__getitem__, playback_path=lambda track: track.file_path,
        store_result=store, overlay=overlay,
    )

    def events():
        for _ in range(5):
            app.processEvents()

    yield controller, tracks, store, overlay, events
    controller.cancel()
    controller.deleteLater()
    QCoreApplication.sendPostedEvents(controller, QEvent.Type.DeferredDelete)
    events()


def test_batch_runs_sequentially_and_continues_after_failure(batch):
    controller, _tracks, store, overlay, events = batch
    assert controller.start([1, 1, 2], {"device": "cpu"})
    assert not controller.start([3], {})
    events()
    first = controller._worker
    assert first.lyrics == "Lyrics 1"
    assert first.settings["device"] == "cpu"
    first.finish()
    events()
    assert controller._worker is not first
    assert controller._worker.lyrics == "Lyrics 2"
    controller._worker.finish(False, "Backend failed", "")
    events()
    assert not controller.busy
    store.assert_called_once_with(1, "[00:01.00]Lyrics")
    assert "1 draft(s) ready, 1 failed" in overlay.finish_batch.call_args.args[0]


def test_batch_skips_instrumentals_empty_lyrics_and_missing_audio(batch):
    controller, tracks, store, overlay, events = batch
    tracks[1].instrumental = True
    tracks[2].txt_lyrics = ""
    tracks[3].file_path = "nonexistent-audio-file"
    controller.start([1, 2, 3], {})
    events()
    assert not controller.busy
    store.assert_not_called()
    assert "3 skipped" in overlay.finish_batch.call_args.args[0]


def test_cancel_stops_queue_and_discards_late_results(batch):
    controller, _tracks, store, overlay, events = batch
    controller.start([1, 2], {})
    events()
    worker = controller._worker
    controller.cancel()
    assert worker.interrupted
    worker.finish()
    events()
    store.assert_not_called()
    assert controller._worker is None
    assert not controller.busy
    assert overlay.finish_batch.call_args.kwargs["cancelled"]


def test_batch_does_not_overwrite_edits_made_while_syncing(batch):
    controller, tracks, store, overlay, events = batch
    controller.start([1], {})
    events()
    tracks[1].dirty_lyrics_present = True
    tracks[1].dirty_txt_lyrics = "New user edits"
    controller._worker.finish()
    events()
    store.assert_not_called()
    assert "current edits were kept" in overlay.append_result.call_args.args[1]


def test_batch_respects_empty_and_synced_drafts(batch):
    _, tracks, _, _, _ = batch
    track = tracks[1]
    track.dirty_lyrics_present = True
    # Clearing the draft must not fall back to saved lyrics.
    assert batch_lyrics_source(track) == ""
    track.dirty_lrc_lyrics = "[00:01.00]Draft text"
    assert batch_lyrics_source(track) == "Draft text"


def test_batch_preserves_timestamp_edits_even_when_plain_text_is_unchanged(batch):
    controller, tracks, store, overlay, events = batch
    tracks[1].lrc_lyrics = "[00:01.00]Lyrics 1"
    controller.start([1], {})
    events()
    tracks[1].lrc_lyrics = "[00:02.00]Lyrics 1"
    controller._worker.finish()
    events()
    store.assert_not_called()
    assert "current edits were kept" in overlay.append_result.call_args.args[1]


def test_batch_result_updates_only_the_draft_in_an_isolated_database(tmp_path):
    from db.database import (
        add_tracks,
        get_track_by_id,
        initialize_database,
        update_track_plain_lyrics,
        update_track_synced_lyrics,
    )
    from ui.main_window import MainWindow

    path = tmp_path / "song.wav"
    path.touch()
    db = initialize_database(str(tmp_path))
    try:
        add_tracks(db, [test_support.make_fs_track(path, artist="Artist", album="Album", title="Song")])
        track_id = db.execute("SELECT id FROM tracks").fetchone()[0]
        update_track_plain_lyrics(db, track_id, "Original lyrics")
        update_track_synced_lyrics(db, track_id, "[00:02.00]Original lyrics", "Original lyrics")
        view = MagicMock()
        window = SimpleNamespace(
            app_state=SimpleNamespace(db=db), _editing_track_id=track_id,
            _set_track_lyrics_views=MagicMock(), track_list=view, albums_tab=view,
            artists_tab=view, album_artists_tab=view,
        )
        assert MainWindow._on_auto_sync_finished(
            window, True, "Ready", "[00:01.00]Original lyrics", track_id, batch=True,
        )
        track = get_track_by_id(db, track_id)
        assert track.txt_lyrics == "Original lyrics"
        assert track.lrc_lyrics == "[00:02.00]Original lyrics"
        assert track.dirty_lyrics_present
        assert track.dirty_lrc_lyrics == "[00:01.00]Original lyrics"
        assert not path.with_suffix(".lrc").exists()
        window._set_track_lyrics_views.assert_called_once()
    finally:
        db.close()
