from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests import test_support as _test_support  # noqa: F401
from core.lyrics_sidecar import export_lyrics_sidecars
from db.models import Config, Track


def _make_config(output_dir: str, pattern: str) -> Config:
    return Config(
        skip_tracks_with_synced_lyrics=False,
        skip_tracks_with_plain_lyrics=False,
        download_lyrics_mode="prefer_synced",
        show_line_count=True,
        save_lyrics_sidecars=True,
        lyrics_sidecar_format="both",
        try_embed_lyrics=True,
        lyrics_embed_format="both",
        theme_mode="auto",
        ui_scale_percent=100,
        font_size_mode="normal",
        show_album_art=True,
        startup_view="remember_last",
        lrclib_instance="https://lrclib.net",
        lyrics_output_dir=output_dir,
        lyrics_file_pattern=pattern,
        lyrics_lookup_subdir="",
        scan_excluded_paths="",
        scan_excluded_patterns="",
        reaction_delay_ms=0,
        playback_speed=1.0,
        playback_volume=0.7,
        last_library_route="",
    )


def _make_track(audio_path: Path) -> Track:
    return Track(
        id=1,
        file_path=str(audio_path),
        file_name=audio_path.name,
        title="Take On Me",
        album_name="Hunting High and Low",
        album_artist_name="a-ha",
        album_id=1,
        artist_name="a-ha",
        artist_id=1,
        image_path=None,
        track_number=1,
        txt_lyrics="plain lyrics",
        lrc_lyrics="[00:00.00]synced lyrics",
        duration=180.0,
        instrumental=False,
    )


class LyricsSidecarExportTests(unittest.TestCase):
    def test_export_supports_filename_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio = tmp_path / "music" / "01. Take On Me.mp3"
            audio.parent.mkdir(parents=True, exist_ok=True)
            audio.write_text("audio")
            out_dir = tmp_path / "lyrics"
            config = _make_config(str(out_dir), "{filename}")
            track = _make_track(audio)

            written = export_lyrics_sidecars(track, config)
            expected_lrc = out_dir / "01. Take On Me.lrc"
            expected_txt = out_dir / "01. Take On Me.txt"

            self.assertEqual({str(expected_lrc), str(expected_txt)}, set(written))
            self.assertTrue(expected_lrc.exists())
            self.assertTrue(expected_txt.exists())

    def test_export_with_empty_pattern_defaults_to_audio_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio = tmp_path / "music" / "01. Take On Me.mp3"
            audio.parent.mkdir(parents=True, exist_ok=True)
            audio.write_text("audio")
            out_dir = tmp_path / "lyrics"
            config = _make_config(str(out_dir), "")
            track = _make_track(audio)

            written = export_lyrics_sidecars(track, config)
            expected_lrc = out_dir / "01. Take On Me.lrc"
            expected_txt = out_dir / "01. Take On Me.txt"

            self.assertEqual({str(expected_lrc), str(expected_txt)}, set(written))

    def test_export_falls_back_to_audio_filename_for_invalid_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio = tmp_path / "music" / "01. Take On Me.mp3"
            audio.parent.mkdir(parents=True, exist_ok=True)
            audio.write_text("audio")
            out_dir = tmp_path / "lyrics"
            config = _make_config(str(out_dir), "{filename}-{missing}")
            track = _make_track(audio)

            written = export_lyrics_sidecars(track, config)
            expected_lrc = out_dir / "01. Take On Me.lrc"
            expected_txt = out_dir / "01. Take On Me.txt"

            self.assertEqual({str(expected_lrc), str(expected_txt)}, set(written))

    def test_path_traversal_in_pattern_falls_back_to_safe_name(self):
        """A pattern that resolves outside the output dir must be rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio = tmp_path / "music" / "song.mp3"
            audio.parent.mkdir(parents=True, exist_ok=True)
            audio.write_text("audio")
            out_dir = tmp_path / "lyrics"
            config = _make_config(str(out_dir), "../../etc/{filename}")
            track = _make_track(audio)

            written = export_lyrics_sidecars(track, config)
            for path in written:
                self.assertTrue(
                    Path(path).resolve().is_relative_to(out_dir.resolve()),
                    f"Sidecar escaped output dir: {path}",
                )

    def test_dotdot_in_artist_name_sanitised(self):
        """Track metadata containing '..' must not cause path traversal."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio = tmp_path / "music" / "song.mp3"
            audio.parent.mkdir(parents=True, exist_ok=True)
            audio.write_text("audio")
            out_dir = tmp_path / "lyrics"
            config = _make_config(str(out_dir), "{artist}/{title}")
            track = _make_track(audio)
            track = Track(
                **{**track.__dict__, "artist_name": "../../../etc", "title": "passwd"},
            )

            written = export_lyrics_sidecars(track, config)
            for path in written:
                self.assertTrue(
                    Path(path).resolve().is_relative_to(out_dir.resolve()),
                    f"Sidecar escaped output dir: {path}",
                )

    def test_export_synced_only_writes_only_lrc(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio = tmp_path / "song.mp3"
            audio.write_text("audio")
            audio.with_suffix(".txt").write_text("old plain", encoding="utf-8")
            config = _make_config("", "{filename}")
            config = Config(**{**config.__dict__, "lyrics_sidecar_format": "synced_only"})
            track = _make_track(audio)

            written = export_lyrics_sidecars(track, config)

            self.assertEqual([str(audio.with_suffix(".lrc"))], written)
            self.assertTrue(audio.with_suffix(".lrc").exists())
            self.assertFalse(audio.with_suffix(".txt").exists())

    def test_export_plain_only_writes_only_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio = tmp_path / "song.mp3"
            audio.write_text("audio")
            audio.with_suffix(".lrc").write_text("[00:00.00]old synced", encoding="utf-8")
            config = _make_config("", "{filename}")
            config = Config(**{**config.__dict__, "lyrics_sidecar_format": "plain_only"})
            track = _make_track(audio)

            written = export_lyrics_sidecars(track, config)

            self.assertEqual([str(audio.with_suffix(".txt"))], written)
            self.assertFalse(audio.with_suffix(".lrc").exists())
            self.assertTrue(audio.with_suffix(".txt").exists())

    def test_export_prefer_synced_writes_only_lrc_when_synced_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio = tmp_path / "song.mp3"
            audio.write_text("audio")
            audio.with_suffix(".txt").write_text("old plain", encoding="utf-8")
            config = _make_config("", "{filename}")
            config = Config(**{**config.__dict__, "lyrics_sidecar_format": "prefer_synced"})
            track = _make_track(audio)

            written = export_lyrics_sidecars(track, config)

            self.assertEqual([str(audio.with_suffix(".lrc"))], written)
            self.assertTrue(audio.with_suffix(".lrc").exists())
            self.assertFalse(audio.with_suffix(".txt").exists())

    def test_export_prefer_synced_falls_back_to_only_txt_when_lrc_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audio = tmp_path / "song.mp3"
            audio.write_text("audio")
            audio.with_suffix(".lrc").write_text("[00:00.00]old synced", encoding="utf-8")
            config = _make_config("", "{filename}")
            config = Config(**{**config.__dict__, "lyrics_sidecar_format": "prefer_synced"})
            track = _make_track(audio)

            plain_track = Track(**{**track.__dict__, "lrc_lyrics": None})
            plain_written = export_lyrics_sidecars(plain_track, config)

            self.assertEqual([str(audio.with_suffix(".txt"))], plain_written)
            self.assertFalse(audio.with_suffix(".lrc").exists())
            self.assertTrue(audio.with_suffix(".txt").exists())


if __name__ == "__main__":
    unittest.main()
