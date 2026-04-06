from __future__ import annotations

from copy import deepcopy


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {alpha:.3f})"


def _theme(
    *,
    name: str,
    bg_app: str,
    bg_panel: str,
    bg_control: str,
    bg_elevated: str,
    bg_pressed: str,
    border: str,
    border_strong: str,
    accent: str,
    text: str,
    text_strong: str,
    text_muted: str,
    text_soft: str,
    palette_mode: str,
    accent_alt: str | None = None,
    font_family: str = "'Segoe UI', 'Segoe UI Variable Text', system-ui, sans-serif",
    radius_scale: str = "default",
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    accent_alt = accent_alt or accent
    theme = {
        "theme-name": name,
        "palette-mode": palette_mode,
        "font-family-base": font_family,
        "color-bg-app": bg_app,
        "color-bg-panel": bg_panel,
        "color-bg-control": bg_control,
        "color-bg-elevated": bg_elevated,
        "color-bg-pressed": bg_pressed,
        "color-border": border,
        "color-border-strong": border_strong,
        "color-border-hover": accent,
        "color-accent": accent,
        "color-accent-alt": accent_alt,
        "color-text": text,
        "color-text-strong": text_strong,
        "color-text-muted": text_muted,
        "color-text-soft": text_soft,
        "color-placeholder": text_muted,
        "color-selection-bg": _rgba(accent, 0.18 if palette_mode == "dark" else 0.14),
        "color-selection-text": text_strong,
        "color-menu-hover": bg_elevated,
        "color-scrollbar-track": bg_app,
        "color-scrollbar-handle": border,
        "color-scrollbar-hover": accent,
        "color-disabled-text": "#6b7280" if palette_mode == "dark" else "#9ca3af",
        "color-disabled-bg": bg_pressed,
        "color-disabled-border": border_strong,
        "color-success-bg": "#052e1a",
        "color-success-border": "#16a34a",
        "color-success-text": "#dcfce7",
        "color-error-bg": "#2a0a0a",
        "color-error-border": "#ef4444",
        "color-error-text": "#fee2e2",
        "color-warning-bg": "#2a1a05",
        "color-warning-border": "#f59e0b",
        "color-warning-text": "#fde68a",
        "color-table-bg": bg_app,
        "color-table-alt": bg_panel,
        "color-table-grid": bg_app,
        "color-table-header": bg_app,
        "color-table-header-hover": bg_control,
        "color-table-header-text": text_muted,
        "color-table-header-text-hover": text,
        "color-table-row-hover": _rgba(accent, 0.10 if palette_mode == "dark" else 0.08),
        "color-cover-border": border,
        "color-slider-fill-start": accent,
        "color-slider-fill-end": accent_alt,
        "color-slider-handle-border": text_strong,
        "color-empty-title": text_strong,
        "color-empty-body": text_muted,
        "color-validation-bg": bg_pressed,
        "color-validation-border": border,
    }

    if radius_scale == "round":
        theme.update({
            "radius-sm": "10px",
            "radius-md": "14px",
            "radius-lg": "18px",
            "radius-xl": "22px",
            "radius-pill": "999px",
        })
    elif radius_scale == "sharp":
        theme.update({
            "radius-sm": "6px",
            "radius-md": "8px",
            "radius-lg": "10px",
            "radius-xl": "12px",
            "radius-pill": "999px",
        })
    else:
        theme.update({
            "radius-sm": "8px",
            "radius-md": "10px",
            "radius-lg": "14px",
            "radius-xl": "16px",
            "radius-pill": "999px",
        })

    if extra:
        theme.update(extra)
    return theme


THEMES = {
    "LightTheme": _theme(
        name="Light",
        bg_app="#fafafa",
        bg_panel="#ffffff",
        bg_control="#f3f4f6",
        bg_elevated="#ffffff",
        bg_pressed="#e5e7eb",
        border="#d1d5db",
        border_strong="#cbd5e1",
        accent="#3f51b5",
        accent_alt="#5f5fc4",
        text="#111827",
        text_strong="#030712",
        text_muted="#6b7280",
        text_soft="#4b5563",
        palette_mode="light",
    ),
    "DarkTheme": _theme(
        name="Dark",
        bg_app="#303030",
        bg_panel="#343434",
        bg_control="#3a3a3a",
        bg_elevated="#424242",
        bg_pressed="#262626",
        border="#4b5563",
        border_strong="#1f2937",
        accent="#90caf9",
        accent_alt="#0085ff",
        text="#e5e7eb",
        text_strong="#ffffff",
        text_muted="#cbd5e1",
        text_soft="#94a3b8",
        palette_mode="dark",
    ),
    "AmusicTheme": _theme(
        name="AMusic",
        bg_app="#111111",
        bg_panel="#1a1a1a",
        bg_control="#1d1d1d",
        bg_elevated="#242424",
        bg_pressed="#2c2c2c",
        border="#3a3a3a",
        border_strong="#2a2a2a",
        accent="#ff4e6b",
        accent_alt="#D60017",
        text="#eeeeee",
        text_strong="#ffffff",
        text_muted="#b3b3b3",
        text_soft="#cccccc",
        palette_mode="dark",
    ),
    "CatppuccinMacchiatoTheme": _theme(
        name="Catppuccin Macchiato",
        bg_app="#1e2030",
        bg_panel="#24273a",
        bg_control="#303347",
        bg_elevated="#363a4f",
        bg_pressed="#1b1d2b",
        border="#494d64",
        border_strong="#363a4f",
        accent="#c6a0f6",
        accent_alt="#8aadf4",
        text="#cad3f5",
        text_strong="#f4f4fa",
        text_muted="#8aadf4",
        text_soft="#a5adcb",
        palette_mode="dark",
        radius_scale="round",
    ),
    "DraculaTheme": _theme(
        name="Dracula",
        bg_app="#282a36",
        bg_panel="#21222c",
        bg_control="#44475a",
        bg_elevated="#383a4a",
        bg_pressed="#191a21",
        border="#6272a4",
        border_strong="#44475a",
        accent="#bd93f9",
        accent_alt="#50fa7b",
        text="#f8f8f2",
        text_strong="#ffffff",
        text_muted="#8be9fd",
        text_soft="#f1fa8c",
        palette_mode="dark",
        extra={
            "color-table-row-hover": _rgba("#ff79c6", 0.18),
            "color-empty-body": "#8be9fd",
            "color-slider-fill-start": "#bd93f9",
            "color-slider-fill-end": "#50fa7b",
        },
    ),
    "ElectricPurpleTheme": _theme(
        name="Electric Purple",
        bg_app="#1f1230",
        bg_panel="#2c1646",
        bg_control="#401a66",
        bg_elevated="#530099",
        bg_pressed="#32124f",
        border="#6d28d9",
        border_strong="#4c1d95",
        accent="#bf00ff",
        accent_alt="#ff3f00",
        text="#f5eaff",
        text_strong="#ffffff",
        text_muted="#f757ff",
        text_soft="#ffff82",
        palette_mode="dark",
        extra={
            "color-table-row-hover": _rgba("#ff763a", 0.20),
            "color-slider-fill-end": "#fff14e",
        },
    ),
    "ExtraDarkTheme": _theme(
        name="Extra Dark",
        bg_app="#000000",
        bg_panel="#050505",
        bg_control="#0d0d0d",
        bg_elevated="#151515",
        bg_pressed="#080808",
        border="#202020",
        border_strong="#101010",
        accent="#0f60b6",
        accent_alt="#0f60b6",
        text="#eeeeee",
        text_strong="#ffffff",
        text_muted="#909090",
        text_soft="#737373",
        palette_mode="dark",
        radius_scale="sharp",
    ),
    "GreenTheme": _theme(
        name="Green",
        bg_app="#202124",
        bg_panel="#2b2d31",
        bg_control="#32353b",
        bg_elevated="#3a3f45",
        bg_pressed="#25282d",
        border="#3f4a42",
        border_strong="#2b332e",
        accent="#4caf50",
        accent_alt="#2e7d32",
        text="#eeeeee",
        text_strong="#ffffff",
        text_muted="#b7d7b8",
        text_soft="#9fb89f",
        palette_mode="dark",
    ),
    "GruvboxDarkTheme": _theme(
        name="Gruvbox Dark",
        bg_app="#282828",
        bg_panel="#32302f",
        bg_control="#3c3836",
        bg_elevated="#49483e",
        bg_pressed="#1f1f1f",
        border="#5a524c",
        border_strong="#3c3836",
        accent="#8ec07c",
        accent_alt="#458588",
        text="#ebdbb2",
        text_strong="#f9f5d7",
        text_muted="#bdae93",
        text_soft="#a89984",
        palette_mode="dark",
        extra={
            "color-table-row-hover": _rgba("#cc241d", 0.16),
        },
    ),
    "LigeraTheme": _theme(
        name="Ligera",
        bg_app="#f0f2f5",
        bg_panel="#ffffff",
        bg_control="#f8fafc",
        bg_elevated="#ffffff",
        bg_pressed="#e5e7eb",
        border="#cccccc",
        border_strong="#d6d9df",
        accent="#0054df",
        accent_alt="#224bff",
        text="#232323",
        text_strong="#0a0a0a",
        text_muted="#656565",
        text_soft="#464646",
        palette_mode="light",
        radius_scale="round",
        font_family="'Segoe UI Variable Text', 'Segoe UI', system-ui, sans-serif",
    ),
    "MonokaiTheme": _theme(
        name="Monokai",
        bg_app="#272822",
        bg_panel="#2d2e27",
        bg_control="#3b3a32",
        bg_elevated="#49483e",
        bg_pressed="#1f201b",
        border="#5a574d",
        border_strong="#3b3a32",
        accent="#66d9ef",
        accent_alt="#f92672",
        text="#f8f8f2",
        text_strong="#ffffff",
        text_muted="#a6a28c",
        text_soft="#f92672",
        palette_mode="dark",
    ),
    "NautilineTheme": _theme(
        name="Nautiline",
        bg_app="#ffffff",
        bg_panel="#f5f5f7",
        bg_control="#ffffff",
        bg_elevated="#e5e5ea",
        bg_pressed="#dfe3e8",
        border="#d1d5db",
        border_strong="#c7ccd1",
        accent="#009688",
        accent_alt="#32b8aa",
        text="#1a1a1a",
        text_strong="#000000",
        text_muted="#8e8e93",
        text_soft="#6b7280",
        palette_mode="light",
        radius_scale="round",
        font_family="'Segoe UI Variable Display', 'Segoe UI', system-ui, sans-serif",
        extra={
            "color-bg-panel": "#f5f5f7",
            "color-bg-control": "#ffffff",
            "color-menu-hover": "#e5e5ea",
            "color-table-alt": "#f5f5f7",
        },
    ),
    "NordTheme": _theme(
        name="Nord",
        bg_app="#2e3440",
        bg_panel="#3b4252",
        bg_control="#434c5e",
        bg_elevated="#4c566a",
        bg_pressed="#252b36",
        border="#5e81ac",
        border_strong="#4c566a",
        accent="#81a1c1",
        accent_alt="#5e81ac",
        text="#d8dee9",
        text_strong="#eceff4",
        text_muted="#b5c0d0",
        text_soft="#aebbcf",
        palette_mode="dark",
    ),
    "NuclearTheme": _theme(
        name="Nuclear",
        bg_app="#1d2021",
        bg_panel="#282828",
        bg_control="#32302f",
        bg_elevated="#3a3530",
        bg_pressed="#141617",
        border="#665c54",
        border_strong="#4f463f",
        accent="#b8bb26",
        accent_alt="#c44129",
        text="#ebdbb2",
        text_strong="#f9f5d7",
        text_muted="#bdae93",
        text_soft="#c44129",
        palette_mode="dark",
        extra={
            "color-table-row-hover": _rgba("#c44129", 0.16),
        },
    ),
    "NutballTheme": _theme(
        name="Nutball",
        bg_app="#fafafa",
        bg_panel="#ffffff",
        bg_control="#f3f4f6",
        bg_elevated="#ffffff",
        bg_pressed="#e5e7eb",
        border="#e0e0e0",
        border_strong="#d6d6d6",
        accent="#80ea00",
        accent_alt="#53b700",
        text="#111111",
        text_strong="#000000",
        text_muted="#6b7280",
        text_soft="#4b5563",
        palette_mode="light",
        radius_scale="round",
    ),
    "SpotifyTheme": _theme(
        name="Spotify-ish",
        bg_app="#121212",
        bg_panel="#171717",
        bg_control="#181818",
        bg_elevated="#282828",
        bg_pressed="#1d1d1d",
        border="#28282b",
        border_strong="#000000",
        accent="#1db954",
        accent_alt="#62ec83",
        text="#ffffff",
        text_strong="#ffffff",
        text_muted="#b3b3b3",
        text_soft="#c2c1c2",
        palette_mode="dark",
        font_family="system-ui, 'Helvetica Neue', Helvetica, Arial, sans-serif",
        radius_scale="round",
        extra={
            "radius-md": "18px",
            "radius-lg": "20px",
            "color-table-row-hover": _rgba("#1db954", 0.12),
        },
    ),
    "SquiddiesGlassTheme": _theme(
        name="Squiddies Glass",
        bg_app="#181818",
        bg_panel="#1d1d1d",
        bg_control="#282828",
        bg_elevated="#33213b",
        bg_pressed="#23162a",
        border="#5e3a66",
        border_strong="#402448",
        accent="#c231ab",
        accent_alt="#380eff",
        text="#fbe3f4",
        text_strong="#ffffff",
        text_muted="#f5b9e3",
        text_soft="#c2c1c2",
        palette_mode="dark",
        radius_scale="round",
        extra={
            "color-bg-panel": "rgba(29, 29, 29, 0.88)",
            "color-table-row-hover": _rgba("#c231ab", 0.18),
            "color-menu-hover": _rgba("#e14ac2", 0.15),
        },
    ),
}

FONT_TOKENS = {
    "font-size-xs": "10px",
    "font-size-sm": "11px",
    "font-size-md": "12px",
    "font-size-lg": "14px",
}

SPACE_TOKENS = {
    "space-1": "4px",
    "space-2": "8px",
    "space-3": "12px",
    "space-4": "16px",
}


def get_available_themes() -> list[tuple[str, str]]:
    return [("auto", "Auto")] + [(key, theme["theme-name"]) for key, theme in THEMES.items()]


def resolve_theme_key(theme_mode: str | None, *, prefers_dark: bool | None = None) -> str:
    if theme_mode == "auto":
        if prefers_dark is False:
            return "LightTheme"
        return "DarkTheme"
    if theme_mode in THEMES:
        return str(theme_mode)
    return "DarkTheme"


def get_theme_tokens(theme_mode: str | None, *, prefers_dark: bool | None = None) -> dict[str, str]:
    tokens = deepcopy(THEMES[resolve_theme_key(theme_mode, prefers_dark=prefers_dark)])
    tokens.update(FONT_TOKENS)
    tokens.update(SPACE_TOKENS)
    return tokens


STYLE_TOKENS: dict[str, str] = {}


def set_theme_tokens(theme_mode: str | None, *, prefers_dark: bool | None = None) -> dict[str, str]:
    STYLE_TOKENS.clear()
    STYLE_TOKENS.update(get_theme_tokens(theme_mode, prefers_dark=prefers_dark))
    return STYLE_TOKENS


set_theme_tokens("DarkTheme")
