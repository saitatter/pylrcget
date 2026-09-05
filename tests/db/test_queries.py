from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from core.models import FsTrack
from db.database import add_tracks, get_album_rows, initialize_database
from db.queries import (
    clear_download_history,
    clear_publish_history,
    clear_track_dirty_lyrics,
    find_artist,
    get_config,
    get_download_history_rows,
    get_publish_history_rows,
    get_similar_lyrics_track_rows,
    get_track_by_id,
    get_track_scan_state_index,
    get_track_list_rows,
    get_track_rows,
    record_download_history,
    record_download_history_batch,
    record_publish_history,
    refresh_track_from_file,
    set_config,
    update_track_dirty_lyrics,
    update_track_plain_lyrics,
    upsert_track_scan_state,
)
from library.scan_state import TrackScanState
from tests import test_support as _test_support  # noqa: F401
from tests.test_support import make_fs_track, touch_text


class ArtistAlbumQueryTests(unittest.TestCase):
    def test_track_scan_state_round_trips_without_overloading_track_lyrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "song.mp3"
                touch_text(audio, "audio")
                add_tracks(db, [make_fs_track(audio, artist="Artist", album="Album", title="Song")])
                track_id = int(db.execute("SELECT id FROM tracks LIMIT 1").fetchone()["id"])
                state = TrackScanState(
                    track_id=track_id,
                    audio_mtime_ns=123,
                    audio_size=456,
                    sidecar_signature="sidecar-v1",
                    embedded_txt_present=True,
                    embedded_lrc_present=False,
                    sidecar_txt_present=False,
                    sidecar_lrc_present=True,
                    embedded_txt_lyrics="embedded plain",
                    embedded_lrc_lyrics=None,
                    last_scan_at=789.0,
                )

                upsert_track_scan_state(db, state)

                self.assertEqual(get_track_scan_state_index(db), {track_id: state})
                track = get_track_by_id(db, track_id)
                self.assertIsNone(track.txt_lyrics)
                self.assertIsNone(track.lrc_lyrics)
            finally:
                db.close()

    def test_get_album_rows_filters_by_track_artist_not_album_artist_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio_a = Path(tmp) / "artist_a.mp3"
                audio_b = Path(tmp) / "artist_b.mp3"
                touch_text(audio_a, "a")
                touch_text(audio_b, "b")

                add_tracks(
                    db,
                    [
                        make_fs_track(audio_a, artist="Artist A", album="Album Shared", title="Song A"),
                        make_fs_track(audio_b, artist="Artist B", album="Album Other", title="Song B"),
                    ],
                )

                artist_a_id = find_artist(db, "Artist A")
                rows = get_album_rows(db, artist_id=artist_a_id)
                album_names = [row["album_name"] for row in rows]
                self.assertEqual(album_names, ["Album Shared"])
            finally:
                db.close()

    def test_get_track_rows_includes_and_sorts_track_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                first = Path(tmp) / "first.mp3"
                second = Path(tmp) / "second.mp3"
                unknown = Path(tmp) / "unknown.mp3"
                touch_text(first, "a")
                touch_text(second, "b")
                touch_text(unknown, "c")
                add_tracks(
                    db,
                    [
                        replace(make_fs_track(first, artist="Artist", album="Album", title="First"), track_number=2),
                        replace(make_fs_track(second, artist="Artist", album="Album", title="Second"), track_number=1),
                        replace(make_fs_track(unknown, artist="Artist", album="Album", title="Unknown"), track_number=None),
                    ],
                )

                rows = get_track_rows(
                    db,
                    search_query="",
                    synced_lyrics_tracks=True,
                    plain_lyrics_tracks=True,
                    instrumental_tracks=True,
                    no_lyrics_tracks=True,
                    sort_column=0,
                    sort_order="asc",
                )

                self.assertEqual([row["title"] for row in rows], ["Second", "First", "Unknown"])
                self.assertEqual([row["track_number"] for row in rows], [1, 2, None])
            finally:
                db.close()

    def test_get_track_list_rows_exposes_lightweight_lyrics_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "song.mp3"
                touch_text(audio, "a")
                add_tracks(
                    db,
                    [
                        replace(
                            make_fs_track(audio, artist="Artist", album="Album", title="Song"),
                            txt_lyrics="plain lyrics",
                            lrc_lyrics=None,
                        )
                    ],
                )

                rows = get_track_list_rows(
                    db,
                    search_query="",
                    synced_lyrics_tracks=True,
                    plain_lyrics_tracks=True,
                    instrumental_tracks=True,
                    no_lyrics_tracks=True,
                    sort_column=0,
                    sort_order="asc",
                )

                self.assertEqual(len(rows), 1)
                self.assertTrue(bool(rows[0]["has_txt_lyrics"]))
                self.assertFalse(bool(rows[0]["has_lrc_lyrics"]))
                self.assertFalse(bool(rows[0]["has_instrumental_marker"]))
            finally:
                db.close()

    def test_get_album_rows_prefers_album_artist_name_for_artist_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "album_artist.mp3"
                touch_text(audio, "a")
                add_tracks(
                    db,
                    [make_fs_track(audio, artist="Track Artist", album="Known Album", title="Song A")],
                )

                rows = get_album_rows(db)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["artist_name"], "Track Artist")
            finally:
                db.close()

    def test_get_album_rows_supports_limit_offset_and_sorting(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                tracks = [
                    ("c.mp3", "Artist C", "Gamma", "Song 1"),
                    ("a.mp3", "Artist A", "Alpha", "Song 2"),
                    ("b.mp3", "Artist B", "Beta", "Song 3"),
                ]
                fs_tracks = []
                for filename, artist, album, title in tracks:
                    path = Path(tmp) / filename
                    touch_text(path, filename)
                    fs_tracks.append(make_fs_track(path, artist=artist, album=album, title=title))
                add_tracks(db, fs_tracks)

                rows = get_album_rows(db, limit=2, offset=1, sort_column=0, sort_order="asc")
                self.assertEqual([row["album_name"] for row in rows], ["Beta", "Gamma"])
            finally:
                db.close()


class PublishHistoryQueryTests(unittest.TestCase):
    def test_record_publish_history_persists_and_sorts_latest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "song.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist A", album="Album A", title="Song A")])

                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                first_id = record_publish_history(
                    db,
                    track_id=int(track["id"]),
                    title="Song A",
                    artist_name="Artist A",
                    album_name="Album A",
                    publish_kind="plain",
                    lrclib_instance="https://lrclib.net/api",
                )
                second_id = record_publish_history(
                    db,
                    track_id=int(track["id"]),
                    title="Song A",
                    artist_name="Artist A",
                    album_name="Album A",
                    publish_kind="synced",
                    lrclib_instance="https://lrclib.net/api",
                )

                rows = get_publish_history_rows(db)
                self.assertEqual(len(rows), 2)
                self.assertEqual(int(rows[0]["id"]), second_id)
                self.assertEqual(rows[0]["publish_kind"], "synced")
                self.assertEqual(rows[0]["publish_status"], "Published")
                self.assertEqual(int(rows[0]["track_exists"]), 1)
                self.assertEqual(int(rows[1]["id"]), first_id)
            finally:
                db.close()

    def test_clear_publish_history_removes_local_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                record_publish_history(
                    db,
                    track_id=None,
                    title="Song A",
                    artist_name="Artist A",
                    album_name="Album A",
                    publish_kind="plain",
                    lrclib_instance="https://lrclib.net/api",
                )

                self.assertEqual(len(get_publish_history_rows(db)), 1)
                clear_publish_history(db)
                self.assertEqual(get_publish_history_rows(db), [])
            finally:
                db.close()


