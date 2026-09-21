from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QBoxLayout

from tests.widgets_navigation._shared import *
from ui.button_roles import set_button_role
from ui.icon_loader import (
    ICON_SIZE_COMPACT,
    ICON_SIZE_NORMAL,
    ICON_SIZE_PLAYBACK,
)


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class SharedUiComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_download_missing_tooltip_does_not_populate_status_bar(self):
        def noop(*args, **kwargs):
            return None

        widget = TopBarController(
            on_refresh=noop,
            on_download_missing=noop,
            on_export_library=noop,
            on_open_settings=noop,
            on_open_about=noop,
            on_toggle_logs=noop,
            on_toggle_hotkey_hints=noop,
            on_schedule_search=noop,
            on_filter_changed=noop,
        )
        try:
            widget.set_download_missing_mode("prefer_synced")
            self.assertIn("Download missing lyrics", widget.btn_download_missing.toolTip())
            self.assertEqual(widget.btn_download_missing.statusTip(), "")
            self.assertEqual(widget.btn_export_library.text(), "")
        finally:
            widget.deleteLater()

    def test_button_roles_are_semantic_and_theme_styles_are_declared(self):
        button = QPushButton("Save")
        try:
            set_button_role(button, "primary")
            self.assertEqual(button.property("buttonRole"), "primary")

            stylesheet = Path("src/ui/qss/app.qss").read_text(encoding="utf-8")
            for role in ("primary", "secondary", "ghost", "danger", "segmented", "chip"):
                self.assertIn(f'QPushButton[buttonRole="{role}"]', stylesheet)
            self.assertIn('QToolButton[buttonRole="icon"]', stylesheet)
        finally:
            button.deleteLater()

    def test_top_bar_uses_flat_command_bar_layout(self):
        def noop(*args, **kwargs):
            return None

        widget = TopBarController(
            on_refresh=noop,
            on_download_missing=noop,
            on_export_library=noop,
            on_open_settings=noop,
            on_open_about=noop,
            on_toggle_logs=noop,
            on_toggle_hotkey_hints=noop,
            on_schedule_search=noop,
            on_filter_changed=noop,
        )
        try:
            self.assertFalse(widget.search_label.isVisible())
            self.assertFalse(widget.filters_label.isVisible())
            self.assertFalse(widget.actions_label.isVisible())
            self.assertEqual(widget.search_box.minimumWidth(), 260)
            self.assertEqual(widget.chk_synced.minimumHeight(), 28)
            self.assertEqual(widget.library_actions_group.objectName(), "TopBarActionCluster")
            self.assertEqual(widget.app_actions_group.objectName(), "TopBarActionCluster")
            self.assertEqual(widget.actions_separator.objectName(), "TopBarActionSeparator")
            self.assertEqual(widget.btn_hotkeys.text(), "")
            self.assertFalse(widget.btn_hotkeys.icon().isNull())

            stylesheet = Path("src/ui/qss/main_window.qss").read_text(encoding="utf-8")
            self.assertIn("QWidget#TopBar {", stylesheet)
            self.assertIn("background-color: {{color-bg-panel}};", stylesheet)
            self.assertIn("max-height: 52px;", stylesheet)
            self.assertIn("QCheckBox#TopBarFilterCheck", stylesheet)
            self.assertIn("QWidget#TopBarActionCluster", stylesheet)
            self.assertIn("QWidget#TopBarActionSeparator", stylesheet)
            self.assertIn("background: transparent;", stylesheet)
            self.assertIn("border: none;", stylesheet)
            self.assertIn("min-height: 28px;", stylesheet)
            self.assertIn("padding: 4px 8px;", stylesheet)
            self.assertIn("min-width: 32px;", stylesheet)
            self.assertNotIn("min-height: 72px;", stylesheet)
        finally:
            widget.deleteLater()

    def test_top_bar_uses_overflow_for_global_actions_in_compact_layout(self):
        def noop(*args, **kwargs):
            return None

        widget = TopBarController(
            on_refresh=noop,
            on_download_missing=noop,
            on_export_library=noop,
            on_open_settings=noop,
            on_open_about=noop,
            on_toggle_logs=noop,
            on_toggle_hotkey_hints=noop,
            on_schedule_search=noop,
            on_filter_changed=noop,
        )
        try:
            widget.update_responsive_layout(1000)
            self.assertFalse(widget.btn_actions_overflow.isHidden())
            self.assertTrue(widget.library_actions_group.isHidden())
            self.assertTrue(widget.app_actions_group.isHidden())
            self.assertTrue(widget.actions_separator.isHidden())
            self.assertTrue(all(button.isHidden() for button in widget._regular_action_buttons))
            self.assertEqual(widget.root_layout.direction(), QBoxLayout.Direction.LeftToRight)

            widget.update_responsive_layout(1400)
            self.assertTrue(widget.btn_actions_overflow.isHidden())
            self.assertFalse(widget.library_actions_group.isHidden())
            self.assertFalse(widget.app_actions_group.isHidden())
            self.assertFalse(widget.actions_separator.isHidden())
            self.assertTrue(all(not button.isHidden() for button in widget._regular_action_buttons))
        finally:
            widget.deleteLater()

    def test_top_bar_filters_are_keyboard_focusable(self):
        def noop(*args, **kwargs):
            return None

        widget = TopBarController(
            on_refresh=noop,
            on_download_missing=noop,
            on_export_library=noop,
            on_open_settings=noop,
            on_open_about=noop,
            on_toggle_logs=noop,
            on_toggle_hotkey_hints=noop,
            on_schedule_search=noop,
            on_filter_changed=noop,
        )
        try:
            filters = (
                widget.chk_synced,
                widget.chk_plain,
                widget.chk_instr,
                widget.chk_none,
                widget.chk_unsaved,
            )
            self.assertTrue(all(control.focusPolicy() != Qt.FocusPolicy.NoFocus for control in filters))
            self.assertEqual(
                [control.accessibleName() for control in filters],
                [
                    "Filter synced lyrics",
                    "Filter plain lyrics",
                    "Filter instrumental tracks",
                    "Filter tracks without lyrics",
                    "Filter tracks with unsaved draft",
                ],
            )
        finally:
            widget.deleteLater()

    def test_top_bar_tab_order_cycles_only_search_and_filters(self):
        def noop(*args, **kwargs):
            return None

        widget = TopBarController(
            on_refresh=noop,
            on_download_missing=noop,
            on_export_library=noop,
            on_open_settings=noop,
            on_open_about=noop,
            on_toggle_logs=noop,
            on_toggle_hotkey_hints=noop,
            on_schedule_search=noop,
            on_filter_changed=noop,
        )
        window = SimpleNamespace(setTabOrder=MagicMock())
        tabs = QWidget()
        try:
            widget.bind_tab_order(window, tabs)

            calls = window.setTabOrder.call_args_list
            self.assertEqual(len(calls), 6)
            self.assertIs(calls[0].args[0], widget.search_box)
            self.assertIs(calls[-1].args[1], widget.search_box)
            self.assertTrue(all(tabs not in call.args for call in calls))
            self.assertTrue(all(widget.btn_refresh not in call.args for call in calls))
        finally:
            tabs.deleteLater()
            widget.deleteLater()

    def test_top_bar_intercepts_tab_before_it_reaches_library_widgets(self):
        def noop(*args, **kwargs):
            return None

        widget = TopBarController(
            on_refresh=noop,
            on_download_missing=noop,
            on_export_library=noop,
            on_open_settings=noop,
            on_open_about=noop,
            on_toggle_logs=noop,
            on_toggle_hotkey_hints=noop,
            on_schedule_search=noop,
            on_filter_changed=noop,
        )
        window = SimpleNamespace(setTabOrder=MagicMock())
        tabs = QWidget()
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab, Qt.KeyboardModifier.NoModifier)
        try:
            widget.bind_tab_order(window, tabs)
            widget.show()
            self.app.processEvents()
            widget.search_box.setFocus()
            self.app.processEvents()

            self.assertTrue(widget.eventFilter(widget.search_box, event))
            self.assertTrue(widget.chk_synced.hasFocus())

            event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
            self.assertTrue(widget.eventFilter(widget.chk_synced, event))
            self.assertTrue(widget.search_box.hasFocus())
        finally:
            widget.hide()
            tabs.deleteLater()
            widget.deleteLater()

    def test_icon_sizes_follow_shared_ui_scale(self):
        def noop(*args, **kwargs):
            return None

        widget = TopBarController(
            on_refresh=noop,
            on_download_missing=noop,
            on_export_library=noop,
            on_open_settings=noop,
            on_open_about=noop,
            on_toggle_logs=noop,
            on_toggle_hotkey_hints=noop,
            on_schedule_search=noop,
            on_filter_changed=noop,
        )
        player = PlayerBar(None)
        try:
            self.assertEqual(widget.btn_refresh.iconSize().width(), ICON_SIZE_NORMAL)
            self.assertEqual(player.btn_prev.iconSize().width(), ICON_SIZE_COMPACT)
            self.assertEqual(player.btn_play.iconSize().width(), ICON_SIZE_PLAYBACK)
            self.assertEqual(player.lbl_volume.iconSize().width(), ICON_SIZE_NORMAL)
        finally:
            widget.deleteLater()
            player.deleteLater()

    def test_main_navigation_separates_library_and_lrclib_tabs(self):
        tab_bar = LibraryNavigationTabBar()
        for label in ("Tracks", "Albums", "Artists", "Album Artists", "Lyrics Browser", "Lyrics Activity"):
            tab_bar.addTab(label)
        try:
            self.assertEqual(tab_bar.LIBRARY_TAB_COUNT, 4)
            self.assertEqual(tab_bar.tabText(4), "Lyrics Browser")
            stylesheet = Path("src/ui/qss/app.qss").read_text(encoding="utf-8")
            self.assertIn("border-bottom: 2px solid transparent;", stylesheet)
            self.assertIn("border-bottom-color: {{color-accent}};", stylesheet)
            self.assertIn("border-radius: 0;", stylesheet)
        finally:
            tab_bar.deleteLater()

    def test_context_row_uses_flat_breadcrumb_and_selection_surfaces(self):
        stylesheet = Path("src/ui/qss/main_window.qss").read_text(encoding="utf-8")
        self.assertIn("QWidget#LibraryNavBar {", stylesheet)
        self.assertIn("QWidget#SelectionActionsBar {", stylesheet)
        self.assertIn("background: transparent;", stylesheet)
        self.assertIn("border: none;", stylesheet)
        self.assertIn("LibraryBreadcrumbButton", stylesheet)

    def test_library_table_headers_use_readable_case_and_density(self):
        stylesheet = Path("src/ui/qss/data_table.qss").read_text(encoding="utf-8")
        self.assertIn("padding: 6px 8px;", stylesheet)
        self.assertIn("font-weight: 600;", stylesheet)
        self.assertNotIn("text-transform: uppercase;", stylesheet)

    def test_lyrics_splitter_toggle_is_reversible(self):
        splitter = LyricsPaneSplitter()
        splitter.addWidget(QWidget())
        splitter.addWidget(QWidget())
        try:
            splitter.set_lyrics_collapsed(False)
            button = splitter.handle(1).toggle_button
            self.assertIn("Collapse", button.toolTip())

            splitter.set_lyrics_collapsed(True)
            self.assertEqual(button.text(), "‹")
            self.assertIn("Expand", button.toolTip())

            splitter.set_lyrics_collapsed(False)
            self.assertEqual(button.text(), "›")
            self.assertIn("Collapse", button.toolTip())
        finally:
            splitter.deleteLater()

    def test_player_hotkey_badges_use_shared_badge_style(self):
        stylesheet = Path("src/ui/qss/player_bar.qss").read_text(encoding="utf-8")
        self.assertIn("QLabel#HotkeyHintBadge", stylesheet)
        self.assertIn("background: {{color-accent}};", stylesheet)
        self.assertIn("border-radius: {{radius-pill}};", stylesheet)
        self.assertIn("border-radius: 22px;", stylesheet)
        self.assertIn("border-radius: 14px;", stylesheet)
        self.assertIn("QToolButton#BtnPrev:hover", stylesheet)
        self.assertIn("QToolButton#BtnNext:hover", stylesheet)

    def test_light_theme_disabled_controls_keep_readable_contrast(self):
        tokens = get_theme_tokens("LightTheme")
        self.assertEqual(tokens["color-disabled-text"], "#475569")
        app_stylesheet = Path("src/ui/qss/app.qss").read_text(encoding="utf-8")
        main_stylesheet = Path("src/ui/qss/main_window.qss").read_text(encoding="utf-8")
        player_stylesheet = Path("src/ui/qss/player_bar.qss").read_text(encoding="utf-8")
        self.assertIn("QToolButton:disabled", app_stylesheet)
        self.assertIn("QToolButton#TopBarAction:disabled", main_stylesheet)
        self.assertIn("QToolButton:disabled", player_stylesheet)

    def test_hotkey_badge_uses_window_parent_for_small_buttons(self):
        parent = QWidget()
        button = QPushButton(parent)
        button.setGeometry(10, 10, 28, 28)
        manager = HotkeyHintManager(parent)
        try:
            parent.resize(120, 80)
            parent.show()
            self.app.processEvents()
            manager.register(button, "Ctrl+Left")
            manager.set_visible(True)

            badge = manager._hints[0].badge
            self.assertIs(badge.parentWidget(), parent)
            self.assertEqual(badge.text(), "C<")
            self.assertLessEqual(badge.width(), button.width())
            self.assertGreaterEqual(badge.x(), button.x())
            self.assertLessEqual(badge.x() + badge.width(), button.x() + button.width())
            self.assertTrue(badge.isVisible())
        finally:
            parent.deleteLater()

    def test_hotkey_badge_refresh_updates_after_layout_shift(self):
        parent = QWidget()
        button = QPushButton(parent)
        button.setGeometry(10, 10, 80, 36)
        manager = HotkeyHintManager(parent)
        try:
            parent.resize(220, 120)
            parent.show()
            self.app.processEvents()
            manager.register(button, "Ctrl+F")
            manager.set_visible(True)
            original_pos = manager._hints[0].badge.pos()

            button.move(10, 70)
            manager.refresh_positions()

            self.assertNotEqual(manager._hints[0].badge.pos(), original_pos)
            self.assertGreater(manager._hints[0].badge.y(), original_pos.y())
            self.assertTrue(manager._hints[0].badge.isVisible())
        finally:
            parent.deleteLater()

    def test_hotkey_badge_register_updates_existing_widget(self):
        parent = QWidget()
        button = QPushButton(parent)
        manager = HotkeyHintManager(parent)
        try:
            manager.register(button, "Ctrl+F")
            manager.register(button, "Tab")

            self.assertEqual(len(manager._hints), 1)
            self.assertEqual(manager._hints[0].key, "Tab")
            self.assertEqual(manager._hints[0].badge.text(), "Tab")
        finally:
            parent.deleteLater()

    def test_player_speed_label_and_value_fit_centered(self):
        widget = PlayerBar(player=None)
        try:
            widget.cmb_speed.resize(100, 28)
            widget._set_speed_combo_value(1.0)
            prefix = widget.lbl_speed_prefix.geometry()
            margins = widget.cmb_speed.lineEdit().textMargins()
            value_width = widget.cmb_speed.lineEdit().fontMetrics().horizontalAdvance(widget.cmb_speed.lineEdit().text())
            group_left = prefix.left()
            group_width = 44 + 4 + 50
            group_right = group_left + group_width

            self.assertGreaterEqual(group_left, 0)
            self.assertLessEqual(group_right, widget.cmb_speed.width())
            self.assertGreaterEqual(group_left - (widget.cmb_speed.width() - group_right), 0)
            self.assertLessEqual(group_left - (widget.cmb_speed.width() - group_right), 10)
            self.assertLessEqual(margins.left() + value_width, group_right)

            left_for_one_decimal = widget.lbl_speed_prefix.x()
            margin_for_one_decimal = margins.left()
            widget._set_speed_combo_value(1.05)
            self.assertEqual(widget.lbl_speed_prefix.x(), left_for_one_decimal)
            self.assertEqual(widget.cmb_speed.lineEdit().textMargins().left(), margin_for_one_decimal)
        finally:
            widget.deleteLater()

    def test_player_cover_is_larger_and_text_is_centered(self):
        widget = PlayerBar(player=None)
        try:
            widget.resize(1000, 120)
            widget.show()
            self.app.processEvents()

            self.assertEqual(widget.lbl_cover.width(), PLAYER_COVER_SIZE)
            self.assertEqual(widget.lbl_cover.height(), PLAYER_COVER_SIZE)

            text_widgets = [widget.lbl_title, widget.lbl_artist, widget.lbl_album]
            text_top = min(label.geometry().top() for label in text_widgets if label.isVisible())
            text_bottom = max(label.geometry().bottom() for label in text_widgets if label.isVisible())
            text_center_y = (text_top + text_bottom) // 2
            cover_center_y = widget.lbl_cover.geometry().center().y()

            self.assertLessEqual(abs(text_center_y - cover_center_y), 4)
        finally:
            widget.deleteLater()

    def test_player_volume_slider_aligns_with_speed_combo(self):
        widget = PlayerBar(player=None)
        try:
            widget.show()
            self.app.processEvents()

            self.assertEqual(widget.slider_volume.width(), widget.cmb_speed.width())
            self.assertEqual(widget.slider_volume.x(), widget.cmb_speed.x())
            self.assertEqual(widget.lbl_volume.x(), widget.btn_speed_down.x())
            self.assertEqual(widget.lbl_volume_value.x(), widget.btn_speed_up.x())
            self.assertEqual(widget.lbl_volume_value.width(), widget.btn_speed_up.width())
        finally:
            widget.deleteLater()

    def test_player_transport_stays_centered_between_symmetric_side_panels(self):
        widget = PlayerBar(player=None)
        try:
            widget.resize(1200, 120)
            widget.show()
            self.app.processEvents()

            shell_center = widget.findChild(QWidget, "PlayerShell").rect().center().x()
            center_panel = widget.center_panel.geometry()
            self.assertEqual(widget.left_panel.width(), widget.right_panel.width())
            self.assertLessEqual(abs(center_panel.center().x() - shell_center), 1)

            widget.lbl_title.setText("A very long title that should not move playback controls")
            widget.lbl_artist.setText("A very long artist name")
            widget.lbl_album.setText("A very long album name")
            self.app.processEvents()
            self.assertLessEqual(abs(widget.center_panel.geometry().center().x() - shell_center), 1)
        finally:
            widget.deleteLater()

    def test_player_seek_uses_stable_accessible_time_controls(self):
        widget = PlayerBar(player=None)
        try:
            self.assertEqual(widget.lbl_time.width(), 40)
            self.assertEqual(widget.lbl_dur.width(), 40)
            self.assertEqual(widget.lbl_time.alignment(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.assertEqual(widget.lbl_dur.alignment(), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.assertEqual(widget.slider.accessibleName(), "Track position")
            self.assertEqual(widget.slider.focusPolicy(), Qt.FocusPolicy.StrongFocus)
            self.assertGreaterEqual(widget.slider.minimumHeight(), 20)

            widget.slider.setObjectName("PlayerSlider")
            self.assertEqual(widget.slider._track_geometry()[3], 6.0)
            widget.slider_volume.setObjectName("VolumeSlider")
            self.assertEqual(widget.slider_volume._track_geometry()[3], 5.0)
        finally:
            widget.deleteLater()

    def test_player_slider_handles_keep_border_clearance_at_both_edges(self):
        widget = PlayerBar(player=None)
        try:
            for slider in (widget.slider, widget.slider_volume):
                handle_size = (
                    slider._SEEK_HANDLE_SIZE
                    if slider.objectName() == "PlayerSlider"
                    else slider._VOLUME_HANDLE_SIZE
                )
                slider.resize(100, 24)
                track_left, track_width, _track_top, _track_height = slider._track_geometry()
                edge_clearance = slider._HANDLE_BORDER_WIDTH / 2.0
                handle_radius = handle_size / 2.0

                self.assertGreaterEqual(track_left - handle_radius, edge_clearance)
                self.assertLessEqual(
                    track_left + track_width + handle_radius,
                    slider.width() - edge_clearance,
                )

                for center_x in (track_left, track_left + track_width):
                    handle_rect = QRectF(
                        center_x - handle_radius,
                        (slider.height() - handle_size) / 2.0,
                        handle_size,
                        handle_size,
                    )
                    focus_rect = slider._focus_ring_geometry(handle_rect)
                    self.assertGreaterEqual(focus_rect.left(), 0.0)
                    self.assertLessEqual(focus_rect.right(), slider.width())
        finally:
            widget.deleteLater()

    def test_track_action_buttons_track_individual_hover(self):
        table = QTableView()
        model = QStandardItemModel(1, 5)
        item = QStandardItem("")
        item.setData(
            TrackListRow(
                track_id=1,
                title="Song",
                artist="Artist",
                artist_id=None,
                album="Album",
                album_id=None,
                track_number=1,
                duration_s=120,
                lyrics_state=LyricsState.NONE,
                download_state=DownloadState.IDLE,
            ),
            Qt.ItemDataRole.UserRole,
        )
        model.setItem(0, 4, item)
        table.setModel(model)
        delegate = ActionsDelegate(table)
        option = QStyleOptionViewItem()
        option.widget = table
        option.rect = QRect(0, 0, 150, 44)
        refresh_rect, download_rect = delegate._button_rects(option.rect)
        index = model.index(0, 4)
        try:
            refresh_event = QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(refresh_rect.center()),
                QPointF(refresh_rect.center()),
                QPointF(refresh_rect.center()),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
            self.assertTrue(delegate.editorEvent(refresh_event, model, option, index))
            self.assertEqual(delegate._hover_button, "refresh")

            download_event = QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(download_rect.center()),
                QPointF(download_rect.center()),
                QPointF(download_rect.center()),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
            self.assertTrue(delegate.editorEvent(download_event, model, option, index))
            self.assertEqual(delegate._hover_button, "download")
        finally:
            table.deleteLater()

    def test_track_action_buttons_keep_theme_background_when_row_selected(self):
        table = QTableView()
        model = QStandardItemModel(1, 5)
        item = QStandardItem("")
        item.setData(
            TrackListRow(
                track_id=1,
                title="Song",
                artist="Artist",
                artist_id=None,
                album="Album",
                album_id=None,
                track_number=1,
                duration_s=120,
                lyrics_state=LyricsState.SYNCED,
                download_state=DownloadState.IDLE,
            ),
            Qt.ItemDataRole.UserRole,
        )
        model.setItem(0, 4, item)
        table.setModel(model)
        delegate = ActionsDelegate(table)
        option = QStyleOptionViewItem()
        option.widget = table
        option.rect = QRect(0, 0, 150, 44)
        option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Selected
        index = model.index(0, 4)
        refresh_rect, download_rect = delegate._button_rects(option.rect)
        image = QImage(option.rect.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("#554872"))
        painter = QPainter(image)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()
            table.deleteLater()

        button_sample = image.pixelColor(download_rect.left() + 8, download_rect.center().y())
        row_sample = image.pixelColor(8, download_rect.center().y())
        self.assertNotEqual(row_sample.name(), "#000000")
        self.assertLess(abs(button_sample.value() - row_sample.value()), 8)

        image.fill(QColor("#554872"))
        delegate._hover_row = 0
        delegate._hover_button = "download"
        painter = QPainter(image)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()

        hover_button_sample = image.pixelColor(download_rect.left() + 8, download_rect.center().y())
        hover_row_sample = image.pixelColor(8, download_rect.center().y())
        hover_cell_background = image.pixelColor(refresh_rect.left() - 4, download_rect.center().y())
        self.assertNotEqual(hover_button_sample.name(), hover_row_sample.name())
        self.assertLess(abs(hover_cell_background.value() - hover_row_sample.value()), 8)

    def test_lyrics_status_delegate_preserves_status_color_when_row_selected(self):
        table = QTableView()
        model = QStandardItemModel(1, 5)
        item = QStandardItem("Synced")
        synced_color = QColor("#22c55e")
        item.setData(synced_color, Qt.ItemDataRole.ForegroundRole)
        model.setItem(0, 3, item)
        table.setModel(model)
        delegate = LyricsStatusDelegate(table)
        option = QStyleOptionViewItem()
        option.widget = table
        option.rect = QRect(0, 0, 118, 44)
        option.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Selected
        option.palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))

        try:
            delegate.initStyleOption(option, model.index(0, 3))
        finally:
            table.deleteLater()

        highlighted = option.palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText)
        self.assertEqual(highlighted.name(), synced_color.name())

    def test_status_and_toast_with_same_text_do_not_duplicate(self):
        host = QWidget()
        host.resize(480, 320)
        host.show()
        manager = ToastManager(host)
        try:
            manager.show_status("Lyrics saved.", 2500)
            manager.show_toast("Lyrics saved.", "success", 3000)
            self.app.processEvents()

            self.assertEqual(len(manager._toasts), 1)
            self.assertIsNone(manager._status_toast)
            self.assertEqual(manager._toasts[0].lbl.text(), "Lyrics saved.")

            manager.show_status("Lyrics saved.", 2500)
            self.app.processEvents()
            self.assertEqual(len(manager._toasts), 1)
        finally:
            host.deleteLater()
