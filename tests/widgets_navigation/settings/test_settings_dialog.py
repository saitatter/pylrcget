from tests.widgets_navigation._shared import *


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class SettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_settings_dialog_loads_and_saves_custom_hotkeys(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                dialog = MusicFoldersDialog(app_state)
                dialog.shortcut_enabled_checks["play_pause"].setChecked(False)
                dialog.shortcut_edits["snap"].setKeySequence(QKeySequence("Tab"))
                dialog.shortcut_edits["shift_selected"].setKeySequence(QKeySequence("Alt+S"))
                dialog.shortcut_edits["shift_all_from_first"].setKeySequence(QKeySequence("Ctrl+Alt+A"))

                dialog.save()

                reloaded = MusicFoldersDialog(app_state)
                try:
                    self.assertFalse(reloaded.shortcut_enabled_checks["play_pause"].isChecked())
                    self.assertEqual(reloaded.shortcut_edits["snap"].keySequence().toString(), "Tab")
                    self.assertEqual(reloaded.shortcut_edits["shift_selected"].keySequence().toString(), "Alt+S")
                    self.assertEqual(reloaded.shortcut_edits["shift_all_from_first"].keySequence().toString(), "Ctrl+Alt+A")
                finally:
                    reloaded.deleteLater()
                    dialog.deleteLater()
            finally:
                app_state.db.close()

    def test_settings_dialog_has_dedicated_ai_sync_tab(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                dialog = MusicFoldersDialog(app_state)
                try:
                    tab_labels = [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())]
                    self.assertIn("AI Sync", tab_labels)
                    self.assertGreater(tab_labels.index("AI Sync"), tab_labels.index("Lyrics"))
                finally:
                    dialog.deleteLater()
            finally:
                app_state.db.close()

    def test_settings_dialog_loads_and_saves_ai_sync_preferences(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                dialog = MusicFoldersDialog(app_state)
                dialog.ai_whisper_model_combo.setCurrentIndex(dialog.ai_whisper_model_combo.findData("small"))
                dialog.ai_device_combo.setCurrentIndex(dialog.ai_device_combo.findData("cpu"))
                dialog.ai_use_demucs_chk.setChecked(False)

                dialog.save()

                reloaded = MusicFoldersDialog(app_state)
                try:
                    self.assertEqual(reloaded.ai_whisper_model_combo.currentData(), "small")
                    self.assertEqual(reloaded.ai_device_combo.currentData(), "cpu")
                    self.assertFalse(reloaded.ai_use_demucs_chk.isChecked())
                finally:
                    reloaded.deleteLater()
                    dialog.deleteLater()
            finally:
                app_state.db.close()