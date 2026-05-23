from tests.widgets_navigation._shared import *
from PySide6.QtWidgets import QToolButton


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

    def test_create_selection_actions_bar_uses_compact_action_set(self):
        window = MainWindow.__new__(MainWindow)

        bar, _label, buttons = MainWindow._create_selection_actions_bar(window)

        try:
            self.assertEqual([button.text() for button in buttons], ["Refresh", "Download v", "Export", "Instrumental v", "Publish v"])
            self.assertIsInstance(buttons[1], QToolButton)
            self.assertIsNotNone(buttons[1].menu())
            self.assertEqual([action.text() for action in buttons[1].menu().actions()], ["Use current mode", "Synced only", "Plain only"])
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

    def test_restore_window_state_falls_back_from_too_small_saved_geometry(self):
        class DummyWindow:
            def __init__(self):
                self._geometry = QRect(40, 50, 900, 600)
                self._load_window_state_payload = MagicMock(
                    return_value={
                        "geometry": bytes(QByteArray(b"restored").toBase64()).decode("ascii"),
                    }
                )
                self.top_bar = SimpleNamespace(
                    set_search_text=MagicMock(),
                    set_filter_values=MagicMock(),
                )
                self._apply_track_filters = MagicMock()
                self.tabs = SimpleNamespace(count=lambda: 5, setCurrentIndex=MagicMock())

            def geometry(self):
                return QRect(self._geometry)

            def setGeometry(self, rect):
                self._geometry = QRect(rect)

            def move(self, x, y):
                self._geometry.moveTo(x, y)

            def restoreGeometry(self, _payload):
                self._geometry = QRect(20, 30, 420, 320)
                return True

            def minimumWidth(self):
                return 0

            def minimumHeight(self):
                return 0

            def minimumSizeHint(self):
                return SimpleNamespace(width=lambda: 820, height=lambda: 560)

            def isMaximized(self):
                return False

            def isFullScreen(self):
                return False

            def screen(self):
                return None

        window = DummyWindow()

        with patch("ui.main_window_parts.preferences.QApplication.primaryScreen") as primary_screen:
            primary_screen.return_value = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1600, 900))

            MainWindow._restore_window_state(window)

        self.assertEqual(window.geometry(), QRect(40, 50, 900, 600))
        window.top_bar.set_search_text.assert_not_called()
        window.top_bar.set_filter_values.assert_not_called()
        window._apply_track_filters.assert_not_called()

    def test_restore_window_state_falls_back_from_narrow_compact_startup_geometry(self):
        class DummyWindow:
            def __init__(self):
                self._geometry = QRect(40, 50, 1200, 760)
                self._load_window_state_payload = MagicMock(
                    return_value={
                        "geometry": bytes(QByteArray(b"restored").toBase64()).decode("ascii"),
                    }
                )
                self.top_bar = SimpleNamespace(
                    set_search_text=MagicMock(),
                    set_filter_values=MagicMock(),
                )
                self._apply_track_filters = MagicMock()
                self.tabs = SimpleNamespace(count=lambda: 5, setCurrentIndex=MagicMock())

            def geometry(self):
                return QRect(self._geometry)

            def setGeometry(self, rect):
                self._geometry = QRect(rect)

            def move(self, x, y):
                self._geometry.moveTo(x, y)

            def restoreGeometry(self, _payload):
                self._geometry = QRect(20, 30, 930, 760)
                return True

            def minimumWidth(self):
                return 0

            def minimumHeight(self):
                return 0

            def minimumSizeHint(self):
                return SimpleNamespace(width=lambda: 820, height=lambda: 560)

            def isMaximized(self):
                return False

            def isFullScreen(self):
                return False

            def screen(self):
                return None

        window = DummyWindow()

        with patch("ui.main_window_parts.preferences.QApplication.primaryScreen") as primary_screen:
            primary_screen.return_value = SimpleNamespace(availableGeometry=lambda: QRect(0, 0, 1600, 900))

            MainWindow._restore_window_state(window)

        self.assertEqual(window.geometry(), QRect(40, 50, 1200, 760))

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

    def test_scan_progress_updates_overlay(self):
        window = MainWindow.__new__(MainWindow)
        overlay_calls: list[tuple[int, int, str, str]] = []
        window.scan_overlay = SimpleNamespace(
            update_progress=lambda current, total, label, status: overlay_calls.append((current, total, label, status))
        )
        window.progress_bar = SimpleNamespace(
            maximum=lambda: 100,
            setRange=lambda *_args: None,
            setValue=lambda *_args: None,
        )
        window.scan_label = SimpleNamespace(setText=lambda *_args: None)
        window.scan_details = SimpleNamespace(setText=lambda *_args: None)

        MainWindow._update_scan_progress(window, 3, 10, "C:/Music/Song.mp3", 1.25)

        self.assertEqual(overlay_calls[-1][0:3], (3, 10, "Song.mp3"))
        self.assertIn("30%", overlay_calls[-1][3])

    def test_status_message_uses_toast_area_without_changing_layout(self):
        window = MainWindow.__new__(MainWindow)
        window.central_widget = QWidget()
        window.central_widget.resize(480, 320)
        window.central_widget.show()
        window.player_bar = QWidget(window.central_widget)
        window.player_bar.setGeometry(0, 260, 480, 52)
        window.player_bar.show()
        window.toasts = ToastManager(window.central_widget)
        window.toasts.set_bottom_anchor(window.player_bar)
        try:
            before = window.central_widget.geometry()

            MainWindow._show_status_message(window, "Lyrics saved.", 2500)
            self.app.processEvents()

            self.assertEqual(window.central_widget.geometry(), before)
            self.assertIsNotNone(window.toasts._status_toast)
            toast = window.toasts._status_toast
            self.assertTrue(toast.isVisible())
            self.assertEqual(toast.lbl.text(), "Lyrics saved.")
            self.assertLessEqual(
                toast.y() + toast.height(),
                window.player_bar.y(),
            )

            window.toasts.show_toast("Saved.", "success", 3000)
            self.app.processEvents()
            normal_toast = next(t for t in window.toasts._toasts if t is not toast)
            self.assertLess(normal_toast.y(), toast.y())
            self.assertLessEqual(normal_toast.y() + normal_toast.height(), toast.y())
        finally:
            window.central_widget.deleteLater()

    def test_enter_play_handler_uses_the_focused_track_list(self):
        window = MainWindow.__new__(MainWindow)
        played: list[int] = []
        window.on_play_track = lambda track_id: played.append(int(track_id))
        track_list = SimpleNamespace(selected_track_id=lambda: 42)

        MainWindow._play_selected_from_track_list(window, track_list)

        self.assertEqual(played, [42])