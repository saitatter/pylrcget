from __future__ import annotations

from pathlib import Path

from db.database import add_tracks, initialize_database
from db.query_modules.remote_mapping_queries import (
    get_remote_track_mappings,
    upsert_remote_track_mapping,
)
from tests.test_support import make_fs_track


def test_bulk_remote_mapping_query_returns_all_requested_rows(tmp_path: Path):
    db = initialize_database(str(tmp_path))
    try:
        paths = [tmp_path / f"song_{index}.mp3" for index in range(3)]
        for path in paths:
            path.write_bytes(b"audio")
        add_tracks(
            db,
            [make_fs_track(path, artist="Artist", album="Album", title=path.stem) for path in paths],
        )
        track_ids = [int(row["id"]) for row in db.execute("SELECT id FROM tracks ORDER BY id")]
        for track_id in track_ids:
            upsert_remote_track_mapping(
                db,
                track_id=track_id,
                provider="musixmatch",
                provider_track_id=f"musixmatch-{track_id}",
                match_method="metadata",
                match_score=90,
                remote_isrc=None,
                remote_title="Song",
                remote_artist="Artist",
                remote_album="Album",
                remote_duration=180,
                verified_at=1,
                local_metadata_fingerprint=f"fingerprint-{track_id}",
            )

        statements: list[str] = []
        db.set_trace_callback(statements.append)
        mappings = get_remote_track_mappings(db, track_ids, "musixmatch")

        assert list(mappings) == track_ids
        assert mappings[track_ids[1]]["provider_track_id"] == "musixmatch-2"
        assert sum("FROM remote_track_mapping" in statement for statement in statements) == 1
    finally:
        db.close()