class DownloadHistoryQueryTests(unittest.TestCase):
    def test_record_download_history_persists_and_sorts_latest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "song.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist A", album="Album A", title="Song A")])

                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                first_id = record_download_history(
                    db,
                    track_id=int(track["id"]),
                    title="Song A",
                    artist_name="Artist A",
                    album_name="Album A",
                    download_mode="prefer_synced",
                    download_status="plain",
                    message="Downloaded plain lyrics.",
                    lrclib_instance="https://lrclib.net/api",
                )
                second_id = record_download_history(
                    db,
                    track_id=int(track["id"]),
                    title="Song A",
                    artist_name="Artist A",
                    album_name="Album A",
                    download_mode="synced_only",
                    download_status="synced",
                    message="Downloaded synced lyrics.",
                    lrclib_instance="https://lrclib.net/api",
                )

                rows = get_download_history_rows(db)
                self.assertEqual(len(rows), 2)
                self.assertEqual(int(rows[0]["id"]), second_id)
                self.assertEqual(rows[0]["download_status"], "synced")
                self.assertEqual(rows[0]["download_mode"], "synced_only")
                self.assertEqual(int(rows[0]["track_exists"]), 1)
                self.assertEqual(int(rows[1]["id"]), first_id)
            finally:
                db.close()

    def test_clear_download_history_removes_local_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                record_download_history(
                    db,
                    track_id=None,
                    title="Song A",
                    artist_name="Artist A",
                    album_name="Album A",
                    download_mode="prefer_synced",
                    download_status="plain",
                    message="Downloaded plain lyrics.",
                    lrclib_instance="https://lrclib.net/api",
                )

                self.assertEqual(len(get_download_history_rows(db)), 1)
                clear_download_history(db)
                self.assertEqual(get_download_history_rows(db), [])
            finally:
                db.close()

    def test_record_download_history_batch_persists_multiple_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "song.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist A", album="Album A", title="Song A")])
                track = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track)

                record_download_history_batch(
                    db,
                    [
                        {
                            "track_id": int(track["id"]),
                            "title": "Song A",
                            "artist_name": "Artist A",
                            "album_name": "Album A",
                            "download_mode": "prefer_synced",
                            "download_status": "plain",
                            "message": "Downloaded plain lyrics.",
                            "lrclib_instance": "https://lrclib.net/api",
                            "downloaded_at": "2026-04-12 10:00:00 UTC",
                        },
                        {
                            "track_id": int(track["id"]),
                            "title": "Song A",
                            "artist_name": "Artist A",
                            "album_name": "Album A",
                            "download_mode": "synced_only",
                            "download_status": "synced",
                            "message": "Downloaded synced lyrics.",
                            "lrclib_instance": "https://lrclib.net/api",
                            "downloaded_at": "2026-04-12 10:00:01 UTC",
                        },
                    ],
                )

                rows = get_download_history_rows(db)
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[0]["download_status"], "synced")
                self.assertEqual(rows[1]["download_status"], "plain")
            finally:
                db.close()


