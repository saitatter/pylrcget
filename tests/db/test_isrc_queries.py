from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from db.database import (
    add_tracks,
    get_track_by_id,
    get_tracks_for_bulk_download,
    initialize_database,
)
from tests import test_support as _test_support  # noqa: F401
from tests.test_support import make_fs_track, touch_text


def test_isrc_round_trips_through_single_and_bulk_track_queries(tmp_path: Path):
    db = initialize_database(str(tmp_path))
    try:
        audio = tmp_path / "isrc.mp3"
        touch_text(audio, "fixture")
        track = replace(
            make_fs_track(audio, artist="Artist", album="Album", title="Song"),
            isrc="USAAA0000001",
        )
        add_tracks(db, [track])
        track_id = int(db.execute("SELECT id FROM tracks LIMIT 1").fetchone()["id"])

        assert get_track_by_id(db, track_id).isrc == "USAAA0000001"
        assert get_tracks_for_bulk_download(db, [track_id])[track_id].isrc == "USAAA0000001"
    finally:
        db.close()
