from PySide6.QtWidgets import QGroupBox

from tests.widgets_navigation._shared import *
from ui.hotkeys import HOTKEY_SPECS


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

    def test_settings_dialog_uses_compact_scrollable_shortcuts_tab(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                dialog = MusicFoldersDialog(app_state)
                try:
                    self.assertTrue(dialog.shortcuts_scroll.widgetResizable())
                    global_box = next(box for box in dialog.findChildren(QGroupBox) if box.title() == "App Shortcuts")
                    global_shortcut_count = sum(1 for spec in HOTKEY_SPECS.values() if spec.group == "global")
                    self.assertLess(global_box.layout().rowCount(), global_shortcut_count)
                finally:
                    dialog.deleteLater()
            finally:
                app_state.db.close()

    def test_settings_dialog_splits_lyrics_settings_into_sub_tabs(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                dialog = MusicFoldersDialog(app_state)
                try:
                    labels = [dialog.lyrics_sections_tabs.tabText(index) for index in range(dialog.lyrics_sections_tabs.count())]
                    self.assertEqual(labels, ["Download", "Providers", "Files", "Embed", "Editor"])
                finally:
                    dialog.deleteLater()
            finally:
                app_state.db.close()

    def test_settings_dialog_uses_compact_library_scan_editors(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                dialog = MusicFoldersDialog(app_state)
                try:
                    self.assertLessEqual(dialog.excluded_paths_edit.maximumHeight(), 140)
                    self.assertLessEqual(dialog.excluded_patterns_edit.maximumHeight(), 140)
                    self.assertIn(dialog.scan_source_combo.currentData(), {"both", "embedded_only", "sidecar_only"})
                finally:
                    dialog.deleteLater()
            finally:
                app_state.db.close()

    def test_settings_dialog_loads_and_saves_scan_lyrics_source_mode(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                dialog = MusicFoldersDialog(app_state)
                dialog.scan_source_combo.setCurrentIndex(dialog.scan_source_combo.findData("sidecar_only"))
                dialog.save()

                reloaded = MusicFoldersDialog(app_state)
                try:
                    self.assertEqual(reloaded.scan_source_combo.currentData(), "sidecar_only")
                finally:
                    reloaded.deleteLater()
                    dialog.deleteLater()
            finally:
                app_state.db.close()

    def test_settings_dialog_loads_and_saves_logging_verbosity(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                dialog = MusicFoldersDialog(app_state)
                dialog.logging_verbosity_combo.setCurrentIndex(dialog.logging_verbosity_combo.findData("debug"))
                dialog.save()

                reloaded = MusicFoldersDialog(app_state)
                try:
                    self.assertEqual(reloaded.logging_verbosity_combo.currentData(), "debug")
                finally:
                    reloaded.deleteLater()
                    dialog.deleteLater()
            finally:
                app_state.db.close()

    def test_settings_dialog_loads_and_saves_ai_sync_preferences(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                dialog = MusicFoldersDialog(app_state)
                dialog.ai_device_combo.setCurrentIndex(dialog.ai_device_combo.findData("cpu"))
                dialog.ai_language_combo.setCurrentIndex(dialog.ai_language_combo.findData("ro"))
                dialog.ai_enable_fuzzy_chk.setChecked(False)
                dialog.ai_fuzzy_threshold_spin.setValue(72)

                dialog.save()

                reloaded = MusicFoldersDialog(app_state)
                try:
                    self.assertEqual(reloaded.ai_device_combo.currentData(), "cpu")
                    self.assertEqual(reloaded.ai_language_combo.currentData(), "ro")
                    self.assertFalse(reloaded.ai_enable_fuzzy_chk.isChecked())
                    self.assertEqual(reloaded.ai_fuzzy_threshold_spin.value(), 72)
                finally:
                    reloaded.deleteLater()
                    dialog.deleteLater()
            finally:
                app_state.db.close()

    def test_settings_dialog_loads_and_saves_lyrics_source_preferences(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                dialog = MusicFoldersDialog(app_state)
                try:
                    self.assertEqual(dialog.lyrics_source_list.count(), 2)
                    self.assertEqual(
                        [dialog.lyrics_source_list.item(i).data(Qt.UserRole) for i in range(2)],
                        ["lrclib", "tidal"],
                    )
                    dialog.lyrics_source_list.item(1).setCheckState(Qt.Checked)
                    dialog.lyrics_source_list.setCurrentRow(1)
                    dialog._move_lyrics_source(-1)
                    dialog.tidal_country_edit.setText("ro")
                    dialog.tidal_client_id_edit.setText("test-client-id")
                    dialog.tidal_redirect_uri_edit.setText("http://127.0.0.1:8765/callback")
                    dialog.save()
                finally:
                    dialog.deleteLater()

                reloaded = MusicFoldersDialog(app_state)
                try:
                    self.assertEqual(
                        [reloaded.lyrics_source_list.item(i).data(Qt.UserRole) for i in range(2)],
                        ["tidal", "lrclib"],
                    )
                    self.assertEqual(reloaded.lyrics_source_list.item(0).checkState(), Qt.Checked)
                    self.assertEqual(reloaded.tidal_country_edit.text(), "RO")
                    self.assertEqual(reloaded.tidal_client_id_edit.text(), "test-client-id")
                    self.assertEqual(
                        reloaded.tidal_redirect_uri_edit.text(),
                        "http://127.0.0.1:8765/callback",
                    )
                finally:
                    reloaded.deleteLater()
            finally:
                app_state.db.close()

    def test_settings_dialog_uses_provider_settings_selector(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                dialog = MusicFoldersDialog(app_state)
                try:
                    self.assertLessEqual(dialog.size().height(), 700)
                    self.assertEqual(
                        [dialog.provider_settings_combo.itemData(i) for i in range(2)],
                        ["lrclib", "tidal"],
                    )
                    self.assertEqual(dialog.provider_settings_stack.currentIndex(), 0)
                    dialog.provider_settings_combo.setCurrentIndex(1)
                    self.assertEqual(dialog.provider_settings_stack.currentIndex(), 1)
                    self.assertFalse(dialog.tidal_client_id_edit.isHidden())
                finally:
                    dialog.deleteLater()
            finally:
                app_state.db.close()
