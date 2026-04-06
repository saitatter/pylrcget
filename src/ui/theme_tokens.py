from __future__ import annotations


COLOR_TOKENS = {
    "color-bg-app": "#020617",
    "color-bg-panel": "#040b19",
    "color-bg-control": "#0b1222",
    "color-bg-elevated": "#111827",
    "color-bg-pressed": "#0f172a",
    "color-border": "#1f2937",
    "color-border-strong": "#111827",
    "color-accent": "#38bdf8",
    "color-text": "#e5e7eb",
    "color-text-strong": "#f8fafc",
    "color-text-muted": "#94a3b8",
    "color-text-soft": "#9ca3af",
}

RADIUS_TOKENS = {
    "radius-sm": "8px",
    "radius-md": "10px",
    "radius-lg": "14px",
    "radius-xl": "16px",
    "radius-pill": "999px",
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


STYLE_TOKENS = {}
STYLE_TOKENS.update(COLOR_TOKENS)
STYLE_TOKENS.update(RADIUS_TOKENS)
STYLE_TOKENS.update(FONT_TOKENS)
STYLE_TOKENS.update(SPACE_TOKENS)
