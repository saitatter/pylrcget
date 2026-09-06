from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from db.database import get_config, initialize_database, set_config
from library.scan_library import AudioMetadata
from tests.library.reference_library import ReferenceLibraryBuilder
from tests.test_support import touch_text
from ui.workers.library_scanner import LibraryScanner


def _metadata_for_path(path: str) -> AudioMetadata:
    stem = Path(path).stem
    return AudioMetadata(
        title=stem.title(),
        album="Album One" if stem in {"alpha", "beta"} else "Album Two",
        artist="Artist One" if stem != "gamma" else "Artist Two",
        album_artist="Artist One" if stem != "gamma" else "Artist Two",
        track_number=1 if stem in {"alpha", "gamma"} else 2,
        duration=180.0 if stem != "gamma" else 200.0,
    )


def _metadata_reader(path: str):
    return None, _metadata_for_path(path)


def _db_state(db_path: str) -> dict[str, tuple[object, ...]]:
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            """
            SELECT tracks.file_path, tracks.title, artists.name AS artist,
                   albums.name AS album, albums.album_artist_name AS album_artist,
                   tracks.duration, tracks.track_number, tracks.txt_lyrics,
                   tracks.lrc_lyrics, tracks.instrumental
            FROM tracks
            JOIN artists ON tracks.artist_id = artists.id
            JOIN albums ON tracks.album_id = albums.id
            """
        ).fetchall()
    finally:
        db.close()
    return {
        str(row["file_path"]): tuple(row[key] for key in (
            "title",
            "artist",
            "album",
            "album_artist",
            "duration",
            "track_number",
            "txt_lyrics",
            "lrc_lyrics",
            "instrumental",
        ))
        for row in rows
    }


def _assert_matches_reference(db_path: str, expected) -> None:
    actual = _db_state(db_path)
    reference = {path: track.logical_state() for path, track in expected.items()}
    assert actual == reference


def test_reference_library_soak_matches_incremental_scanner(tmp_path, monkeypatch):
    music_dir = tmp_path / "Music"
    music_dir.mkdir()
    alpha = music_dir / "alpha.mp3"
    beta = music_dir / "beta.mp3"
    touch_text(alpha, "audio alpha")
    touch_text(beta, "audio beta")

    db = initialize_database(str(tmp_path))
    config = get_config(db)
    set_config(db, replace(config, scan_lyrics_source_mode="sidecar_only"))
    db.close()
    db_path = str(tmp_path / "pylrcget.db.sqlite3")

    monkeypatch.setattr("ui.workers.library_scanner.read_audio_metadata_for_scan", _metadata_reader)

    reference = ReferenceLibraryBuilder(_metadata_reader)

    def scan_and_compare():
        LibraryScanner(db_path, [str(music_dir)], scan_worker_count=2).run()
        expected = reference.build([str(music_dir)], scan_lyrics_source_mode="sidecar_only")
        _assert_matches_reference(db_path, expected)

    scan_and_compare()

    touch_text(music_dir / "alpha.lrc", "[00:01.00]alpha first")
    scan_and_compare()

    touch_text(music_dir / "alpha.lrc", "[00:02.00]alpha second")
    scan_and_compare()

    touch_text(music_dir / "beta.txt", "beta plain")
    scan_and_compare()

    (music_dir / "alpha.lrc").unlink()
    scan_and_compare()

    beta.unlink()
    gamma = music_dir / "gamma.mp3"
    touch_text(gamma, "audio gamma")
    scan_and_compare()

    # The reference builder must remain complete after a repeated no-op cycle.
    scan_and_compare()
