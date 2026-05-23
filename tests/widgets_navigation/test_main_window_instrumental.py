from tests.widgets_navigation._shared import *

@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class MainWindowInstrumentalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_mark_instrumental_refreshes_active_album_track_list(self):
        window = MainWindow.__new__(MainWindow)
        album_track_list = SimpleNamespace(restore_selection=MagicMock())
        album_stack = SimpleNamespace(currentWidget=lambda: album_track_list)

        window.tracks_tab = object()
        window.albums_page = object()
        window.artists_page = object()
        window.tabs = SimpleNamespace(currentWidget=lambda: window.albums_page)
        window.track_list = SimpleNamespace()
        window.albums_tab = SimpleNamespace(
            stack=album_stack,
            track_list=album_track_list,
        )
        window.artists_tab = SimpleNamespace(
            stack=SimpleNamespace(currentWidget=lambda: object()),
            album_browser=SimpleNamespace(),
        )
        window.app_state = SimpleNamespace(db=object())
        window._confirm_bulk = MagicMock(return_value=True)
        window._show_status_message = MagicMock()
        window._refresh_visible_library_view_after_downloads = MagicMock()
        window._publish_instrumental_to_lrclib = MagicMock()
        window.top_bar = SimpleNamespace(filter_values=lambda: {"instrumental": False})

        with patch("ui.main_window.mark_tracks_instrumental") as mark_tracks:
            MainWindow._on_mark_instrumental(window, [1, 2, None])

        mark_tracks.assert_called_once_with(window.app_state.db, [1, 2])
        window._refresh_visible_library_view_after_downloads.assert_called_once_with()
        album_track_list.restore_selection.assert_called_once_with({1, 2})
        window._show_status_message.assert_called_once_with(
            "Marked 2 track(s) as instrumental. Enable the Instrumental filter to show them.",
            5000,
        )
        window._publish_instrumental_to_lrclib.assert_called_once_with([1, 2])

    def test_apply_track_filters_updates_embedded_album_and_artist_track_lists(self):
        window = MainWindow.__new__(MainWindow)
        main_track_list = SimpleNamespace(
            setSearchValue=MagicMock(),
            setFilters=MagicMock(),
            set_now_playing=MagicMock(),
        )
        album_track_list = SimpleNamespace(
            setSearchValue=MagicMock(),
            setFilters=MagicMock(),
            set_now_playing=MagicMock(),
        )
        artist_track_list = SimpleNamespace(
            setSearchValue=MagicMock(),
            setFilters=MagicMock(),
            set_now_playing=MagicMock(),
        )
        window.track_list = main_track_list
        window.albums_tab = SimpleNamespace(track_list=album_track_list)
        window.artists_tab = SimpleNamespace(album_browser=SimpleNamespace(track_list=artist_track_list))
        window.top_bar = SimpleNamespace(
            search_text=lambda: "downfall",
            filter_values=lambda: {
                "synced": True,
                "plain": True,
                "instrumental": True,
                "none": True,
                "unsaved": False,
            },
        )
        window.app_state = SimpleNamespace(player=None)
        window._update_search_feedback = MagicMock()

        MainWindow._apply_track_filters(window)

        for track_list in (main_track_list, album_track_list, artist_track_list):
            track_list.setSearchValue.assert_called_once_with("downfall")
            track_list.setFilters.assert_called_once_with(
                synced=True,
                plain=True,
                instrumental=True,
                none_=True,
                unsaved=False,
            )
            track_list.set_now_playing.assert_not_called()
        window._update_search_feedback.assert_called_once_with()

    def test_selected_track_ids_for_toolbar_uses_active_track_list(self):
        window = MainWindow.__new__(MainWindow)
        active_track_list = SimpleNamespace(selected_track_ids=lambda: [5, 7])
        window.track_list = SimpleNamespace()
        window._active_track_list_widget = MagicMock(return_value=active_track_list)

        self.assertEqual(MainWindow._selected_track_ids_for_toolbar(window), [5, 7])

    def test_update_selection_actions_bar_shows_only_active_bar(self):
        window = MainWindow.__new__(MainWindow)
        active_track_list = SimpleNamespace()
        inactive_track_list_a = SimpleNamespace()
        inactive_track_list_b = SimpleNamespace()

        active_bar = SimpleNamespace(setVisible=MagicMock())
        inactive_bar_a = SimpleNamespace(setVisible=MagicMock())
        inactive_bar_b = SimpleNamespace(setVisible=MagicMock())
        active_label = SimpleNamespace(setText=MagicMock())
        inactive_label_a = SimpleNamespace(setText=MagicMock())
        inactive_label_b = SimpleNamespace(setText=MagicMock())
        active_button = SimpleNamespace(setEnabled=MagicMock())
        inactive_button_a = SimpleNamespace(setEnabled=MagicMock())
        inactive_button_b = SimpleNamespace(setEnabled=MagicMock())

        window.selection_actions_bar = active_bar
        window.selection_actions_label = active_label
        window.selection_action_buttons = [active_button]
        window.albums_selection_actions_bar = inactive_bar_a
        window.albums_selection_actions_label = inactive_label_a
        window.albums_selection_action_buttons = [inactive_button_a]
        window.artists_selection_actions_bar = inactive_bar_b
        window.artists_selection_actions_label = inactive_label_b
        window.artists_selection_action_buttons = [inactive_button_b]
        window.track_list = active_track_list
        window.albums_tab = SimpleNamespace(track_list=inactive_track_list_a)
        window.artists_tab = SimpleNamespace(album_browser=SimpleNamespace(track_list=inactive_track_list_b))
        window._active_track_list_widget = MagicMock(return_value=active_track_list)
        window._selected_track_ids_for_toolbar = MagicMock(return_value=[11, 12])

        MainWindow._update_selection_actions_bar(window)

        active_bar.setVisible.assert_called_once_with(True)
        inactive_bar_a.setVisible.assert_called_once_with(False)
        inactive_bar_b.setVisible.assert_called_once_with(False)
        active_label.setText.assert_called_once_with("Selected tracks: 2")
        active_button.setEnabled.assert_called_once_with(True)
        inactive_label_a.setText.assert_not_called()
        inactive_label_b.setText.assert_not_called()
        inactive_button_a.setEnabled.assert_not_called()
        inactive_button_b.setEnabled.assert_not_called()

    def test_create_selection_actions_bar_has_fixed_vertical_size(self):
        window = MainWindow.__new__(MainWindow)

        bar, _label, _buttons = MainWindow._create_selection_actions_bar(window)

        try:
            self.assertEqual(bar.sizePolicy().verticalPolicy(), QSizePolicy.Policy.Fixed)
            self.assertEqual(bar.maximumHeight(), 44)
        finally:
            bar.deleteLater()

    def test_save_window_state_persists_filter_checkboxes(self):
        window = MainWindow.__new__(MainWindow)
        saved_payload = {}
        window._persist_window_state_payload = lambda payload: saved_payload.update(payload)
        window.saveGeometry = MagicMock(return_value=QByteArray(b"geo"))
        window.tabs = SimpleNamespace(currentIndex=lambda: 2)
        window.top_bar = SimpleNamespace(
            search_text=lambda: "chapter ii",
            filter_values=lambda: {
                "synced": False,
                "plain": True,
                "instrumental": True,
                "none": False,
                "unsaved": True,
            }
        )

        MainWindow._save_window_state(window)

        self.assertEqual(saved_payload["search_text"], "chapter ii")
        self.assertEqual(saved_payload["filters"]["synced"], False)
        self.assertEqual(saved_payload["filters"]["plain"], True)
        self.assertEqual(saved_payload["filters"]["instrumental"], True)
        self.assertEqual(saved_payload["filters"]["none"], False)
        self.assertEqual(saved_payload["filters"]["unsaved"], True)
        self.assertEqual(saved_payload["tab_index"], 2)
        self.assertTrue(isinstance(saved_payload["geometry"], str) and saved_payload["geometry"])

    def test_restore_window_state_restores_filter_checkboxes(self):
        window = MainWindow.__new__(MainWindow)
        window._load_window_state_payload = MagicMock(
            return_value={
                "search_text": "downfall",
                "filters": {
                    "synced": False,
                    "plain": True,
                    "instrumental": True,
                    "none": False,
                    "unsaved": True,
                },
            }
        )
        window.top_bar = SimpleNamespace(
            default_filter_values=lambda: {
                "synced": True,
                "plain": True,
                "instrumental": False,
                "none": True,
                "unsaved": False,
            },
            set_search_text=MagicMock(),
            set_filter_values=MagicMock(),
        )
        window._apply_track_filters = MagicMock()
        window.tabs = SimpleNamespace(count=lambda: 5, setCurrentIndex=MagicMock())

        MainWindow._restore_window_state(window)

        window.top_bar.set_search_text.assert_called_once_with("downfall")
        window.top_bar.set_filter_values.assert_called_once_with(
            {
                "synced": False,
                "plain": True,
                "instrumental": True,
                "none": False,
                "unsaved": True,
            }
        )
        window._apply_track_filters.assert_called_once_with()

    def test_apply_hotkey_preferences_updates_lyrics_views_and_hints(self):
        window = MainWindow.__new__(MainWindow)
        lyrics_view = SimpleNamespace(
            btn_snap=object(),
            btn_shift_selected=object(),
            btn_shift_all_from_first=object(),
            set_hotkey_bindings=MagicMock(),
        )
        albums_view = SimpleNamespace(
            btn_snap=object(),
            btn_shift_selected=object(),
            btn_shift_all_from_first=object(),
            set_hotkey_bindings=MagicMock(),
        )
        artists_view = SimpleNamespace(
            btn_snap=object(),
            btn_shift_selected=object(),
            btn_shift_all_from_first=object(),
            set_hotkey_bindings=MagicMock(),
        )
        window.lyrics_view = lyrics_view
        window.albums_lyrics_view = albums_view
        window.artists_lyrics_view = artists_view
        window.hotkey_hints = SimpleNamespace(refresh_positions=MagicMock())
        window._apply_global_shortcuts = MagicMock()
        window._register_hotkey_hints = MagicMock()

        MainWindow._apply_hotkey_preferences(
            window,
            SimpleNamespace(
                hotkey_bindings_json=serialize_lyrics_hotkeys(
                    {
                        "snap": "Tab",
                        "shift_selected": "Alt+S",
                        "shift_all_from_first": "Ctrl+Alt+A",
                    }
                )
            ),
        )

        expected = {
            "snap": {"enabled": True, "key": "Tab"},
            "shift_selected": {"enabled": True, "key": "Alt+S"},
            "shift_all_from_first": {"enabled": True, "key": "Ctrl+Alt+A"},
        }
        lyrics_view.set_hotkey_bindings.assert_called_once_with(expected)
        albums_view.set_hotkey_bindings.assert_called_once_with(expected)
        artists_view.set_hotkey_bindings.assert_called_once_with(expected)
        window._apply_global_shortcuts.assert_called_once()
        window._register_hotkey_hints.assert_called_once()
        registered_bindings = window._register_hotkey_hints.call_args.args[0]
        self.assertEqual(registered_bindings["snap"], expected["snap"])
        self.assertEqual(registered_bindings["shift_selected"], expected["shift_selected"])
        self.assertEqual(registered_bindings["shift_all_from_first"], expected["shift_all_from_first"])
        window.hotkey_hints.refresh_positions.assert_called_once_with()

@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class SettingsDialogHotkeyTests(unittest.TestCase):
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
