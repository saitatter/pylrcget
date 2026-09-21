from __future__ import annotations

import pytest

from ui.theme_tokens import get_theme_tokens


@pytest.mark.parametrize(
    ("theme", "expected"),
    [
        (
            "DarkTheme",
            {
                "color-success-bg": "#102A20",
                "color-success-border": "#237A50",
                "color-success-text": "#75E0A7",
                "color-warning-bg": "#2B210C",
                "color-warning-border": "#B88214",
                "color-warning-text": "#FEC84B",
                "color-error-bg": "#321414",
                "color-error-border": "#D24A4A",
                "color-error-text": "#FDA29B",
                "color-info-bg": "#10243B",
                "color-info-border": "#316DA8",
                "color-info-text": "#8CC8FF",
            },
        ),
        (
            "LightTheme",
            {
                "color-success-bg": "#ECFDF3",
                "color-success-border": "#ABEFC6",
                "color-success-text": "#067647",
                "color-warning-bg": "#FFFAEB",
                "color-warning-border": "#FEDF89",
                "color-warning-text": "#B54708",
                "color-error-bg": "#FEF3F2",
                "color-error-border": "#FECDCA",
                "color-error-text": "#B42318",
                "color-info-bg": "#EFF8FF",
                "color-info-border": "#B2DDFF",
                "color-info-text": "#175CD3",
            },
        ),
    ],
)
def test_core_theme_semantic_colors_are_palette_aware(theme: str, expected: dict[str, str]) -> None:
    tokens = get_theme_tokens(theme)

    for token, value in expected.items():
        assert tokens[token] == value


def test_optional_theme_keeps_its_palette_mode_for_semantic_fallbacks() -> None:
    tokens = get_theme_tokens("SpotifyTheme")

    assert tokens["palette-mode"] == "dark"
    assert tokens["color-success-bg"] == "#102A20"
