from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from core.models import FsTrack
from db.database import (
    add_artist,
    add_tracks,
    get_config,
    get_library_file_index,
    initialize_database,
    set_config,
)
from library.scan_library import (
    AudioMetadata,
    MutagenError,
    SidecarLookupCache,
    get_audio_signature,
    get_audio_file_signature,
    get_sidecar_scan_state,
    iter_audio_paths,
    iter_audio_paths_with_audio_signatures,
    iter_audio_paths_with_signatures,
    new_fs_track_from_path,
    preview_audio_path_exclusions,
    read_audio_metadata_from_audio,
    read_lyrics_for_scan,
)
from tests import test_support as _test_support  # noqa: F401
from tests.test_support import make_fs_track, touch_text
from ui.workers.library_scanner import LibraryScanner, _ScanTimingStats, _scan_worker_count


class ScanLibraryHelpersTests(unittest.TestCase):
    def test_wav_metadata_uses_id3_tags(self):
        class _FakeWave:
            def get(self, key):
                return {
                    "TIT2": ["Track"],
                    "TALB": ["Album"],
                    "TPE1": ["Artist"],
                    "TPE2": ["Album Artist"],
                    "TRCK": ["02/10"],
                }.get(key)

        metadata = read_audio_metadata_from_audio(_FakeWave(), "song.wav")

        self.assertEqual(metadata.title, "Track")
        self.assertEqual(metadata.album, "Album")
        self.assertEqual(metadata.artist, "Artist")
        self.assertEqual(metadata.album_artist, "Album Artist")
        self.assertEqual(metadata.track_number, 2)

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
            combined_state = get_sidecar_scan_state(
                str(audio),
                audio_signature=(audio.stat().st_mtime, audio.stat().st_size),
            )
            self.assertEqual(combined_state.file_signature, sig)

    def test_audio_signature_is_independent_from_sidecar_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "track.mp3"
            lrc = root / "track.lrc"
            touch_text(audio, "audio")

            before = get_audio_signature(str(audio))
            touch_text(lrc, "[00:01.00]first")
            after_add = get_audio_signature(str(audio))
            touch_text(lrc, "[00:02.00]second")
            after_change = get_audio_signature(str(audio))

            self.assertEqual(before, after_add)
            self.assertEqual(after_add, after_change)
            self.assertEqual(before, (audio.stat().st_mtime_ns, audio.stat().st_size))

    def test_sidecar_scan_state_changes_for_add_change_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "track.mp3"
            lrc = root / "track.lrc"
            touch_text(audio, "audio")

            no_sidecar = get_sidecar_scan_state(str(audio))
            touch_text(lrc, "[00:01.00]first")
            added = get_sidecar_scan_state(str(audio))
            touch_text(lrc, "[00:02.00]second")
            changed = get_sidecar_scan_state(str(audio))
            lrc.unlink()
            removed = get_sidecar_scan_state(str(audio))

            self.assertFalse(no_sidecar.lrc_present)
            self.assertTrue(added.lrc_present)
            self.assertTrue(changed.lrc_present)
            self.assertFalse(removed.lrc_present)
            self.assertNotEqual(no_sidecar.signature, added.signature)
            self.assertNotEqual(added.signature, changed.signature)
            self.assertNotEqual(changed.signature, removed.signature)

    def test_iter_audio_paths_with_audio_signatures_uses_nanoseconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "track.mp3"
            touch_text(audio, "audio")

            paths, signatures = iter_audio_paths_with_audio_signatures([str(root)])

            self.assertEqual(paths, [str(audio)])
            self.assertEqual(signatures[str(audio)], (audio.stat().st_mtime_ns, audio.stat().st_size))

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

    def test_new_fs_track_from_path_reuses_sidecar_directory_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "track.mp3"
            sidecar = root / "track.txt"
            unrelated_audio = root / "other.flac"
            touch_text(audio, "audio")
            touch_text(sidecar, "plain sidecar")
            touch_text(unrelated_audio, "audio")

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

            cache = SidecarLookupCache()
            with (
                patch("library.scan_library.MutagenFile", return_value=_FakeAudio()),
                patch("library.scan_library.read_embedded_lyrics", return_value=(None, None)),
                patch("library.scan_library.os.scandir", wraps=os.scandir) as scandir_mock,
            ):
                first = new_fs_track_from_path(str(audio), sidecar_lookup_cache=cache)
                second = new_fs_track_from_path(str(audio), sidecar_lookup_cache=cache)

            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertEqual(scandir_mock.call_count, 1)
            index = cache._dir_entries[cache._dir_key(str(root))]
            self.assertNotIn("other.flac", index.by_lower_name)

    def test_read_lyrics_for_scan_can_skip_independent_sidecar_content_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "track.mp3"
            touch_text(audio, "audio")
            touch_text(root / "track.txt", "plain sidecar")
            touch_text(root / "track.lrc", "[00:01.00]synced sidecar")

            result = read_lyrics_for_scan(
                str(audio),
                scan_lyrics_source_mode="sidecar_only",
                read_sidecar_txt=False,
                read_sidecar_lrc=True,
                sidecar_lookup_cache=SidecarLookupCache(),
            )

            self.assertIsNone(result.sidecar_txt)
            self.assertEqual(result.sidecar_lrc, "[00:01.00]synced sidecar")

    def test_new_fs_track_from_path_passes_scan_mode_to_signature_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "track.mp3"
            touch_text(audio, "audio")

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
                "library.scan_library.get_audio_file_signature_with_lookup",
                return_value=(123.0, 456),
            ) as signature_mock, patch(
                "library.scan_library.read_embedded_lyrics",
                return_value=(None, None),
            ), patch(
                "library.scan_library._read_sidecar",
                return_value=(None, None),
            ):
                track = new_fs_track_from_path(
                    str(audio),
                    scan_lyrics_source_mode="embedded_only",
                )

            self.assertIsNotNone(track)
            self.assertEqual(signature_mock.call_args.kwargs["scan_lyrics_source_mode"], "embedded_only")

    def test_new_fs_track_from_path_uses_audio_signature_when_signature_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "track.mp3"
            touch_text(audio, "audio")

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

            audio_signature = (123.0, 456)
            with patch("library.scan_library.MutagenFile", return_value=_FakeAudio()), patch(
                "library.scan_library.get_audio_file_signature_with_lookup",
                return_value=audio_signature,
            ) as signature_mock, patch(
                "library.scan_library.read_embedded_lyrics",
                return_value=(None, None),
            ):
                track = new_fs_track_from_path(
                    str(audio),
                    audio_signature=audio_signature,
                )

            self.assertIsNotNone(track)
            assert track is not None
            self.assertEqual(track.modified_time, audio_signature[0])
            self.assertEqual(track.file_size, audio_signature[1])
            self.assertEqual(signature_mock.call_args.kwargs["audio_signature"], audio_signature)

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

    def test_new_fs_track_from_path_respects_scan_lyrics_source_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "track.mp3"
            touch_text(audio, "audio")
            touch_text(root / "track.txt", "plain sidecar")

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

            with patch("library.scan_library.MutagenFile", return_value=_FakeAudio()) as _file_mock, patch(
                "library.scan_library.read_embedded_lyrics",
                return_value=("embedded plain", "[00:03.00]embedded synced"),
            ) as embedded_mock:
                track = new_fs_track_from_path(str(audio), scan_lyrics_source_mode="sidecar_only")

            self.assertIsNotNone(track)
            assert track is not None
            self.assertIsNone(track.lrc_lyrics)
            self.assertEqual(track.txt_lyrics, "plain sidecar")
            embedded_mock.assert_not_called()

            with patch("library.scan_library.MutagenFile", return_value=_FakeAudio()), patch(
                "library.scan_library.read_embedded_lyrics",
                return_value=("embedded plain", "[00:03.00]embedded synced"),
            ) as embedded_mock:
                track = new_fs_track_from_path(str(audio), scan_lyrics_source_mode="embedded_only")

            self.assertIsNotNone(track)
            assert track is not None
            self.assertEqual(track.txt_lyrics, "embedded plain")
            self.assertEqual(track.lrc_lyrics, "[00:03.00]embedded synced")
            embedded_mock.assert_called_once()
            with patch("library.scan_library.MutagenFile", return_value=_FakeAudio()), patch(
                "library.scan_library.read_embedded_lyrics",
                return_value=("embedded plain", "[00:03.00]embedded synced"),
            ), patch("library.scan_library._read_sidecar") as sidecar_mock:
                track = new_fs_track_from_path(str(audio), scan_lyrics_source_mode="embedded_only")

            self.assertIsNotNone(track)
            sidecar_mock.assert_not_called()


