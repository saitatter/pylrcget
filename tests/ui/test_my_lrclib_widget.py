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
