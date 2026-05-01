from __future__ import annotations


DOWNLOAD_MODE_LABELS: dict[str, str] = {
    "prefer_synced": "Prefer synced",
    "synced_only": "Synced only",
    "plain_only": "Plain only",
}


def normalize_download_mode(mode: str | None) -> str:
    value = (mode or "prefer_synced").strip() or "prefer_synced"
    if value not in DOWNLOAD_MODE_LABELS:
        return "prefer_synced"
    return value


def download_mode_label(mode: str | None) -> str:
    return DOWNLOAD_MODE_LABELS[normalize_download_mode(mode)]


def missing_lyrics_summary(mode: str | None) -> str:
    normalized = normalize_download_mode(mode)
    if normalized == "plain_only":
        return "Tracks count as missing when they do not have plain lyrics yet."
    if normalized == "synced_only":
        return "Tracks count as missing when they do not have synced lyrics yet."
    return "Tracks count as missing when they do not have synced lyrics yet, even if plain lyrics already exist."


def missing_lyrics_detail(mode: str | None) -> str:
    normalized = normalize_download_mode(mode)
    if normalized == "plain_only":
        return (
            "Synced results can still be converted into plain lyrics, "
            "but the app will only store the plain version."
        )
    if normalized == "synced_only":
        return "If LRCLIB only has plain lyrics for a track, that match is skipped."
    return "If synced lyrics are unavailable, the app falls back to plain lyrics for that track; only the chosen format is saved."


def download_missing_tooltip(mode: str | None) -> str:
    label = download_mode_label(mode)
    return (
        "Download missing lyrics\n"
        f"Current mode: {label}\n"
        f"{missing_lyrics_summary(mode)}\n"
        f"{missing_lyrics_detail(mode)}"
    )


def no_missing_tracks_message(mode: str | None) -> str:
    label = download_mode_label(mode)
    return f"No tracks are missing lyrics for {label}. {missing_lyrics_summary(mode)}"