class LibraryScannerIncrementalTests(unittest.TestCase):
    def test_scan_timing_stats_accumulate_worker_local_buckets(self):
        timings = _ScanTimingStats()

        def record_worker_metrics() -> None:
            for _ in range(100):
                timings.record("metadata_read_s", 0.001)
                timings.record("metadata_read_count", 1)
                timings.record("signature_sidecar_candidate_count", 3)

        workers = [threading.Thread(target=record_worker_metrics) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        timings.merge()

        self.assertAlmostEqual(timings.metadata_read_s, 0.4)
        self.assertEqual(timings.metadata_read_count, 400)
        self.assertEqual(timings.signature_sidecar_candidate_count, 1200)

    def _scan_sidecar_mutation(
        self,
        *,
        operation: str,
        suffix: str = ".lrc",
        lyrics_lookup_subdir: str = "",
        lyrics_file_pattern: str = "",
        seed_sidecar: bool = False,
    ) -> tuple[sqlite3.Row, int]:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "pylrcget.db.sqlite3")
            music_dir = Path(tmp) / "Music"
            music_dir.mkdir(parents=True, exist_ok=True)
            audio = music_dir / "track.mp3"
            touch_text(audio, "audio")

            metadata = AudioMetadata(
                title="Song",
                album="Album",
                artist="Artist",
                album_artist="Artist",
                track_number=1,
                duration=180.0,
            )
            sidecar_dir = music_dir / lyrics_lookup_subdir if lyrics_lookup_subdir else music_dir
            sidecar_dir.mkdir(parents=True, exist_ok=True)
            sidecar_stem = "Artist - Song" if lyrics_file_pattern else audio.stem
            sidecar = sidecar_dir / f"{sidecar_stem}{suffix}"
            if seed_sidecar:
                touch_text(sidecar, "original sidecar")

            signature = get_audio_file_signature(
                str(audio),
                lyrics_lookup_subdir,
                metadata=metadata,
                lyrics_file_pattern=lyrics_file_pattern,
            )
            db = initialize_database(tmp)
            add_tracks(
                db,
                [
                    FsTrack(
                        file_path=str(audio),
                        file_name=audio.name,
                        title=metadata.title,
                        album=metadata.album,
                        artist=metadata.artist,
                        album_artist=metadata.album_artist,
                        duration=metadata.duration,
                        txt_lyrics="original sidecar" if seed_sidecar and suffix == ".txt" else None,
                        lrc_lyrics="original sidecar" if seed_sidecar and suffix == ".lrc" else None,
                        track_number=metadata.track_number,
                        modified_time=signature[0],
                        file_size=signature[1],
                    )
                ],
            )
            db.close()

            if operation == "add":
                touch_text(sidecar, "new sidecar")
            elif operation == "remove":
                sidecar.unlink()
            elif operation == "change":
                touch_text(sidecar, "changed sidecar")
            elif operation == "rename":
                sidecar.replace(sidecar_dir / f"renamed{suffix}")
            else:
                raise AssertionError(f"Unknown sidecar operation: {operation}")

            metadata_calls = 0

            def fake_read_metadata(path: str):
                nonlocal metadata_calls
                metadata_calls += 1
                return object(), metadata

            def fake_new_fs_track(path: str, *, signature=None, **_kwargs):
                current = sidecar.read_text(encoding="utf-8") if sidecar.exists() else None
                return FsTrack(
                    file_path=path,
                    file_name=audio.name,
                    title=metadata.title,
                    album=metadata.album,
                    artist=metadata.artist,
                    album_artist=metadata.album_artist,
                    duration=metadata.duration,
                    txt_lyrics=current if suffix == ".txt" else None,
                    lrc_lyrics=current if suffix == ".lrc" else None,
                    track_number=metadata.track_number,
                    modified_time=signature[0] if signature else None,
                    file_size=signature[1] if signature else None,
                )

            scanner = LibraryScanner(
                db_path,
                [str(music_dir)],
                lyrics_lookup_subdir=lyrics_lookup_subdir,
                lyrics_file_pattern=lyrics_file_pattern,
            )
            with (
                patch("ui.workers.library_scanner.read_audio_metadata_for_scan", side_effect=fake_read_metadata),
                patch("ui.workers.library_scanner.new_fs_track_from_path", side_effect=fake_new_fs_track),
            ):
                scanner.run()

            db = sqlite3.connect(db_path)
            db.row_factory = sqlite3.Row
            try:
                row = db.execute("SELECT txt_lyrics, lrc_lyrics FROM tracks LIMIT 1").fetchone()
                assert row is not None
                return row, metadata_calls
            finally:
                db.close()

    def test_new_lrc_beside_unchanged_audio_is_detected(self):
        row, _metadata_calls = self._scan_sidecar_mutation(operation="add", suffix=".lrc")
        self.assertEqual(row["lrc_lyrics"], "new sidecar")

    def test_new_txt_beside_unchanged_audio_is_detected(self):
        row, _metadata_calls = self._scan_sidecar_mutation(operation="add", suffix=".txt")
        self.assertEqual(row["txt_lyrics"], "new sidecar")

    def test_removed_lrc_beside_unchanged_audio_is_detected(self):
        row, metadata_calls = self._scan_sidecar_mutation(
            operation="remove",
            suffix=".lrc",
            seed_sidecar=True,
        )
        self.assertIsNone(row["lrc_lyrics"])
        self.assertEqual(metadata_calls, 1)

    def test_removed_txt_beside_unchanged_audio_is_detected(self):
        row, metadata_calls = self._scan_sidecar_mutation(
            operation="remove",
            suffix=".txt",
            seed_sidecar=True,
        )
        self.assertIsNone(row["txt_lyrics"])
        self.assertEqual(metadata_calls, 1)

    def test_changed_sidecar_beside_unchanged_audio_is_detected(self):
        row, metadata_calls = self._scan_sidecar_mutation(
            operation="change",
            suffix=".lrc",
            seed_sidecar=True,
        )
        self.assertEqual(row["lrc_lyrics"], "changed sidecar")
        self.assertEqual(metadata_calls, 1)

    def test_renamed_sidecar_beside_unchanged_audio_is_removed_from_effective_lyrics(self):
        row, metadata_calls = self._scan_sidecar_mutation(
            operation="rename",
            suffix=".lrc",
            seed_sidecar=True,
        )
        self.assertIsNone(row["lrc_lyrics"])
        self.assertEqual(metadata_calls, 1)

    def test_new_sidecar_in_configured_lookup_subdirectory_is_detected(self):
        row, _metadata_calls = self._scan_sidecar_mutation(
            operation="add",
            suffix=".lrc",
            lyrics_lookup_subdir="lyrics",
        )
        self.assertEqual(row["lrc_lyrics"], "new sidecar")

    def test_new_sidecar_using_custom_pattern_is_detected(self):
        row, _metadata_calls = self._scan_sidecar_mutation(
            operation="add",
            suffix=".lrc",
            lyrics_file_pattern="{artist} - {title}",
        )
        self.assertEqual(row["lrc_lyrics"], "new sidecar")

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
            seen_track_kwargs: list[dict] = []

            class RecordingExecutor(RealThreadPoolExecutor):
                def __init__(self, *args, max_workers=None, **kwargs):
                    created_workers.append(int(max_workers or 0))
                    super().__init__(*args, max_workers=max_workers, **kwargs)

            def fake_new_fs_track(path: str, *, signature=None, **kwargs):
                seen_track_kwargs.append(kwargs)
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
                patch("ui.workers.library_scanner.read_audio_metadata_for_scan", return_value=(object(), fake_metadata)) as read_metadata,
                patch("ui.workers.library_scanner.get_audio_file_signature") as signature_mock,
                patch("ui.workers.library_scanner.new_fs_track_from_path", side_effect=fake_new_fs_track),
            ):
                expected_workers = _scan_worker_count()
                signature_mock.side_effect = lambda path, lyrics_lookup_subdir=None, **kwargs: (
                    first.stat().st_mtime if Path(path).name == "first.mp3" else second.stat().st_mtime,
                    first.stat().st_size if Path(path).name == "first.mp3" else second.stat().st_size,
                )
                scanner.run()

            self.assertEqual(created_workers, [expected_workers])
            self.assertEqual(read_metadata.call_count, 2)
            self.assertEqual(signature_mock.call_count, 0)
            self.assertEqual(len(seen_track_kwargs), 2)
            for kwargs in seen_track_kwargs:
                self.assertIsNotNone(kwargs["audio_signature"])
                self.assertIsNotNone(kwargs["sidecar_lookup_cache"])

    def test_library_scanner_prefers_scan_mode_from_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            config = get_config(db)
            set_config(db, replace(config, scan_lyrics_source_mode="embedded_only"))
            db_path = str(Path(tmp) / "pylrcget.db.sqlite3")
            db.close()

            music_dir = Path(tmp) / "Music"
            music_dir.mkdir(parents=True, exist_ok=True)
            track_path = music_dir / "mode.mp3"
            touch_text(track_path, "mode")

            fake_metadata = AudioMetadata(
                title="Mode",
                album="Album",
                artist="Artist",
                album_artist="Artist",
                track_number=None,
                duration=120.0,
            )
            seen_modes: list[str | None] = []

            def fake_signature(path: str, lyrics_lookup_subdir: str | None = None, **kwargs):
                seen_modes.append(kwargs.get("scan_lyrics_source_mode"))
                return (track_path.stat().st_mtime, track_path.stat().st_size)

            def fake_new_fs_track(path: str, *, scan_lyrics_source_mode=None, signature=None, **_kwargs):
                seen_modes.append(scan_lyrics_source_mode)
                return FsTrack(
                    file_path=path,
                    file_name=Path(path).name,
                    title="Mode",
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

            scanner = LibraryScanner(db_path, [str(music_dir)], scan_lyrics_source_mode="both")
            with (
                patch("ui.workers.library_scanner.read_audio_metadata_for_scan", return_value=(object(), fake_metadata)),
                patch("ui.workers.library_scanner.get_audio_file_signature", side_effect=fake_signature),
                patch("ui.workers.library_scanner.new_fs_track_from_path", side_effect=fake_new_fs_track),
            ):
                scanner.run()

            self.assertEqual(seen_modes, ["embedded_only"])

    def test_sidecar_only_change_reuses_stored_metadata_without_audio_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            db_path = str(Path(tmp) / "pylrcget.db.sqlite3")
            music_dir = Path(tmp) / "Music"
            music_dir.mkdir(parents=True, exist_ok=True)
            audio = music_dir / "track.mp3"
            sidecar = music_dir / "track.lrc"
            touch_text(audio, "audio")

            metadata = AudioMetadata(
                title="Track",
                album="Album",
                artist="Artist",
                album_artist="Artist",
                track_number=1,
                duration=180.0,
            )
            db.close()
            scanner = LibraryScanner(db_path, [str(music_dir)], scan_worker_count=1)
            first_track = FsTrack(
                file_path=str(audio),
                file_name=audio.name,
                title=metadata.title,
                album=metadata.album,
                artist=metadata.artist,
                album_artist=metadata.album_artist,
                duration=metadata.duration,
                txt_lyrics=None,
                lrc_lyrics=None,
                track_number=metadata.track_number,
                modified_time=audio.stat().st_mtime,
                file_size=audio.stat().st_size,
            )
            with (
                patch("ui.workers.library_scanner.read_audio_metadata_for_scan", return_value=(object(), metadata)),
                patch("ui.workers.library_scanner.new_fs_track_from_path", return_value=first_track),
            ):
                scanner.run()

            touch_text(sidecar, "[00:01.00]sidecar lyrics")
            second_metadata_read = patch(
                "ui.workers.library_scanner.read_audio_metadata_for_scan",
                side_effect=AssertionError("sidecar-only refresh must not parse audio"),
            )
            second_new_track = patch(
                "ui.workers.library_scanner.new_fs_track_from_path",
                side_effect=AssertionError("sidecar-only refresh must not build an audio track"),
            )
            with second_metadata_read, second_new_track:
                LibraryScanner(db_path, [str(music_dir)], scan_worker_count=1).run()

            db = sqlite3.connect(db_path)
            db.row_factory = sqlite3.Row
            try:
                row = db.execute("SELECT lrc_lyrics FROM tracks LIMIT 1").fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["lrc_lyrics"], "[00:01.00]sidecar lyrics")
            finally:
                db.close()

    def test_missing_sidecar_candidate_alias_does_not_reindex_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = initialize_database(tmp)
            db_path = str(Path(tmp) / "pylrcget.db.sqlite3")
            music_dir = Path(tmp) / "Music"
            music_dir.mkdir(parents=True, exist_ok=True)
            audio = music_dir / "track.mp3"
            touch_text(audio, "audio")

            # The normalized artist key collides, so the DB keeps a display name
            # different from the original audio metadata used for scan state.
            add_artist(db, "Maenpaa")
            db.close()

            metadata = AudioMetadata(
                title="Song",
                album="Album",
                artist="Mäenpää",
                album_artist="Mäenpää",
                track_number=1,
                duration=180.0,
            )

            def fake_new_fs_track(path: str, *, signature=None, **_kwargs):
                return FsTrack(
                    file_path=path,
                    file_name=audio.name,
                    title=metadata.title,
                    album=metadata.album,
                    artist=metadata.artist,
                    album_artist=metadata.album_artist,
                    duration=metadata.duration,
                    txt_lyrics=None,
                    lrc_lyrics=None,
                    track_number=metadata.track_number,
                    modified_time=signature[0] if signature else None,
                    file_size=signature[1] if signature else None,
                )

            with (
                patch("ui.workers.library_scanner.read_audio_metadata_for_scan", return_value=(object(), metadata)),
                patch("ui.workers.library_scanner.new_fs_track_from_path", side_effect=fake_new_fs_track),
            ):
                LibraryScanner(db_path, [str(music_dir)], scan_worker_count=1).run()

            with (
                patch(
                    "ui.workers.library_scanner.read_audio_metadata_for_scan",
                    side_effect=AssertionError("unchanged audio must not be reparsed"),
                ),
                patch(
                    "ui.workers.library_scanner.read_lyrics_for_scan",
                    side_effect=AssertionError("missing sidecar aliases must not refresh lyrics"),
                ),
            ):
                LibraryScanner(db_path, [str(music_dir)], scan_worker_count=1).run()

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
                patch("ui.workers.library_scanner.read_audio_metadata_for_scan", return_value=(object(), fake_metadata)) as read_metadata,
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
            with (
                self.assertLogs("ui.workers.library_scanner", level="DEBUG") as logs,
                patch(
                    "ui.workers.library_scanner.read_audio_metadata_for_scan",
                    return_value=(object(), fake_metadata),
                ),
                patch("ui.workers.library_scanner.new_fs_track_from_path", side_effect=fake_new_fs_track),
            ):
                scanner.run()

            joined = "\n".join(logs.output)
            self.assertIn("Library scan summary:", joined)
            self.assertIn("Library scan timing totals are cumulative worker time", joined)
            self.assertIn("Library scan cumulative worker time:", joined)
            self.assertIn("Library scan path discovery cumulative worker time:", joined)
            self.assertIn("Library scan audio-only fast path cumulative worker time:", joined)
            self.assertIn("Library scan signature check cumulative worker time:", joined)
            self.assertIn("Library scan signature audio stat cumulative worker time:", joined)
            self.assertIn("Library scan signature sidecar stat cumulative worker time:", joined)
            self.assertIn("Library scan metadata read cumulative worker time:", joined)
            self.assertIn("Library scan embedded lyrics read cumulative worker time:", joined)
            self.assertIn("Library scan sidecar lookup cumulative worker time:", joined)
            self.assertIn("Library scan DB flush cumulative worker time:", joined)
            self.assertIn("Library scan average throughput:", joined)

    def test_first_audio_tag_text_decodes_bytes_and_handles_freeform_tags(self):
        from library.scan_library import read_audio_metadata_from_audio

        class FakeAudioTag:
            def __init__(self, val):
                self.value = val

        class FakeAudio:
            def __init__(self, tags_dict):
                self.tags = tags_dict

        # Test freeform MP4 tag with bytes
        audio_m4a = FakeAudio({"----:com.apple.iTunes:ALBUMARTIST": [b"Aviators"]})
        meta = read_audio_metadata_from_audio(audio_m4a, "track.m4a")
        self.assertEqual(meta.album_artist, "Aviators")

        # Test MP3 TXXX album artist tag
        audio_mp3 = FakeAudio({"TXXX:ALBUM ARTIST": FakeAudioTag("Aviators MP3")})
        meta_mp3 = read_audio_metadata_from_audio(audio_mp3, "track.mp3")
        self.assertEqual(meta_mp3.album_artist, "Aviators MP3")
