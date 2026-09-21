from db.database import initialize_database
from tests.test_support import qt_app, simple_app_state
from ui.theme_tokens import set_theme_tokens
from ui.widgets.my_lrclib_widget import MyLrclibWidget


def test_my_lrclib_history_status_colors_use_readable_light_theme_text_tokens() -> None:
    set_theme_tokens("LightTheme")
    try:
        assert MyLrclibWidget._kind_color("synced") == "#067647"
        assert MyLrclibWidget._kind_color("plain") == "#B54708"
        assert MyLrclibWidget._download_status_color("synced") == "#067647"
        assert MyLrclibWidget._download_status_color("plain") == "#B54708"
        assert MyLrclibWidget._download_status_color("instrumental") == "#175CD3"
        assert MyLrclibWidget._download_status_color("error") == "#B42318"
    finally:
        set_theme_tokens("DarkTheme")


def test_my_lrclib_tables_keep_only_the_custom_sort_indicator(tmp_path) -> None:
    app = qt_app()
    db = initialize_database(str(tmp_path))
    widget = MyLrclibWidget(simple_app_state(db))
    try:
        assert not widget.publish_table.horizontalHeader().isSortIndicatorShown()
        assert not widget.download_table.horizontalHeader().isSortIndicatorShown()
    finally:
        widget.deleteLater()
        app.processEvents()
        db.close()
