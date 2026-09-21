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

    def test_settings_dialog_shows_verified_ai_runtime_status(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                with (
                    patch(
                        "ui.workers.ai.ai_runtime.resolve_ai_runtime_python",
                        return_value=Path("C:/ai-runtime/Scripts/python.exe"),
                    ),
                    patch(
                        "ui.workers.ai.ai_runtime.default_ai_runtime_dir",
                        return_value=Path("C:/ai-runtime"),
                    ),
                    patch(
                        "ui.workers.ai.ai_sync_runtime._cuda_runtime_available",
                        return_value=True,
                    ),
                    patch(
                        "ui.workers.ai.ai_sync_runtime.get_missing_ai_dependencies",
                        return_value=["demucs"],
                    ),
                    patch(
                        "ui.workers.ai.ai_sync_lyrics_aligner.is_available",
                        return_value=True,
                    ),
                ):
                    dialog = MusicFoldersDialog(app_state)
                    try:
                        dialog.ai_device_combo.setCurrentIndex(dialog.ai_device_combo.findData("auto"))
                        self.assertEqual(dialog.ai_runtime_status_labels["runtime"].text(), "Ready · optional Demucs missing")
                        self.assertEqual(dialog.ai_runtime_status_labels["device"].text(), "Auto → NVIDIA CUDA")
                        self.assertEqual(dialog.ai_runtime_status_labels["english"].text(), "Ready")
                        self.assertEqual(dialog.ai_runtime_status_labels["multilingual"].text(), "Ready")
                        self.assertEqual(dialog.ai_runtime_status_labels["fallback"].text(), "WhisperX fallback ready")
                        self.assertEqual(dialog.ai_runtime_status_labels["runtime"].property("statusTone"), "warning")
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
                    self.assertTrue(dialog.tabs.documentMode())
                    self.assertFalse(dialog.tabs.tabBar().drawBase())
                    self.assertTrue(dialog.lyrics_sections_tabs.documentMode())
                    self.assertFalse(dialog.lyrics_sections_tabs.tabBar().drawBase())
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
                        ["lrclib", "musixmatch"],
                    )
                    dialog.lyrics_source_list.item(1).setCheckState(Qt.Checked)
                    dialog.lyrics_source_list.setCurrentRow(1)
                    dialog._move_lyrics_source(-1)
                    dialog.musixmatch_mode_combo.setCurrentIndex(
                        dialog.musixmatch_mode_combo.findData("official")
                    )
                    dialog.musixmatch_api_key_edit.setText("test-api-key")
                    dialog.save()
                finally:
                    dialog.deleteLater()

                reloaded = MusicFoldersDialog(app_state)
                try:
                    self.assertEqual(
                        [reloaded.lyrics_source_list.item(i).data(Qt.UserRole) for i in range(2)],
                        ["musixmatch", "lrclib"],
                    )
                    self.assertEqual(reloaded.lyrics_source_list.item(0).checkState(), Qt.Checked)
                    self.assertEqual(reloaded.musixmatch_mode_combo.currentData(), "official")
                    self.assertEqual(reloaded.musixmatch_api_key_edit.text(), "test-api-key")
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
                        ["lrclib", "musixmatch"],
                    )
                    self.assertEqual(dialog.provider_settings_stack.currentIndex(), 0)
                    dialog.provider_settings_combo.setCurrentIndex(1)
                    self.assertEqual(dialog.provider_settings_stack.currentIndex(), 1)
                    self.assertFalse(dialog.musixmatch_api_key_edit.isHidden())
                    self.assertFalse(dialog.musixmatch_api_key_edit.isReadOnly())
                finally:
                    dialog.deleteLater()
            finally:
                app_state.db.close()
