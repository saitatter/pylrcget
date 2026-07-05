from __future__ import annotations

import sqlite3
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from tests import test_support as _test_support  # noqa: F401
from tests.test_support import make_fs_track, touch_text
from db.database import add_tracks, get_library_file_index, initialize_database
from library.scan_library import (
    AudioMetadata,
    MutagenError,
    SidecarLookupCache,
    get_audio_file_signature,
    iter_audio_paths,
    iter_audio_paths_with_signatures,
    new_fs_track_from_path,
    preview_audio_path_exclusions,
)
from ui.workers.library_scanner import LibraryScanner, _scan_worker_count
from core.models import FsTrack


class ScanLibraryHelpersTests(unittest.TestCase):
    def test_get_audio_file_signature_includes_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "track.mp3"
            txt = root / "track.txt"
            lrc = root / "track.lrc"

            touch_text(audio, "audio")
            time.sleep(0.02)
            touch_text(txt, "plain lyrics")
            time.sleep(0.02)
            touch_text(lrc, "[00:01.00]synced")

            sig = get_audio_file_signature(str(audio))
            self.assertIsNotNone(sig[0])
            self.assertEqual(sig[1], audio.stat().st_size + txt.stat().st_size + lrc.stat().st_size)
            self.assertEqual(sig[0], max(audio.stat().st_mtime, txt.stat().st_mtime, lrc.stat().st_mtime))

    def test_get_audio_file_signature_includes_lookup_subfolder_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "track.mp3"
            lyrics_dir = root / "lyrics"
            txt = lyrics_dir / "track.txt"
            lrc = lyrics_dir / "track.lrc"

            touch_text(audio, "audio")
            time.sleep(0.02)
            touch_text(txt, "plain lyrics")
            time.sleep(0.02)
            touch_text(lrc, "[00:01.00]synced")

            sig = get_audio_file_signature(str(audio), "lyrics")
            self.assertIsNotNone(sig[0])
            self.assertEqual(sig[1], audio.stat().st_size + txt.stat().st_size + lrc.stat().st_size)
            self.assertEqual(sig[0], max(audio.stat().st_mtime, txt.stat().st_mtime, lrc.stat().st_mtime))

    def test_get_audio_file_signature_includes_metadata_named_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "01-track.flac"
            lrc = root / "Artist - Song Title.lrc"
            metadata = AudioMetadata(
                title="Song Title",
                album="Album",
                artist="Artist",
                album_artist="Artist",
                track_number=1,
                duration=180.0,
            )

            touch_text(audio, "audio")
            time.sleep(0.02)
            touch_text(lrc, "[00:01.00]synced")

            sig = get_audio_file_signature(str(audio), metadata=metadata, lyrics_file_pattern="{artist} - {title}")
            self.assertIsNotNone(sig[0])
            self.assertEqual(sig[1], audio.stat().st_size + lrc.stat().st_size)
            self.assertEqual(sig[0], max(audio.stat().st_mtime, lrc.stat().st_mtime))

    def test_get_audio_file_signature_uses_sidecar_cache_to_skip_missing_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "track.mp3"
            touch_text(audio, "audio")
            audio_size = audio.stat().st_size
            audio_mtime = audio.stat().st_mtime

            with (
                patch("library.scan_library.os.listdir", return_value=[]),
                patch("library.scan_library.os.stat", wraps=os.stat) as stat_mock,
            ):
                sig = get_audio_file_signature(str(audio), sidecar_lookup_cache=SidecarLookupCache())

            self.assertEqual(stat_mock.call_count, 1)
            self.assertEqual(sig[1], audio_size)
            self.assertEqual(sig[0], audio_mtime)

    def test_get_audio_file_signature_uses_provided_audio_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "track.mp3"
            touch_text(audio, "audio")
            audio_signature = (audio.stat().st_mtime, audio.stat().st_size)

            with patch("library.scan_library.os.stat", wraps=os.stat) as stat_mock:
                sig = get_audio_file_signature(
                    str(audio),
                    audio_signature=audio_signature,
                    sidecar_lookup_cache=SidecarLookupCache(),
                )

            self.assertEqual(sig[0], audio_signature[0])
            self.assertEqual(sig[1], audio_signature[1])
            self.assertEqual(stat_mock.call_count, 0)

    def test_iter_audio_paths_and_preview_apply_path_and_regex_exclusions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            include_a = root / "Music" / "keep.mp3"
            include_b = root / "Music" / "sub" / "keep.flac"
            excluded_dir_file = root / "Podcasts" / "skip.mp3"
            excluded_regex_file = root / "Music" / "demo_track.mp3"
            non_audio = root / "Music" / "note.txt"

            for path in (include_a, include_b, excluded_dir_file, excluded_regex_file, non_audio):
                touch_text(path, "x")

            paths = iter_audio_paths(
                [str(root)],
                excluded_paths=str(root / "Podcasts"),
                excluded_patterns=r"demo",
            )
            self.assertEqual({Path(p).name for p in paths}, {"keep.mp3", "keep.flac"})

            included, excluded = preview_audio_path_exclusions(
                [str(root)],
                excluded_paths=str(root / "Podcasts"),
                excluded_patterns=r"demo",
            )
            self.assertEqual({Path(p).name for p in included}, {"keep.mp3", "keep.flac"})
            self.assertEqual({Path(p).name for p in excluded}, {"demo_track.mp3"})

    def test_iter_audio_paths_with_signatures_returns_audio_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "track.mp3"
            touch_text(audio, "audio")

            paths, signatures = iter_audio_paths_with_signatures([str(root)])

            self.assertEqual([str(audio)], paths)
            self.assertIn(str(audio), signatures)
            self.assertEqual(signatures[str(audio)][1], audio.stat().st_size)

    def test_new_fs_track_from_path_skips_corrupt_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "broken.mp3"
            touch_text(audio, "not really audio")

            with patch("library.scan_library.MutagenFile", side_effect=MutagenError("bad frame sync")):
                track = new_fs_track_from_path(str(audio))

            self.assertIsNone(track)

    def test_new_fs_track_from_path_prefers_embedded_then_sidecar_then_lookup_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "track.mp3"
            adjacent_txt = root / "track.txt"
            adjacent_lrc = root / "track.lrc"
            lookup_dir = root / "lyrics"
            lookup_txt = lookup_dir / "track.txt"
            lookup_lrc = lookup_dir / "track.lrc"
            touch_text(audio, "audio")
            touch_text(adjacent_txt, "adjacent plain")
            touch_text(adjacent_lrc, "[00:01.00]adjacent synced")
            touch_text(lookup_txt, "lookup plain")
            touch_text(lookup_lrc, "[00:02.00]lookup synced")

            class _FakeAudio:
                def __init__(self) -> None:
                    self.info = type("Info", (), {"length": 180.0})()

                def get(self, key):
                    mapping = {
                        "title": ["Track"],
                        "album": ["Album"],
                        "artist": ["Artist"],
                        "albumartist": ["Artist"],
                    }
                    return mapping.get(key)

            with patch("library.scan_library.MutagenFile", return_value=_FakeAudio()), patch(
                "library.scan_library.read_embedded_lyrics",
                return_value=("embedded plain", "[00:03.00]embedded synced"),
            ):
                track = new_fs_track_from_path(str(audio), lyrics_lookup_subdir="lyrics")

            self.assertIsNotNone(track)
            assert track is not None
            self.assertEqual(track.txt_lyrics, "embedded plain")
            self.assertEqual(track.lrc_lyrics, "[00:03.00]embedded synced")

            with patch("library.scan_library.MutagenFile", return_value=_FakeAudio()), patch(
                "library.scan_library.read_embedded_lyrics",
                return_value=(None, None),
            ):
                track_without_embedded = new_fs_track_from_path(str(audio), lyrics_lookup_subdir="lyrics")

            self.assertIsNotNone(track_without_embedded)
            assert track_without_embedded is not None
            self.assertEqual(track_without_embedded.txt_lyrics, "adjacent plain")
            self.assertEqual(track_without_embedded.lrc_lyrics, "[00:01.00]adjacent synced")

            adjacent_txt.unlink()
            adjacent_lrc.unlink()
            with patch("library.scan_library.MutagenFile", return_value=_FakeAudio()), patch(
                "library.scan_library.read_embedded_lyrics",
                return_value=(None, None),
            ):
                track_lookup_only = new_fs_track_from_path(str(audio), lyrics_lookup_subdir="lyrics")

            self.assertIsNotNone(track_lookup_only)
            assert track_lookup_only is not None
            self.assertEqual(track_lookup_only.txt_lyrics, "lookup plain")
            self.assertEqual(track_lookup_only.lrc_lyrics, "[00:02.00]lookup synced")

    def test_new_fs_track_from_path_reads_artist_title_lrc_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "01-track.flac"
            lrc = root / "Artist - Song Title.lrc"
            touch_text(audio, "audio")
            touch_text(lrc, "[00:01.00]synced")

            class _FakeAudio:
                def __init__(self) -> None:
                    self.info = type("Info", (), {"length": 180.0})()

                def get(self, key):
                    mapping = {
                        "title": ["Song Title"],
                        "album": ["Album"],
                        "artist": ["Artist"],
                        "albumartist": ["Artist"],
                        "tracknumber": ["01"],
                    }
                    return mapping.get(key)

            with patch("library.scan_library.MutagenFile", return_value=_FakeAudio()), patch(
                "library.scan_library.read_embedded_lyrics",
                return_value=(None, None),
            ):
                track = new_fs_track_from_path(
                    str(audio),
                    lyrics_file_pattern="{artist} - {title}",
                )

            self.assertIsNotNone(track)
            assert track is not None
            self.assertEqual(track.lrc_lyrics, "[00:01.00]synced")