class TrackRefreshQueryTests(unittest.TestCase):
    def test_config_round_trip_persists_appearance_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                config = get_config(db)
                updated = config.__class__(
                    skip_tracks_with_synced_lyrics=config.skip_tracks_with_synced_lyrics,
                    skip_tracks_with_plain_lyrics=config.skip_tracks_with_plain_lyrics,
                    download_lyrics_mode=config.download_lyrics_mode,
                    show_line_count=config.show_line_count,
                    save_lyrics_sidecars=config.save_lyrics_sidecars,
                    lyrics_sidecar_format="synced_only",
                    try_embed_lyrics=config.try_embed_lyrics,
                    lyrics_embed_format="plain_only",
                    theme_mode=config.theme_mode,
                    ui_scale_percent=125,
                    font_size_mode="large",
                    show_album_art=False,
                    startup_view="albums",
                    lrclib_instance=config.lrclib_instance,
                    lyrics_output_dir=config.lyrics_output_dir,
                    lyrics_file_pattern="",
                    lyrics_lookup_subdir=config.lyrics_lookup_subdir,
                    scan_excluded_paths=config.scan_excluded_paths,
                    scan_excluded_patterns=config.scan_excluded_patterns,
                    reaction_delay_ms=config.reaction_delay_ms,
                    playback_speed=config.playback_speed,
                    playback_volume=config.playback_volume,
                    last_library_route=config.last_library_route,
                    hotkey_bindings_json='{"snap":{"enabled":true,"key":"Tab"}}',
                    ui_state_json='{"tab_index":2}',
                )

                set_config(db, updated)
                reloaded = get_config(db)

                self.assertEqual(reloaded.ui_scale_percent, 125)
                self.assertEqual(reloaded.font_size_mode, "large")
                self.assertFalse(reloaded.show_album_art)
                self.assertEqual(reloaded.startup_view, "albums")
                self.assertEqual(reloaded.lyrics_sidecar_format, "synced_only")
                self.assertEqual(reloaded.lyrics_embed_format, "plain_only")
                self.assertEqual(reloaded.lyrics_file_pattern, "")
                self.assertEqual(reloaded.hotkey_bindings_json, '{"snap":{"enabled":true,"key":"Tab"}}')
                self.assertEqual(reloaded.ui_state_json, '{"tab_index":2}')
            finally:
                db.close()

    def test_refresh_track_from_file_updates_existing_track_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "song.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist A", album="Album A", title="Song A")])

                track_row = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track_row)
                track_id = int(track_row["id"])

                refreshed_fs = FsTrack(
                    file_path=str(audio),
                    file_name=audio.name,
                    title="Song A (Updated)",
                    album="Album A",
                    artist="Artist A",
                    album_artist="Artist A",
                    duration=181.0,
                    txt_lyrics="Fresh plain lyrics",
                    lrc_lyrics="[00:00.00]Fresh synced lyrics",
                    track_number=2,
                    modified_time=123.0,
                    file_size=456,
                )

                with patch("db.queries.scan_library.new_fs_track_from_path", return_value=refreshed_fs):
                    refreshed = refresh_track_from_file(db, track_id)

                self.assertIsNotNone(refreshed)
                assert refreshed is not None
                self.assertEqual(refreshed.id, track_id)
                self.assertEqual(refreshed.title, "Song A (Updated)")
                self.assertEqual(refreshed.txt_lyrics, "Fresh plain lyrics")
                self.assertEqual(refreshed.lrc_lyrics, "[00:00.00]Fresh synced lyrics")
                stored = db.execute(
                    "SELECT title, txt_lyrics, lrc_lyrics, track_number FROM tracks WHERE id = ?",
                    (track_id,),
                ).fetchone()
                self.assertEqual(stored["title"], "Song A (Updated)")
                self.assertEqual(stored["txt_lyrics"], "Fresh plain lyrics")
                self.assertEqual(stored["lrc_lyrics"], "[00:00.00]Fresh synced lyrics")
                self.assertEqual(int(stored["track_number"]), 2)
            finally:
                db.close()

    def test_refresh_track_from_file_removes_missing_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "missing.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist A", album="Album A", title="Song A")])

                track_row = db.execute("SELECT id FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(track_row)
                track_id = int(track_row["id"])

                audio.unlink()
                refreshed = refresh_track_from_file(db, track_id)

                self.assertIsNone(refreshed)
                remaining = db.execute("SELECT COUNT(*) AS count FROM tracks").fetchone()
                self.assertEqual(int(remaining["count"]), 0)
            finally:
                db.close()

    def test_dirty_lyrics_can_be_saved_and_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                audio = Path(tmp) / "song.mp3"
                touch_text(audio, "a")
                add_tracks(db, [make_fs_track(audio, artist="Artist A", album="Album A", title="Song A")])

                track_id = int(db.execute("SELECT id FROM tracks LIMIT 1").fetchone()["id"])
                update_track_plain_lyrics(db, track_id, "saved plain")
                update_track_dirty_lyrics(db, track_id, "", "draft plain")
                dirty = get_track_by_id(db, track_id)

                self.assertTrue(dirty.dirty_lyrics_present)
                self.assertEqual(dirty.dirty_txt_lyrics, "draft plain")
                self.assertEqual(dirty.txt_lyrics, "saved plain")

                clear_track_dirty_lyrics(db, track_id)
                cleared = get_track_by_id(db, track_id)

                self.assertFalse(cleared.dirty_lyrics_present)
                self.assertIsNone(cleared.dirty_txt_lyrics)
                self.assertEqual(cleared.txt_lyrics, "saved plain")
            finally:
                db.close()

    def test_similar_lyrics_tracks_rank_album_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            try:
                source_audio = Path(tmp) / "album.flac"
                single_audio = Path(tmp) / "single.flac"
                similar_title_audio = Path(tmp) / "similar-title.flac"
                other_artist_audio = Path(tmp) / "other-artist.flac"
                touch_text(source_audio, "a")
                touch_text(single_audio, "b")
                touch_text(similar_title_audio, "c")
                touch_text(other_artist_audio, "d")

                add_tracks(
                    db,
                    [
                        replace(make_fs_track(source_audio, artist="Artist A", album="Album", title="Song"), duration=180.0),
                        replace(make_fs_track(single_audio, artist="Artist A", album="Single", title="Song"), duration=181.0),
                        replace(
                            make_fs_track(
                                similar_title_audio,
                                artist="Artist A",
                                album="Other",
                                title="Song - Acoustic Version",
                            ),
                            duration=180.0,
                        ),
                        replace(
                            make_fs_track(other_artist_audio, artist="Other", album="Other", title="Song"),
                            duration=180.0,
                        ),
                    ],
                )

                source_id = int(
                    db.execute(
                        "SELECT tracks.id FROM tracks JOIN albums ON tracks.album_id = albums.id WHERE albums.name = ?",
                        ("Album",),
                    ).fetchone()["id"]
                )

                matches = get_similar_lyrics_track_rows(db, source_id)

                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["track"].album_name, "Single")
                self.assertGreaterEqual(matches[0]["score"], 95)
            finally:
                db.close()
