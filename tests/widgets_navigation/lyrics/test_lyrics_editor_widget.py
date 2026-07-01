from tests.widgets_navigation._shared import *


@unittest.skipUnless(HAS_QT, "PySide6 is required for widget tests")
class LyricsEditorWidgetTests(unittest.TestCase):
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

    def test_empty_lyrics_actions_wrap_in_narrow_layouts(self):
        widget = LyricsEditorWidget()
        try:
            widget.resize(420, 520)
            widget.show()
            self.app.processEvents()

            widget.set_track_lyrics("Song", "", "", False)
            self.app.processEvents()

            buttons = [
                widget.empty_state.action,
                widget.empty_state.secondary_action,
                widget.empty_state.tertiary_action,
                widget.empty_state.quaternary_action,
            ]
            visible_buttons = [button for button in buttons if button.isVisible()]
            self.assertEqual(len(visible_buttons), 4)

            y_positions = {button.geometry().y() for button in visible_buttons}

            self.assertGreater(len(y_positions), 1)
        finally:
            widget.hide()
            widget.deleteLater()

    def test_no_selection_toolbar_buttons_remain_fully_visible_in_narrow_layouts(self):
        widget = LyricsEditorWidget()
        try:
            widget.resize(520, 360)
            widget.show()
            self.app.processEvents()

            widget.show_none("Choose a track to review or edit its lyrics.")
            self.app.processEvents()

            toolbar_buttons = [
                widget.btn_snap,
                widget.btn_shift_minus,
                widget.btn_shift_plus,
                widget.btn_shift_selected,
                widget.btn_shift_all_from_first,
                widget.btn_add,
                widget.btn_del,
                widget.btn_save,
                widget.btn_sync_others,
                widget.btn_export_files,
                widget.btn_publish_synced,
                widget.btn_publish_plain,
            ]

            visible_buttons = [button for button in toolbar_buttons if button.isVisible()]
            self.assertTrue(visible_buttons)
            self.assertTrue(all(button.geometry().top() >= 0 for button in visible_buttons))
            self.assertLessEqual(
                max(button.geometry().bottom() for button in visible_buttons),
                widget.stack.geometry().top() + 8,
            )
        finally:
            widget.hide()
            widget.deleteLater()

    def test_lyrics_header_does_not_inflate_minimum_height_hint(self):
        widget = LyricsEditorWidget()
        try:
            widget.resize(720, 640)
            widget.show()
            self.app.processEvents()

            self.assertLess(widget.minimumSizeHint().height(), 400)
        finally:
            widget.hide()
            widget.deleteLater()

    def test_wrapped_lyrics_header_receives_needed_height(self):
        widget = LyricsEditorWidget()
        try:
            widget.resize(480, 420)
            widget.show()
            self.app.processEvents()

            header_layout = widget.header_widget.layout()
            required_height = header_layout.totalHeightForWidth(widget.header_widget.width())

            self.assertGreaterEqual(widget.header_widget.height(), required_height)
        finally:
            widget.hide()
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
            self.assertEqual(widget.table.currentRow(), 1)
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

    def test_clicking_unsynced_zero_timestamps_does_not_seek(self):
        widget = LyricsEditorWidget()
        emitted: list[int] = []
        widget.seekRequested.connect(emitted.append)
        try:
            widget._set_synced([(0, "First line"), (0, "Second line")])

            widget._on_table_clicked_seek(1, 1)

            self.assertEqual(emitted, [])
        finally:
            widget.deleteLater()

    def test_up_down_on_toolbar_button_moves_lyrics_selection(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "First line"), (3000, "Second line"), (5000, "")])
            widget.table.selectRow(0)
            widget.table.setCurrentCell(0, 1)
            event = QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Down,
                Qt.KeyboardModifier.NoModifier,
            )

            self.assertTrue(widget.eventFilter(widget.btn_snap, event))
            self.assertEqual(widget.table.currentRow(), 1)

            event_up = QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Up,
                Qt.KeyboardModifier.NoModifier,
            )
            self.assertTrue(widget.eventFilter(widget.btn_snap, event_up))
            self.assertEqual(widget.table.currentRow(), 0)
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

    def test_ai_sync_manual_anchors_only_include_non_zero_synced_rows(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(0, "First line"), (1500, "Second line"), (4500, "Third line")])

            anchors = widget.ai_sync_manual_anchors()

            self.assertEqual(
                anchors,
                [
                    {"line_index": 1, "time_ms": 1500, "text": "Second line"},
                    {"line_index": 2, "time_ms": 4500, "text": "Third line"},
                ],
            )
        finally:
            widget.deleteLater()

    def test_ai_sync_manual_anchors_empty_in_plain_mode(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_plain("First line\nSecond line")

            anchors = widget.ai_sync_manual_anchors()

            self.assertEqual(anchors, [])
        finally:
            widget.deleteLater()

    def test_ai_sync_plain_source_from_plain_mode(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_plain("Line one\nLine two")
            self.assertEqual(widget.ai_sync_plain_source(), "Line one\nLine two")
        finally:
            widget.deleteLater()

    def test_ai_sync_plain_source_from_synced_mode(self):
        widget = LyricsEditorWidget()
        try:
            widget._set_synced([(1200, "Line one"), (3000, "Line two")])
            self.assertEqual(widget.ai_sync_plain_source(), "Line one\nLine two")
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