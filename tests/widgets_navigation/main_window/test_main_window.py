from tests.widgets_navigation._shared import *
from PySide6.QtWidgets import QToolButton
from PySide6.QtWidgets import QDialog
from dataclasses import replace

from db.models import Config
from db.queries import get_config, set_config
from ui.main_window_parts.preferences import persist_window_state_payload


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

    def test_auto_sync_missing_dependencies_opens_modal_dialog(self):
        window = MainWindow.__new__(MainWindow)
        window._editing_track_id = 1
        window._ai_sync_worker = None
        window._show_status_message = MagicMock()
        window.app_state = SimpleNamespace()

        with (
            patch("ui.workers.ai_sync_worker._check_ai_sync_available", return_value=(False, "Missing deps")),
            patch("ui.workers.ai_sync_worker.get_missing_ai_dependencies", return_value=["torch", "torchaudio"]),
            patch("ui.main_window.AIDependenciesDialog") as dialog_cls,
            patch("ui.main_window.notify_user") as notify_mock,
        ):
            dialog_cls.return_value.exec.return_value = QDialog.DialogCode.Rejected
            MainWindow._on_auto_sync_requested(window)

        dialog_cls.assert_called_once()
        dialog_cls.return_value.exec.assert_called_once()
        notify_mock.assert_not_called()

    def test_slider_up_down_moves_active_lyrics_selection(self):
        window = MainWindow.__new__(MainWindow)
        slider = SimpleNamespace()
        active_view = SimpleNamespace(move_selection_by_rows=MagicMock(return_value=True))
        window.player_bar = SimpleNamespace(slider=slider)
        window._active_lyrics_view = MagicMock(return_value=active_view)

        event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Down,
            Qt.KeyboardModifier.NoModifier,
        )

        self.assertTrue(MainWindow.eventFilter(window, slider, event))
        active_view.move_selection_by_rows.assert_called_once_with(1)

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

    def test_export_track_ids_disables_audio_embedding(self):
        window = MainWindow.__new__(MainWindow)
        window.app_state = SimpleNamespace(db=object())
        window.lyrics_output = SimpleNamespace(export_tracks=MagicMock(return_value=True))
        window._on_lyrics_exported = MagicMock()
        window._on_lyrics_export_finished = MagicMock()

        config = Config(
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

        with patch("ui.main_window.get_config", return_value=config):
            MainWindow._export_track_ids(window, [1, 2])

        args, kwargs = window.lyrics_output.export_tracks.call_args
        self.assertEqual(args[0], [1, 2])
        self.assertTrue(kwargs["export_config"].save_lyrics_sidecars)
        self.assertFalse(kwargs["export_config"].try_embed_lyrics)

    def test_save_window_state_persists_filter_checkboxes(self):
        window = MainWindow.__new__(MainWindow)
        saved_payload = {}
        window._persist_window_state_payload = lambda payload: saved_payload.update(payload)
        window.saveGeometry = MagicMock(return_value=QByteArray(b"geo"))
        window.geometry = lambda: QRect(40, 50, 1200, 760)
        window.isMaximized = lambda: False
        window._build_library_splitter_state = MagicMock(
            return_value={"orientation": "horizontal", "sizes": [690, 480]}
        )
        window.content_splitter = SimpleNamespace(sizes=lambda: [690, 480])
        window.albums_splitter = SimpleNamespace(sizes=lambda: [690, 480])
        window.artists_splitter = SimpleNamespace(sizes=lambda: [690, 480])
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
        self.assertEqual(
            saved_payload["window_rect"],
            {"x": 40, "y": 50, "width": 1200, "height": 760},
        )
        self.assertFalse(saved_payload["is_maximized"])
        self.assertEqual(
            saved_payload["library_splitter"],
            {"orientation": "horizontal", "sizes": [690, 480]},
        )

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
        window.geometry = lambda: QRect(40, 50, 1200, 760)
        window.setGeometry = MagicMock()
        window.move = MagicMock()
        window.minimumWidth = lambda: 0
        window.minimumHeight = lambda: 0
        window.minimumSizeHint = lambda: SimpleNamespace(width=lambda: 820, height=lambda: 560)
        window.isMaximized = lambda: False
        window.isFullScreen = lambda: False
        window.screen = lambda: None
        window._restore_library_splitter_state = MagicMock()

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
        window._restore_library_splitter_state.assert_called_once_with(window._load_window_state_payload.return_value)

    def test_restore_window_state_falls_back_from_too_small_saved_geometry(self):
        class DummyWindow:
            def __init__(self):
                self._geometry = QRect(40, 50, 900, 600)
                self._load_window_state_payload = MagicMock(
                    return_value={
                        "window_rect": {"x": 20, "y": 30, "width": 420, "height": 320},
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
                        "window_rect": {"x": 20, "y": 30, "width": 930, "height": 760},
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

    def test_sync_library_splitters_from_active_splitter(self):
        class DummySplitter:
            def __init__(self, sizes, orientation):
                self._sizes = list(sizes)
                self._orientation = orientation

            def sizes(self):
                return list(self._sizes)

            def setSizes(self, sizes):
                self._sizes = [int(value) for value in sizes]

            def orientation(self):
                return self._orientation

            def setOrientation(self, orientation):
                self._orientation = orientation

        window = MainWindow.__new__(MainWindow)
        window.content_splitter = DummySplitter([690, 480], Qt.Orientation.Horizontal)
        window.albums_splitter = DummySplitter([300, 200], Qt.Orientation.Horizontal)
        window.artists_splitter = DummySplitter([100, 100], Qt.Orientation.Vertical)
        window._syncing_library_splitters = False

        MainWindow._sync_library_splitters_from(window, window.content_splitter)

        self.assertEqual(window.albums_splitter.orientation(), Qt.Orientation.Horizontal)
        self.assertEqual(window.artists_splitter.orientation(), Qt.Orientation.Horizontal)
        self.assertEqual(window.albums_splitter.sizes(), [295, 205])
        self.assertEqual(window.artists_splitter.sizes(), [118, 82])

    def test_restore_library_splitter_state_prefers_shared_payload(self):
        class DummySplitter:
            def __init__(self, sizes, orientation):
                self._sizes = list(sizes)
                self._orientation = orientation

            def sizes(self):
                return list(self._sizes)

            def setSizes(self, sizes):
                self._sizes = [int(value) for value in sizes]

            def orientation(self):
                return self._orientation

            def setOrientation(self, orientation):
                self._orientation = orientation

        window = MainWindow.__new__(MainWindow)
        window.content_splitter = DummySplitter([600, 400], Qt.Orientation.Horizontal)
        window.albums_splitter = DummySplitter([300, 200], Qt.Orientation.Horizontal)
        window.artists_splitter = DummySplitter([300, 200], Qt.Orientation.Horizontal)
        window._syncing_library_splitters = False

        MainWindow._restore_library_splitter_state(
            window,
            {
                "library_splitter": {
                    "orientation": "vertical",
                    "sizes": [500, 300],
                },
                "tracks_splitter": [100, 900],
            },
        )

        self.assertEqual(window.content_splitter.orientation(), Qt.Orientation.Vertical)
        self.assertEqual(window.albums_splitter.orientation(), Qt.Orientation.Vertical)
        self.assertEqual(window.artists_splitter.orientation(), Qt.Orientation.Vertical)
        self.assertEqual(window.content_splitter.sizes(), [500, 300])
        self.assertEqual(window.albums_splitter.sizes(), [312, 188])
        self.assertEqual(window.artists_splitter.sizes(), [312, 188])

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

    def test_persist_window_state_payload_preserves_ai_sync_settings(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                config = get_config(app_state.db)
                initial_state = {
                    "ai_sync": {
                        "device": "cpu",
                        "language": "ro",
                        "enable_fuzzy": False,
                        "fuzzy_threshold": 72,
                    },
                    "some_other_ui_flag": True,
                }
                set_config(
                    app_state.db,
                    replace(
                        config,
                        ui_state_json=json.dumps(initial_state, ensure_ascii=True, separators=(",", ":")),
                    ),
                )

                window = SimpleNamespace(app_state=app_state)
                persist_window_state_payload(window, {"tab_index": 2, "geometry": "dummy"})

                reloaded = get_config(app_state.db)
                merged = json.loads(reloaded.ui_state_json)
                self.assertEqual(merged.get("tab_index"), 2)
                self.assertEqual(merged.get("geometry"), "dummy")
                self.assertEqual(merged.get("some_other_ui_flag"), True)
                self.assertEqual(
                    merged.get("ai_sync"),
                    {
                        "device": "cpu",
                        "language": "ro",
                        "enable_fuzzy": False,
                        "fuzzy_threshold": 72,
                    },
                )
            finally:
                app_state.db.close()

    def test_persist_window_state_payload_handles_invalid_existing_json(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                config = get_config(app_state.db)
                set_config(app_state.db, replace(config, ui_state_json="{invalid json"))

                window = SimpleNamespace(app_state=app_state)
                persist_window_state_payload(window, {"tab_index": 3})

                reloaded = get_config(app_state.db)
                parsed = json.loads(reloaded.ui_state_json)
                self.assertEqual(parsed.get("tab_index"), 3)
            finally:
                app_state.db.close()

    def test_ai_sync_progress_parses_structured_progress_message(self):
        updates: list[tuple[int, int, str, str]] = []
        statuses: list[str] = []
        window = MainWindow.__new__(MainWindow)
        window._show_status_message = lambda msg, *_args, **_kwargs: statuses.append(str(msg))
        window.ai_sync_overlay = SimpleNamespace(
            update_progress=lambda current, total, label, status: updates.append((current, total, label, status))
        )

        MainWindow._on_ai_sync_progress(
            window,
            "__AI_SYNC_PROGRESS__|3|8|Transcribing audio (base pass)…",
        )

        self.assertEqual(statuses[-1], "Transcribing audio (base pass)…")
        self.assertEqual(updates[-1], (3, 8, "AI Auto-Sync", "Transcribing audio (base pass)…"))

    def test_ai_sync_progress_fallback_mapping_without_marker(self):
        updates: list[tuple[int, int, str, str]] = []
        statuses: list[str] = []
        window = MainWindow.__new__(MainWindow)
        window._show_status_message = lambda msg, *_args, **_kwargs: statuses.append(str(msg))
        window.ai_sync_overlay = SimpleNamespace(
            update_progress=lambda current, total, label, status: updates.append((current, total, label, status))
        )

        MainWindow._on_ai_sync_progress(window, "Performing alignment (forced alignment)...")

        self.assertEqual(statuses[-1], "Performing alignment (forced alignment)...")
        self.assertEqual(updates[-1], (4, 8, "AI Auto-Sync", "Performing alignment (forced alignment)..."))

    def test_validate_current_selected_track_clears_deleted_track(self):
        with TemporaryDirectory() as tmp:
            app_state = simple_app_state(initialize_database(tmp))
            try:
                window = MainWindow.__new__(MainWindow)
                window.app_state = app_state
                window._editing_track_id = 99999  # non-existent ID
                window._editing_saved_lyrics = ("synced", "plain")
                cleared_views = []
                window._all_lyrics_views = lambda: [
                    SimpleNamespace(set_track_lyrics=lambda **kwargs: cleared_views.append(kwargs))
                ]
                window.track_list = SimpleNamespace(table=SimpleNamespace(selectionModel=lambda: None))
                window.albums_tab = SimpleNamespace(track_list=None)
                window.artists_tab = SimpleNamespace(album_browser=SimpleNamespace(track_list=None))

                MainWindow._validate_current_selected_track(window)

                self.assertIsNone(window._editing_track_id)
                self.assertEqual(window._editing_saved_lyrics, ("", ""))
                self.assertEqual(len(cleared_views), 1)
                self.assertEqual(cleared_views[0]["title"], "No Track Selected")
            finally:
                app_state.db.close()

    def test_reapply_theme_styles_calls_apply_styles_on_all_components(self):
        from ui.main_window_parts.preferences import reapply_theme_styles
        called = []
        window = SimpleNamespace(
            setStyleSheet=lambda s: called.append("window"),
            player_bar=SimpleNamespace(_apply_styles=lambda: called.append("player_bar")),
            track_list=SimpleNamespace(
                _apply_styles=lambda: called.append("track_list"),
                model=SimpleNamespace(layoutChanged=SimpleNamespace(emit=lambda: None)),
                table=SimpleNamespace(viewport=lambda: SimpleNamespace(update=lambda: None)),
            ),
            albums_tab=SimpleNamespace(_apply_styles=lambda: called.append("albums_tab")),
            artists_tab=SimpleNamespace(_apply_styles=lambda: called.append("artists_tab")),
            lrclib_browser_tab=SimpleNamespace(_apply_styles=lambda: called.append("lrclib_browser_tab")),
            mylrclib_tab=SimpleNamespace(_apply_styles=lambda: called.append("mylrclib_tab")),
            top_bar=SimpleNamespace(_apply_styles=lambda: called.append("top_bar")),
            _all_lyrics_views=lambda: [
                SimpleNamespace(_apply_styles=lambda: called.append("lyrics_view"))
            ],
        )

        with patch("ui.main_window_parts.preferences.load_stylesheet", return_value=""):
            reapply_theme_styles(window)

        self.assertIn("player_bar", called)
        self.assertIn("track_list", called)
        self.assertIn("albums_tab", called)
        self.assertIn("artists_tab", called)
        self.assertIn("lyrics_view", called)