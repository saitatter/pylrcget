from types import SimpleNamespace

from PySide6.QtWidgets import QGroupBox

from tests.widgets_navigation._shared import *
from ui.dialogs.lyrics_cleanup_dialog import LyricsCleanupDialog


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class LyricsCleanupDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    @staticmethod
    def _track():
        return SimpleNamespace(
            id=1,
            file_path="C:/music/song.mp3",
            file_name="song.mp3",
            title="Song",
            album_name="Album",
            album_artist_name="Album Artist",
            artist_name="Artist",
            track_number=1,
        )

    @staticmethod
    def _config():
        return SimpleNamespace(
            lyrics_lookup_subdir="",
            lyrics_output_dir="",
            lyrics_file_pattern="",
        )

    def test_options_are_grouped_and_embedded_cleanup_is_selective(self):
        dialog = LyricsCleanupDialog([self._track()], self._config())
        try:
            group_titles = {group.title() for group in dialog.findChildren(QGroupBox)}
            self.assertEqual(
                group_titles,
                {"Library database", "Embedded audio", "External files"},
            )

            dialog.clear_txt.setChecked(False)
            dialog.clear_lrc.setChecked(False)
            dialog.discard_drafts.setChecked(False)
            dialog.clear_embedded_txt.setChecked(True)
            dialog.clear_embedded_lrc.setChecked(False)

            options = dialog.options()
            self.assertFalse(options.clear_library)
            self.assertTrue(options.clear_embedded_txt)
            self.assertFalse(options.clear_embedded_lrc)
            self.assertTrue(dialog.buttons.button(dialog.buttons.StandardButton.Ok).isEnabled())
            self.assertNotIn("Lyrics may return", dialog.warning.text())
        finally:
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
