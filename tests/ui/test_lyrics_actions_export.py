from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from db.models import Config, Track
from ui.main_window_parts.lyrics_actions import export_track_sidecars


def _make_config() -> Config:
    return Config(
        skip_tracks_with_synced_lyrics=False,
        skip_tracks_with_plain_lyrics=False,
        download_lyrics_mode="prefer_synced",
        show_line_count=True,
        save_lyrics_sidecars=False,
        lyrics_sidecar_format="both",
        try_embed_lyrics=True,
        lyrics_embed_format="both",
        theme_mode="auto",
        ui_scale_percent=100,
        font_size_mode="normal",
        show_album_art=True,
        startup_view="remember_last",
        lrclib_instance="https://lrclib.net",
        lyrics_output_dir="",
        lyrics_file_pattern="{filename}",
        lyrics_lookup_subdir="",
        scan_excluded_paths="",
        scan_excluded_patterns="",
        reaction_delay_ms=0,
        playback_speed=1.0,
        playback_volume=0.7,
        last_library_route="",
    )


class _FakeView:
    def __init__(self) -> None:
        self.feedback: list[tuple[str, str]] = []

    def set_export_feedback(self, state: str, text: str) -> None:
        self.feedback.append((state, text))


class _FakeWindow:
    def __init__(self) -> None:
        self.app_state = SimpleNamespace(db=object())
        self.view = _FakeView()
        self.status_messages: list[str] = []

    def _all_lyrics_views(self):
        return [self.view]

    def _show_status_message(self, message: str, timeout_ms: int) -> None:
        self.status_messages.append(message)


class LyricsActionsExportTests(unittest.TestCase):
    def test_export_sidecars_disables_audio_embedding(self):
        window = _FakeWindow()
        track = Track(
            id=1,
            file_path=str(Path(r"C:\music\song.mp3")),
            file_name="song.mp3",
            title="Song",
            album_name="Album",
            album_artist_name="Artist",
            album_id=1,
            artist_name="Artist",
            artist_id=1,
            image_path=None,
            track_number=1,
            txt_lyrics="plain",
            lrc_lyrics="[00:00.00]synced",
            duration=180.0,
            instrumental=False,
        )

        captured_config: list[Config] = []

        with (
            patch("ui.main_window_parts.lyrics_actions.get_track_by_id", return_value=track),
            patch("ui.main_window_parts.lyrics_actions.get_config", return_value=_make_config()),
            patch("ui.main_window_parts.lyrics_actions.sync_track_outputs_with_result") as sync_mock,
            patch("ui.main_window_parts.lyrics_actions.notify_user"),
        ):
            sync_mock.side_effect = lambda _track, config: (
                captured_config.append(config),
                SimpleNamespace(sidecar_paths=(r"C:\lyrics\song.lrc",), sidecar_error=None, embed_error=None),
            )[1]

            export_track_sidecars(window, 1)

        self.assertEqual(len(captured_config), 1)
        self.assertTrue(captured_config[0].save_lyrics_sidecars)
        self.assertFalse(captured_config[0].try_embed_lyrics)
        self.assertIn(("success", "Exported"), window.view.feedback)


if __name__ == "__main__":
    unittest.main()
