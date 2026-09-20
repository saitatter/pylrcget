from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from db.database import (
    add_tracks,
    get_track_by_id,
    initialize_database,
    update_track_plain_lyrics,
)
from db.migrations import upgrade_database_if_needed
from library.scan_library import LyricsScanResult
from tests.test_support import make_fs_track


def test_scan_result_reports_plain_and_synced_provenance_independently():
    result = LyricsScanResult(
        embedded_txt="embedded plain",
        embedded_lrc=None,
        sidecar_txt="sidecar plain",
        sidecar_lrc="[00:01.00]sidecar synced",
    )

    assert result.txt_source == "embedded"
    assert result.lrc_source == "sidecar"


def test_track_lyrics_sources_round_trip_and_manual_update(tmp_path: Path):
    db = initialize_database(str(tmp_path))
    try:
        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"audio")
        add_tracks(
            db,
            [
                replace(
                    make_fs_track(audio, artist="Artist", album="Album", title="Song"),
                    txt_lyrics="sidecar plain",
                    lrc_lyrics="[00:01.00]embedded synced",
                    txt_lyrics_source="sidecar",
                    lrc_lyrics_source="embedded",
                )
            ],
        )
        track_id = int(db.execute("SELECT id FROM tracks LIMIT 1").fetchone()["id"])

        track = get_track_by_id(db, track_id)
        assert track.txt_lyrics_source == "sidecar"
        assert track.lrc_lyrics_source == "embedded"

        update_track_plain_lyrics(db, track_id, "downloaded plain", source="tidal")
        updated = get_track_by_id(db, track_id)
        assert updated.txt_lyrics_source == "tidal"
        assert updated.lrc_lyrics_source is None
    finally:
        db.close()


def test_v5_database_migration_adds_nullable_provenance_columns():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.execute(
            """
            CREATE TABLE tracks (
                id INTEGER PRIMARY KEY,
                file_path TEXT,
                txt_lyrics TEXT,
                lrc_lyrics TEXT
            )
            """
        )
        db.execute("PRAGMA user_version=5")
        db.commit()

        upgrade_database_if_needed(db, 5)

        columns = {row["name"] for row in db.execute("PRAGMA table_info(tracks)")}
        assert {"txt_lyrics_source", "lrc_lyrics_source"} <= columns
    finally:
        db.close()
