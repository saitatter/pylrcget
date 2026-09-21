from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core.lyrics_sidecar import delete_lyrics_sidecars, existing_lyrics_sidecar_paths
from db.models import Config, Track
from ui.services.lyrics_cleanup_service import LyricsCleanupOptions, apply_file_cleanup


def make_config(**changes) -> Config:
    values = {
        "skip_tracks_with_synced_lyrics": False,
        "skip_tracks_with_plain_lyrics": False,
        "download_lyrics_mode": "prefer_synced",
        "show_line_count": True,
        "save_lyrics_sidecars": True,
        "lyrics_sidecar_format": "both",
        "try_embed_lyrics": True,
        "lyrics_embed_format": "both",
        "theme_mode": "system",
        "ui_scale_percent": 100,
        "font_size_mode": "normal",
        "show_album_art": True,
        "startup_view": "tracks",
        "lrclib_instance": "https://lrclib.net",
        "lyrics_output_dir": "",
        "lyrics_file_pattern": "{artist} - {title}",
        "lyrics_lookup_subdir": "lyrics",
        "scan_excluded_paths": "",
        "scan_excluded_patterns": "",
        "reaction_delay_ms": 300,
        "playback_speed": 1.0,
        "playback_volume": 1.0,
        "last_library_route": "tracks",
    }
    values.update(changes)
    return Config(**values)


def make_track(path: str) -> Track:
    return Track(
        id=1,
        file_path=path,
        file_name=Path(path).name,
        title="Song",
        album_name="Album",
        album_artist_name="Album Artist",
        album_id=1,
        artist_name="Artist",
        artist_id=1,
        image_path=None,
        track_number=2,
        txt_lyrics="plain",
        lrc_lyrics="[00:01.00] synced",
        duration=120.0,
        instrumental=False,
    )


class LyricsCleanupServiceTests(unittest.TestCase):
    def test_preview_finds_case_insensitive_candidates_in_lookup_subdir(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.mp3"
            audio.touch()
            sidecar_dir = root / "lyrics"
            sidecar_dir.mkdir()
            sidecar = sidecar_dir / "ARTIST - SONG.LRC"
            sidecar.write_text("[00:01.00] line", encoding="utf-8")

            paths = existing_lyrics_sidecar_paths(make_track(str(audio)), make_config())

            self.assertEqual(paths, (str(sidecar),))

    def test_delete_only_removes_matching_lyrics_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "song.mp3"
            audio.touch()
            matching = root / "Artist - Song.txt"
            unrelated = root / "notes.txt"
            matching.write_text("plain", encoding="utf-8")
            unrelated.write_text("keep", encoding="utf-8")

            deleted = delete_lyrics_sidecars(make_track(str(audio)), make_config(lyrics_lookup_subdir=""))

            self.assertEqual(deleted, (str(matching),))
            self.assertFalse(matching.exists())
            self.assertTrue(unrelated.exists())

    @patch("ui.services.lyrics_cleanup_service.clear_embedded_lyrics_for_track")
    def test_file_cleanup_can_remove_embedded_without_touching_database(self, clear_embedded):
        track = make_track("C:/music/song.mp3")

        result = apply_file_cleanup(
            track,
            make_config(),
            LyricsCleanupOptions(clear_library=False, clear_embedded=True),
        )

        self.assertIsNone(result.error)
        self.assertTrue(result.embedded_cleared)
        clear_embedded.assert_called_once_with(track)


if __name__ == "__main__":
    unittest.main()
