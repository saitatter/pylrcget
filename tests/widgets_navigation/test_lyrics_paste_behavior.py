from tests.widgets_navigation._shared import *

@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class LyricsPasteBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_plain_lyrics_editor_rejects_rich_text_paste(self):
        widget = LyricsEditorWidget()
        try:
            self.assertFalse(widget.plain.acceptRichText())
        finally:
            widget.deleteLater()

    def test_empty_lyrics_state_exposes_auto_sync_action(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_track_lyrics("Song", "", "", False)

            self.assertIs(widget.stack.currentWidget(), widget.empty_state)
            self.assertFalse(widget.empty_state.quaternary_action.isHidden())
            self.assertEqual(widget.empty_state.quaternary_action.text(), "Auto Sync")
        finally:
            widget.deleteLater()

    def test_empty_lyrics_auto_sync_action_opens_editor_and_emits_request(self):
        widget = LyricsEditorWidget()
        emitted: list[bool] = []
        widget.autoSyncRequested.connect(lambda: emitted.append(True))
        try:
            widget.set_track_lyrics("Song", "", "", False)

            widget.empty_state.quaternary_action.click()

            self.assertEqual(emitted, [True])
            self.assertIs(widget.stack.currentWidget(), widget.plain)
            self.assertFalse(widget.btn_auto_sync.isHidden())
        finally:
            widget.deleteLater()

    def test_switch_to_synced_parses_pasted_lrc(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_plain("[ar: Artist]\n[ti: Song]\n[00:01.20] First line\n[00:03.00] Second line")
            widget._toggle_editor_mode()

            self.assertEqual(widget.table.rowCount(), 2)
            self.assertEqual(widget.table.item(0, 1).text(), "First line")
            self.assertEqual(widget.table.item(1, 1).text(), "Second line")
            self.assertEqual(widget.table.item(0, 0).text(), "00:01.20")
            self.assertEqual(widget.table.item(1, 0).text(), "00:03.00")
        finally:
            widget.deleteLater()

    def test_synced_lyrics_table_can_copy_selected_lrc_rows(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line")])
            widget.table.selectRow(1)

            widget._copy_synced_selection_to_clipboard()

            self.assertEqual(self.app.clipboard().text(), "[00:03.00] Second line")
        finally:
            widget.deleteLater()

    def test_synced_lyrics_table_can_paste_lrc_from_clipboard(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "Old line")])
            self.app.clipboard().setText("[00:02.50] New line\n[00:04.00] Next line")

            self.assertTrue(widget._paste_synced_from_clipboard())

            self.assertEqual(widget.table.rowCount(), 2)
            self.assertEqual(widget.table.item(0, 0).text(), "00:02.50")
            self.assertEqual(widget.table.item(0, 1).text(), "New line")
            self.assertEqual(widget.table.item(1, 0).text(), "00:04.00")
            self.assertEqual(widget.table.item(1, 1).text(), "Next line")
        finally:
            widget.deleteLater()

    def test_lyrics_quick_actions_have_shortcuts(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line"), (8000, "")])
            widget.table.selectRow(0)

            self.assertIn("(Left)", widget.btn_shift_minus.toolTip())
            self.assertIn("(Right)", widget.btn_shift_plus.toolTip())
            self.assertEqual(widget._shortcut_shift_minus.key().toString(), "Left")
            self.assertEqual(widget._shortcut_shift_plus.key().toString(), "Right")
            self.assertEqual(widget._shortcut_snap.key().toString(), "Ctrl+Return")
            self.assertEqual(widget._shortcut_add_line.key().toString(), "Ins")
            self.assertEqual(widget._shortcut_add_line_new.key().toString(), "Ctrl+N")
            self.assertEqual(widget._shortcut_add_line_before.key().toString(), "Ctrl+Shift+N")
            self.assertEqual(widget._shortcut_delete_line.key().toString(), "Del")
            self.assertIs(widget._shortcut_shift_plus.parent(), widget.table)

            widget._shortcut_shift_plus.activated.emit()
            self.assertEqual(widget.table.item(0, 0).text(), "00:01.30")
            self.assertEqual(widget.table.item(0, 0).data(TIMESTAMP_MS_ROLE), 1300)
        finally:
            widget.deleteLater()

    def test_lyrics_hotkey_bindings_update_configurable_shortcuts(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_hotkey_bindings(
                {
                    "snap": "Tab",
                    "shift_selected": "Alt+S",
                    "shift_all_from_first": "Ctrl+Alt+A",
                }
            )

            self.assertEqual(widget.lyrics_hotkeys["snap"], "Tab")
            self.assertEqual(widget._shortcut_snap.key().toString(), "Tab")
            self.assertIsNone(widget._shortcut_snap_enter)
            self.assertEqual(widget._shortcut_shift_selected.key().toString(), "Alt+S")
            self.assertIsNone(widget._shortcut_shift_selected_enter)
            self.assertEqual(widget._shortcut_shift_all.key().toString(), "Ctrl+Alt+A")
            self.assertIsNone(widget._shortcut_shift_all_enter)
            self.assertIn("(Tab)", widget.btn_snap.toolTip())
            self.assertIn("(Alt+S)", widget.btn_shift_selected.toolTip())
            self.assertIn("(Ctrl+Alt+A)", widget.btn_shift_all_from_first.toolTip())
        finally:
            widget.deleteLater()

    def test_lyrics_hotkey_bindings_can_disable_shortcuts(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_hotkey_bindings(
                {
                    "snap": {"enabled": False, "key": "Tab"},
                    "shift_selected": {"enabled": True, "key": "Alt+S"},
                    "shift_all_from_first": {"enabled": True, "key": "Ctrl+Alt+A"},
                }
            )

            self.assertEqual(widget.lyrics_hotkeys["snap"], "")
            self.assertIsNone(widget._shortcut_snap)
            self.assertIsNone(widget._shortcut_snap_enter)
            self.assertIn("(Disabled)", widget.btn_snap.toolTip())
        finally:
            widget.deleteLater()

    def test_insert_line_before_selection_can_add_first_row(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_current_position_provider(lambda: 500)
            widget._set_synced([(1200, "First line"), (3000, "Second line")])
            widget.table.setCurrentCell(0, 1)

            widget._add_line_before_selection()

            self.assertEqual(widget.table.rowCount(), 3)
            self.assertEqual(widget.table.item(0, 0).text(), "00:00.50")
            self.assertEqual(widget.table.item(0, 1).text(), "")
            self.assertEqual(widget.table.currentRow(), 0)
            self.assertEqual(widget.table.currentColumn(), 1)
            self.assertEqual(widget.table.item(1, 1).text(), "First line")
        finally:
            widget.deleteLater()

    def test_enter_on_synced_timestamp_starts_editing_without_seek(self):
        widget = LyricsEditorWidget()
        emitted: list[int] = []
        widget.seekRequested.connect(emitted.append)
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line")])
            widget.table.setCurrentCell(0, 0)

            self.assertTrue(widget._handle_synced_table_enter())

            self.assertEqual(emitted, [])
            self.assertEqual(widget.table.state(), widget.table.State.EditingState)
        finally:
            widget.deleteLater()

    def test_enter_on_synced_lyric_replays_from_line_timestamp(self):
        widget = LyricsEditorWidget()
        emitted: list[int] = []
        widget.seekRequested.connect(emitted.append)
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line")])
            widget.table.setCurrentCell(1, 1)

            self.assertTrue(widget._handle_synced_table_enter())

            self.assertEqual(emitted, [3000])
        finally:
            widget.deleteLater()

    def test_keypad_enter_on_synced_lyric_replays_from_line_timestamp(self):
        widget = LyricsEditorWidget()
        emitted: list[int] = []
        widget.seekRequested.connect(emitted.append)
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line")])
            widget.table.setCurrentCell(1, 1)
            event = QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Enter,
                Qt.KeyboardModifier.KeypadModifier,
            )

            self.assertTrue(widget.eventFilter(widget.table, event))

            self.assertEqual(emitted, [3000])
        finally:
            widget.deleteLater()

    def test_lyrics_validator_blocks_save_until_autofix(self):
        widget = LyricsEditorWidget()
        emitted: list[tuple[str, str]] = []
        widget.saveRequested.connect(lambda lrc, plain: emitted.append((lrc, plain)))
        try:
            widget._set_synced([(1200, "First line."), (3000, "Second line")])

            self.assertFalse(widget.btn_save.isEnabled())
            self.assertFalse(widget.btn_autofix.isHidden())
            self.assertIn("mark the end", widget.validation_hint.text())

            widget._emit_save()
            self.assertEqual(emitted, [])

            widget._autofix_validation_problems()
            self.assertTrue(widget.btn_save.isEnabled())
            self.assertTrue(widget.btn_autofix.isHidden())

            widget._emit_save()
            self.assertEqual(len(emitted), 1)
            self.assertIn("[00:08.00]", emitted[0][0])
            self.assertNotIn("First line.", emitted[0][0])
        finally:
            widget.deleteLater()

    def test_synced_lyrics_editor_marks_duplicate_timestamps_invalid(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "First line"), (1200, "Second line"), (5000, "")])

            self.assertFalse(widget.btn_save.isEnabled())
            self.assertTrue(widget.btn_autofix.isEnabled())
            self.assertEqual(widget._lint_rows, {0, 1})
            self.assertIn("Duplicate timestamp", widget.validation_hint.text())
            self.assertEqual(widget.validation_badge.text(), "2 issues")
            self.assertIn("Duplicate timestamp", widget.table.item(0, 0).toolTip())
            self.assertIn("Duplicate timestamp", widget.table.item(1, 1).toolTip())
            self.assertEqual(widget.table.item(0, 0).background().color(), QColor("#2a0a0a"))
            self.assertEqual(widget.table.item(1, 1).background().color(), QColor("#2a0a0a"))
            self.assertNotEqual(widget.table.item(0, LINE_NUMBER_COLUMN).background().color(), QColor("#2a0a0a"))
            self.assertEqual(widget.table.item(0, LINE_NUMBER_COLUMN).foreground().color(), QColor("#fee2e2"))
        finally:
            widget.deleteLater()

    def test_validation_hint_click_jumps_to_first_issue(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(3000, "Second line"), (2000, "First line"), (5000, "")])
            event = QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(1, 1),
                QPointF(1, 1),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )

            self.assertTrue(widget.eventFilter(widget.validation_hint, event))

            self.assertEqual(widget.table.currentRow(), 1)
            self.assertEqual(widget.table.currentColumn(), 0)
        finally:
            widget.deleteLater()

    def test_synced_duplicate_autofix_separates_timestamps(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "First line"), (1200, "Second line"), (5000, "")])

            widget._autofix_validation_problems()

            self.assertTrue(widget.btn_save.isEnabled())
            self.assertEqual(widget.table.item(0, 0).text(), "00:01.20")
            self.assertEqual(widget.table.item(1, 0).text(), "00:01.25")
            self.assertEqual(widget.validation_badge.text(), "Valid")
        finally:
            widget.deleteLater()

    def test_publish_buttons_follow_synced_validator_state(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_track_lyrics(
                "Song",
                "First line\nSecond line",
                "[00:01.20] First line\n[00:01.20] Second line\n[00:05.00]",
                False,
            )

            self.assertFalse(widget.btn_save.isEnabled())
            self.assertFalse(widget.btn_publish_synced.isEnabled())
            self.assertFalse(widget.btn_publish_plain.isEnabled())
            self.assertEqual(widget.btn_publish_synced.toolTip(), "Fix validation issues before publishing.")
            self.assertEqual(widget.btn_publish_plain.toolTip(), "Fix validation issues before publishing.")

            widget.set_track_lyrics(
                "Song",
                "First line\nSecond line",
                "[00:01.20] First line\n[00:03.00] Second line\n[00:05.00]",
                False,
            )

            self.assertTrue(widget.btn_save.isEnabled())
            self.assertTrue(widget.btn_publish_synced.isEnabled())
            self.assertTrue(widget.btn_publish_plain.isEnabled())
            self.assertEqual(widget.btn_publish_synced.toolTip(), "Publish synced (LRC) lyrics to LRCLIB")
            self.assertEqual(widget.validation_badge.text(), "Valid")
        finally:
            widget.deleteLater()

    def test_publish_buttons_explain_dirty_draft_state(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_track_lyrics(
                "Song",
                "Saved line",
                "[00:01.20] Saved line\n[00:05.00]",
                False,
                dirty_txt_lyrics="Draft line",
                dirty_lrc_lyrics="[00:01.20] Draft line\n[00:05.00]",
                dirty_lyrics_present=True,
            )

            self.assertFalse(widget.btn_publish_synced.isEnabled())
            self.assertFalse(widget.btn_publish_plain.isEnabled())
            self.assertEqual(widget.btn_publish_synced.toolTip(), "Save the draft before publishing to LRCLIB.")
            self.assertEqual(widget.btn_publish_plain.toolTip(), "Save the draft before publishing to LRCLIB.")
        finally:
            widget.deleteLater()

    def test_publish_buttons_disable_when_saved_lyrics_become_dirty(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_track_lyrics(
                "Song",
                "Saved line",
                "[00:01.20] Saved line\n[00:05.00]",
                False,
            )

            self.assertTrue(widget.btn_publish_synced.isEnabled())
            self.assertTrue(widget.btn_publish_plain.isEnabled())

            widget.table.item(0, 1).setText("Changed line")

            self.assertTrue(widget._has_dirty_draft)
            self.assertFalse(widget.btn_publish_synced.isEnabled())
            self.assertFalse(widget.btn_publish_plain.isEnabled())
            self.assertEqual(widget.btn_publish_synced.toolTip(), "Save the draft before publishing to LRCLIB.")
            self.assertEqual(widget.btn_publish_plain.toolTip(), "Save the draft before publishing to LRCLIB.")
        finally:
            widget.deleteLater()

    def test_publish_plain_button_follows_plain_validator_state(self):
        widget = LyricsEditorWidget()
        try:
            widget.set_track_lyrics("Song", "[00:01.00] Not plain", "", False)

            self.assertFalse(widget.btn_save.isEnabled())
            self.assertFalse(widget.btn_publish_plain.isEnabled())

            widget.set_track_lyrics("Song", "Plain line", "", False)

            self.assertTrue(widget.btn_save.isEnabled())
            self.assertTrue(widget.btn_publish_plain.isEnabled())
        finally:
            widget.deleteLater()

    def test_synced_lyrics_editor_shows_line_numbers(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line")])

            self.assertTrue(widget.table.verticalHeader().isHidden())
            self.assertEqual(widget.table.horizontalHeaderItem(LINE_NUMBER_COLUMN).text(), "#")
            self.assertEqual(widget.table.item(0, LINE_NUMBER_COLUMN).text(), "1")
            self.assertEqual(widget.table.item(1, LINE_NUMBER_COLUMN).text(), "2")

            widget.table.setCurrentCell(0, 1)
            widget._add_line_before_selection()
            self.assertEqual(
                [widget.table.item(row, LINE_NUMBER_COLUMN).text() for row in range(widget.table.rowCount())],
                ["1", "2", "3"],
            )
        finally:
            widget.deleteLater()

    def test_plain_lyrics_validator_blocks_save(self):
        widget = LyricsEditorWidget()
        emitted: list[tuple[str, str]] = []
        widget.saveRequested.connect(lambda lrc, plain: emitted.append((lrc, plain)))
        try:
            widget._set_plain("[00:01.00] Not plain")

            self.assertFalse(widget.btn_save.isEnabled())
            self.assertFalse(widget.btn_autofix.isEnabled())
            widget._emit_save()
            self.assertEqual(emitted, [])
        finally:
            widget.deleteLater()

    def test_sync_others_button_emits_current_lyrics(self):
        widget = LyricsEditorWidget()
        emitted: list[tuple[str, str]] = []
        widget.propagateRequested.connect(lambda lrc, plain: emitted.append((lrc, plain)))
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line"), (8000, "")])

            self.assertTrue(widget.btn_sync_others.isEnabled())
            widget._emit_propagate()

            self.assertEqual(len(emitted), 1)
            self.assertIn("[00:01.20] First line", emitted[0][0])
            self.assertEqual(emitted[0][1], "First line\nSecond line")
        finally:
            widget.deleteLater()

    def test_propagate_dialog_returns_checked_track_ids(self):
        from db.models import Track

        track = Track(
            id=42,
            file_path="song.flac",
            file_name="song.flac",
            title="Song",
            album_name="Single",
            album_artist_name="Artist A",
            album_id=2,
            artist_name="Artist A",
            artist_id=1,
            image_path=None,
            track_number=1,
            txt_lyrics="old lyrics",
            lrc_lyrics=None,
            duration=181.0,
            instrumental=False,
        )
        dialog = LyricsPropagateDialog(
            [
                {
                    "track": track,
                    "score": 96,
                    "title_score": 100,
                    "artist_score": 100,
                    "duration_score": 92,
                }
            ],
            source_lyrics="new lyrics",
        )
        try:
            headers = [dialog.table.horizontalHeaderItem(index).text() for index in range(dialog.table.columnCount())]
            self.assertEqual(headers, ["Apply", "Track", "Artist", "Album", "Duration", "Match", "Diff"])
            self.assertNotIn("Title", headers)
            self.assertNotIn("Artist/Time", headers)
            self.assertEqual(dialog.table.objectName(), "LyricsSyncTable")
            self.assertTrue(dialog.table.alternatingRowColors())
            self.assertFalse(dialog.table.showGrid())
            self.assertIsNone(dialog.table.cellWidget(0, 6))
            delegate = dialog.table.itemDelegateForColumn(6)
            self.assertIsInstance(delegate, LyricsDiffButtonDelegate)
            index = dialog.table.model().index(0, 6)
            self.assertTrue(index.data(HAS_LYRICS_ROLE))
            self.assertEqual(dialog.selected_track_ids(), [42])
        finally:
            dialog.deleteLater()

    def test_lyrics_diff_ignores_trailing_whitespace(self):
        self.assertEqual(
            _normalized_diff_lines("[00:01.00] Same line   \n[00:02.00] Next"),
            _normalized_diff_lines("[00:01.00] Same line\n[00:02.00] Next   "),
        )

    def test_browser_publish_lyrics_fields_reject_rich_text_paste(self):
        dialog = _BrowserPublishDialog("https://lrclib.net")
        try:
            self.assertFalse(dialog._pub_synced.acceptRichText())
            self.assertFalse(dialog._pub_plain.acceptRichText())
        finally:
            dialog.deleteLater()

    def test_track_table_keeps_lyrics_status_column_visible(self):
        app_state = simple_app_state()
        widget = TrackListWidget(app_state)
        try:
            self.assertEqual(widget.model.columnCount(), 5)
            self.assertEqual(widget.model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole), "#")
            self.assertEqual(widget.model.headerData(3, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole), "Lyrics")
            self.assertEqual(
                widget.model.headerData(3, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole),
                int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter),
            )
            self.assertFalse(widget.table.isColumnHidden(0))
            self.assertFalse(widget.table.isColumnHidden(3))
            self.assertGreaterEqual(widget.table.columnWidth(0), 50)
            self.assertGreaterEqual(widget.table.columnWidth(2), 90)
            self.assertEqual(widget.header.sectionResizeMode(3), QHeaderView.ResizeMode.Fixed)
            self.assertGreaterEqual(widget.table.columnWidth(3), 100)
        finally:
            widget.deleteLater()
            app_state.db.close()

    def test_download_missing_tooltip_does_not_populate_status_bar(self):
        noop = lambda *args, **kwargs: None
        widget = TopBarController(
            on_refresh=noop,
            on_download_missing=noop,
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
        finally:
            widget.deleteLater()

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
        self.assertGreater(hover_button_sample.value(), hover_row_sample.value())
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

    def test_enter_play_handler_uses_the_focused_track_list(self):
        window = MainWindow.__new__(MainWindow)
        played: list[int] = []
        window.on_play_track = lambda track_id: played.append(int(track_id))
        track_list = SimpleNamespace(selected_track_id=lambda: 42)

        MainWindow._play_selected_from_track_list(window, track_list)

        self.assertEqual(played, [42])

    def test_open_track_folder_opens_parent_directory(self):
        app_state = simple_app_state()
        widget = TrackListWidget(app_state)
        try:
            with TemporaryDirectory() as tmp:
                audio_path = Path(tmp) / "artist" / "song.mp3"
                audio_path.parent.mkdir()
                track = SimpleNamespace(file_path=str(audio_path))

                with patch("ui.widgets.track_list_widget.get_track_by_id", return_value=track), patch(
                    "ui.widgets.track_list_widget.QDesktopServices.openUrl", return_value=True
                ) as open_url:
                    self.assertTrue(widget._open_track_folder(7))

                open_url.assert_called_once()
                self.assertEqual(Path(open_url.call_args.args[0].toLocalFile()), audio_path.parent)
        finally:
            widget.deleteLater()
            app_state.db.close()

    def test_open_track_folder_ignores_missing_path(self):
        app_state = simple_app_state()
        widget = TrackListWidget(app_state)
        try:
            track = SimpleNamespace(file_path="")
            with patch("ui.widgets.track_list_widget.get_track_by_id", return_value=track), patch(
                "ui.widgets.track_list_widget.QDesktopServices.openUrl"
            ) as open_url:
                self.assertFalse(widget._open_track_folder(7))

            open_url.assert_not_called()
        finally:
            widget.deleteLater()
            app_state.db.close()