class LibraryScannerIncrementalTests(unittest.TestCase):
    def test_library_scanner_uses_worker_pool_for_first_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            db_path = str(Path(tmp) / "pylrcget.db.sqlite3")
            db.close()

            music_dir = Path(tmp) / "Music"
            music_dir.mkdir(parents=True, exist_ok=True)
            first = music_dir / "first.mp3"
            second = music_dir / "second.mp3"
            touch_text(first, "first")
            touch_text(second, "second")

            created_workers: list[int] = []

            class RecordingExecutor(RealThreadPoolExecutor):
                def __init__(self, *args, max_workers=None, **kwargs):
                    created_workers.append(int(max_workers or 0))
                    super().__init__(*args, max_workers=max_workers, **kwargs)

            def fake_new_fs_track(path: str, *, signature=None, **_kwargs):
                name = Path(path).stem
                return FsTrack(
                    file_path=path,
                    file_name=Path(path).name,
                    title=name.title(),
                    album="Album",
                    artist="Artist",
                    album_artist="Artist",
                    duration=120.0,
                    txt_lyrics=None,
                    lrc_lyrics=None,
                    track_number=None,
                    modified_time=signature[0] if signature else None,
                    file_size=signature[1] if signature else None,
                )

            fake_metadata = AudioMetadata(
                title="Track",
                album="Album",
                artist="Artist",
                album_artist="Artist",
                track_number=None,
                duration=120.0,
            )
            scanner = LibraryScanner(db_path, [str(music_dir)])
            with (
                patch("ui.workers.library_scanner.os.cpu_count", return_value=8),
                patch("ui.workers.library_scanner.ThreadPoolExecutor", RecordingExecutor),
                patch("ui.workers.library_scanner.read_audio_metadata", return_value=(object(), fake_metadata)) as read_metadata,
                patch("ui.workers.library_scanner.new_fs_track_from_path", side_effect=fake_new_fs_track),
            ):
                expected_workers = _scan_worker_count()
                scanner.run()

            self.assertEqual(created_workers, [expected_workers])
            self.assertEqual(read_metadata.call_count, 2)

    def test_library_scanner_skips_unchanged_reindexes_new_and_removes_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            db_path = str(Path(tmp) / "pylrcget.db.sqlite3")
            music_dir = Path(tmp) / "Music"
            music_dir.mkdir(parents=True, exist_ok=True)

            unchanged = music_dir / "unchanged.mp3"
            removed = music_dir / "removed.mp3"
            added = music_dir / "added.mp3"
            touch_text(unchanged, "same")
            touch_text(removed, "gone later")

            add_tracks(
                db,
                [
                    make_fs_track(unchanged, artist="Artist 1", album="Album 1", title="Unchanged"),
                    make_fs_track(removed, artist="Artist 2", album="Album 2", title="Removed"),
                ],
            )
            db.close()

            removed.unlink()
            touch_text(added, "new file")

            calls: list[str] = []

            def fake_new_fs_track(path: str, *, signature=None, lyrics_lookup_subdir=None, **_kwargs):
                calls.append(Path(path).name)
                if Path(path).name == "added.mp3":
                    return FsTrack(
                        file_path=path,
                        file_name="added.mp3",
                        title="Added",
                        album="Album 3",
                        artist="Artist 3",
                        album_artist="Artist 3",
                        duration=210.0,
                        txt_lyrics=None,
                        lrc_lyrics=None,
                        track_number=1,
                        modified_time=signature[0] if signature else None,
                        file_size=signature[1] if signature else None,
                    )
                return None

            scanner = LibraryScanner(db_path, [str(music_dir)])
            fake_metadata = AudioMetadata(
                title="Added",
                album="Album 3",
                artist="Artist 3",
                album_artist="Artist 3",
                track_number=1,
                duration=210.0,
            )
            with (
                patch("ui.workers.library_scanner.read_audio_metadata", return_value=(object(), fake_metadata)) as read_metadata,
                patch("ui.workers.library_scanner.new_fs_track_from_path", side_effect=fake_new_fs_track),
            ):
                scanner.run()

            read_metadata.assert_called_once_with(str(added))

            db2 = sqlite3.connect(db_path)
            db2.row_factory = sqlite3.Row
            try:
                index = get_library_file_index(db2)
                names = {Path(path).name for path in index}
                self.assertEqual(names, {"unchanged.mp3", "added.mp3"})
                self.assertEqual(calls, ["added.mp3"])
            finally:
                db2.close()

    def test_library_scanner_logs_timing_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            db_path = str(Path(tmp) / "pylrcget.db.sqlite3")
            db.close()

            music_dir = Path(tmp) / "Music"
            music_dir.mkdir(parents=True, exist_ok=True)
            track_path = music_dir / "timed.mp3"
            touch_text(track_path, "timed")

            fake_metadata = AudioMetadata(
                title="Timed",
                album="Album",
                artist="Artist",
                album_artist="Artist",
                track_number=1,
                duration=180.0,
            )

            def fake_new_fs_track(path: str, *, signature=None, **_kwargs):
                return FsTrack(
                    file_path=path,
                    file_name=Path(path).name,
                    title="Timed",
                    album="Album",
                    artist="Artist",
                    album_artist="Artist",
                    duration=180.0,
                    txt_lyrics=None,
                    lrc_lyrics=None,
                    track_number=1,
                    modified_time=signature[0] if signature else None,
                    file_size=signature[1] if signature else None,
                )

            scanner = LibraryScanner(db_path, [str(music_dir)])
            with self.assertLogs("ui.workers.library_scanner", level="INFO") as logs:
                with (
                    patch("ui.workers.library_scanner.read_audio_metadata", return_value=(object(), fake_metadata)),
                    patch("ui.workers.library_scanner.new_fs_track_from_path", side_effect=fake_new_fs_track),
                ):
                    scanner.run()

            joined = "\n".join(logs.output)
            self.assertIn("Library scan summary:", joined)
            self.assertIn("Library scan path discovery time:", joined)
            self.assertIn("Library scan audio-only fast path time:", joined)
            self.assertIn("Library scan signature check time:", joined)
            self.assertIn("Library scan signature audio stat time:", joined)
            self.assertIn("Library scan signature sidecar stat time:", joined)
            self.assertIn("Library scan metadata read time:", joined)
            self.assertIn("Library scan embedded lyrics read time:", joined)
            self.assertIn("Library scan sidecar lookup time:", joined)
            self.assertIn("Library scan DB flush time:", joined)
            self.assertIn("Library scan average throughput:", joined)
