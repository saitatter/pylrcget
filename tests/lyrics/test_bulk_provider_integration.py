from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from db.database import add_tracks, initialize_database
from lyrics.providers import LyricsProviderCapabilities, LyricsProviderResult
from lyrics.source_settings import (
    default_lyrics_source_settings,
    merge_lyrics_source_settings,
)
from tests.test_support import make_fs_track
from ui.workers.bulk_lyrics_download_worker import BulkLyricsDownloadWorker


class _FakeMusixmatchProvider:
    provider_id = "musixmatch"
    display_name = "Musixmatch"

    def __init__(self) -> None:
        self.calls = 0

    def capabilities(self):
        return LyricsProviderCapabilities(True, True, True, True, False)

    def lookup(self, track, *, requested_mode, cancel_event=None):
        del requested_mode, cancel_event
        self.calls += 1
        return LyricsProviderResult(
            provider="musixmatch",
            provider_track_id="musixmatch-123",
            plain_lyrics="musixmatch plain",
            synced_lyrics="[00:01.00]musixmatch synced",
            instrumental=False,
            match_score=100.0,
            match_method="exact isrc",
            remote_title=track.title,
            remote_artist=track.artists[0],
            remote_album=track.album,
            remote_duration_seconds=track.duration_seconds,
            remote_isrc=track.isrc,
        )


def test_bulk_worker_falls_back_from_lrclib_plain_to_musixmatch_synced(tmp_path: Path):
    db = initialize_database(str(tmp_path))
    try:
        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"audio")
        add_tracks(db, [make_fs_track(audio, artist="Artist", album="Album", title="Song")])
        settings = default_lyrics_source_settings()
        settings["priority"] = ["lrclib", "musixmatch"]
        settings["enabled"] = {"lrclib": True, "musixmatch": True}
        db.execute(
            "UPDATE config_data SET ui_state_json = ?",
            (merge_lyrics_source_settings("", settings),),
        )
        db.commit()
        track_id = int(db.execute("SELECT id FROM tracks LIMIT 1").fetchone()["id"])
    finally:
        db.close()

    worker = BulkLyricsDownloadWorker(
        str(tmp_path / "pylrcget.db.sqlite3"),
        [track_id],
        "https://lrclib.test/api",
    )
    musixmatch = _FakeMusixmatchProvider()
    finished: list[dict] = []
    worker.finishedBatch.connect(lambda _ok, _message, stats: finished.append(stats))
    worker.itemFinished.connect(lambda _track_id, _ok, _label, _message: None)

    fake_lrclib = SimpleNamespace(
        synced_lyrics=None,
        plain_lyrics="lrclib plain",
        track_name="Song",
        artist_name="Artist",
        album_name="Album",
        duration=180,
    )
    with patch("ui.workers.bulk_lyrics_download_worker.LrcLibAPI") as api_cls:
        api_cls.return_value.get_lyrics.return_value = fake_lrclib
        worker._musixmatch_provider_for_current_thread = Mock(return_value=musixmatch)
        worker.run()

    assert api_cls.return_value.get_lyrics.call_count == 1
    assert musixmatch.calls == 1
    assert len(finished) == 1
    assert finished[0]["ok"] == 1
    assert finished[0]["candidates"]
    assert finished[0]["candidates"][0].provider == "musixmatch"
