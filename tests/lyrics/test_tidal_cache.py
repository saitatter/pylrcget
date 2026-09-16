from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import Mock

from db.database import CURRENT_DB_VERSION, add_tracks, initialize_database
from db.migrations import upgrade_database_if_needed
from db.query_modules.remote_mapping_queries import (
    get_remote_track_mapping,
    upsert_remote_track_mapping,
)
from db.schema import SCHEMA_V1_SQL
from lyrics.providers import (
    CachedTidalCatalogueResolver,
    MatchQuality,
    TidalTrack,
    TidalTrackResolution,
    TrackLookupContext,
    TrackMatchScore,
    local_metadata_fingerprint,
)
from tests.test_support import make_fs_track


def _context(**overrides) -> TrackLookupContext:
    values = {
        "track_id": 1,
        "file_path": "C:/Music/song.flac",
        "title": "Song",
        "artists": ("Artist",),
        "album": "Album",
        "album_artist": "Artist",
        "duration_seconds": 180.0,
        "track_number": 1,
        "isrc": "USAAA0000001",
    }
    values.update(overrides)
    return TrackLookupContext(**values)


def _resolution(provider_track_id: str = "123") -> TidalTrackResolution:
    return TidalTrackResolution(
        track=TidalTrack(
            provider_track_id=provider_track_id,
            title="Song",
            artists=("Artist",),
            album="Album",
            album_artist="Artist",
            duration_seconds=180.0,
            track_number=1,
            isrc="USAAA0000001",
        ),
        score=TrackMatchScore(
            score=100.0,
            quality=MatchQuality.EXACT_ID,
            method="exact isrc",
        ),
    )


def test_local_metadata_fingerprint_ignores_path_and_lyrics_state():
    first = _context(file_path="C:/Music/one.flac")
    equivalent = _context(file_path="D:/Other/renamed.flac", title="  SONG  ")

    assert local_metadata_fingerprint(first) == local_metadata_fingerprint(equivalent)
    assert local_metadata_fingerprint(first) != local_metadata_fingerprint(_context(title="Other Song"))


def test_remote_mapping_query_round_trips_and_upserts(tmp_path: Path):
    db = initialize_database(str(tmp_path))
    try:
        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"audio")
        add_tracks(db, [make_fs_track(audio, artist="Artist", album="Album", title="Song")])
        track_id = int(db.execute("SELECT id FROM tracks LIMIT 1").fetchone()["id"])

        upsert_remote_track_mapping(
            db,
            track_id=track_id,
            provider="tidal",
            provider_track_id="old",
            match_method="metadata",
            match_score=88,
            remote_isrc="USAAA0000001",
            remote_title="Song",
            remote_artist="Artist",
            remote_album="Album",
            remote_duration=180,
            verified_at=1,
            local_metadata_fingerprint="fingerprint-1",
        )
        upsert_remote_track_mapping(
            db,
            track_id=track_id,
            provider="tidal",
            provider_track_id="new",
            match_method="exact isrc",
            match_score=100,
            remote_isrc="USAAA0000001",
            remote_title="Song",
            remote_artist="Artist",
            remote_album="Album",
            remote_duration=180,
            verified_at=2,
            local_metadata_fingerprint="fingerprint-2",
        )

        row = get_remote_track_mapping(db, track_id, "tidal")
        assert row is not None
        assert row["provider_track_id"] == "new"
        assert row["local_metadata_fingerprint"] == "fingerprint-2"
        assert db.execute("SELECT COUNT(*) FROM remote_track_mapping").fetchone()[0] == 1
    finally:
        db.close()


def test_cached_resolver_hits_without_another_catalogue_request(tmp_path: Path):
    db = initialize_database(str(tmp_path))
    try:
        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"audio")
        add_tracks(db, [make_fs_track(audio, artist="Artist", album="Album", title="Song")])
        track_id = int(db.execute("SELECT id FROM tracks LIMIT 1").fetchone()["id"])
        local = _context(track_id=track_id)
        client = Mock()
        client.resolve_track.return_value = _resolution()
        resolver = CachedTidalCatalogueResolver(client, db, clock=lambda: 123.0)

        first = resolver.resolve_track(local)
        second = resolver.resolve_track(local)

        assert first is not None and second is not None
        assert first.track.provider_track_id == second.track.provider_track_id == "123"
        assert second.score.diagnostics == {"cache_hit": True}
        assert client.resolve_track.call_count == 1
    finally:
        db.close()


def test_cached_resolver_invalidates_after_catalogue_metadata_changes(tmp_path: Path):
    db = initialize_database(str(tmp_path))
    try:
        audio = tmp_path / "song.mp3"
        audio.write_bytes(b"audio")
        add_tracks(db, [make_fs_track(audio, artist="Artist", album="Album", title="Song")])
        track_id = int(db.execute("SELECT id FROM tracks LIMIT 1").fetchone()["id"])
        client = Mock()
        client.resolve_track.side_effect = [_resolution("123"), _resolution("456")]
        resolver = CachedTidalCatalogueResolver(client, db)

        resolver.resolve_track(_context(track_id=track_id))
        changed = resolver.resolve_track(_context(track_id=track_id, title="Other Song"))

        assert changed is not None
        assert changed.track.provider_track_id == "456"
        assert client.resolve_track.call_count == 2
    finally:
        db.close()


def test_cached_resolver_does_not_persist_without_local_track_id(tmp_path: Path):
    db = initialize_database(str(tmp_path))
    try:
        client = Mock()
        client.resolve_track.return_value = _resolution()
        resolver = CachedTidalCatalogueResolver(client, db)

        assert resolver.resolve_track(_context(track_id=None)) is not None
        assert db.execute("SELECT COUNT(*) FROM remote_track_mapping").fetchone()[0] == 0
    finally:
        db.close()


def test_v7_database_migration_creates_remote_mapping_table():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.executescript(SCHEMA_V1_SQL)
        db.execute("DROP INDEX IF EXISTS idx_remote_track_mapping_provider_id")
        db.execute("DROP TABLE remote_track_mapping")
        db.execute("PRAGMA user_version=7")
        db.commit()

        upgrade_database_if_needed(db, 7)

        table = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='remote_track_mapping'"
        ).fetchone()
        assert table is not None
        columns = {row["name"] for row in db.execute("PRAGMA table_info(remote_track_mapping)")}
        assert {"track_id", "provider", "provider_track_id", "local_metadata_fingerprint"} <= columns
        assert int(db.execute("PRAGMA user_version").fetchone()[0]) == CURRENT_DB_VERSION
    finally:
        db.close()
