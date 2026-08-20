from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class Track:
    id: int
    file_path: str
    file_name: str
    title: str
    album_name: str
    album_artist_name: str | None
    album_id: int
    artist_name: str
    artist_id: int
    image_path: str | None
    track_number: int | None
    txt_lyrics: str | None
    lrc_lyrics: str | None
    duration: float
    instrumental: bool
    dirty_txt_lyrics: str | None = None
    dirty_lrc_lyrics: str | None = None
    dirty_lyrics_present: bool = False

    @staticmethod
    def from_row(row: sqlite3.Row) -> Track:
        # Note: sqlite3.Row doesn't support .get; use "in row.keys()" checks if needed.
        keys = set(row.keys())
        def opt(k: str):
            return row[k] if k in keys else None

        return Track(
            id=row["id"],
            file_path=row["file_path"],
            file_name=row["file_name"],
            title=row["title"],
            artist_name=row["artist_name"],
            artist_id=row["artist_id"],
            album_name=row["album_name"],
            album_artist_name=opt("album_artist_name"),
            album_id=row["album_id"],
            duration=row["duration"],
            track_number=opt("track_number"),
            txt_lyrics=opt("txt_lyrics"),
            lrc_lyrics=opt("lrc_lyrics"),
            dirty_txt_lyrics=opt("dirty_txt_lyrics"),
            dirty_lrc_lyrics=opt("dirty_lrc_lyrics"),
            dirty_lyrics_present=bool(opt("dirty_lyrics_present")),
            image_path=opt("image_path"),
            instrumental=bool(row["instrumental"]),
        )


@dataclass
class Album:
    id: int
    name: str
    image_path: str | None
    artist_name: str
    album_artist_name: str | None
    tracks_count: int

    @staticmethod
    def from_row(row: sqlite3.Row) -> Album:
        keys = set(row.keys())
        def opt(k: str):
            return row[k] if k in keys else None

        return Album(
            id=row["id"],
            name=row["name"],
            image_path=opt("image_path"),
            artist_name=row.get("artist_name") if hasattr(row, "get") else opt("artist_name") or "",
            album_artist_name=opt("album_artist_name"),
            tracks_count=int(opt("tracks_count") or 0),
        )


@dataclass
class Artist:
    id: int
    name: str
    tracks_count: int

    @staticmethod
    def from_row(row: sqlite3.Row) -> Artist:
        keys = set(row.keys())
        def opt(k: str):
            return row[k] if k in keys else None

        return Artist(
            id=row["id"],
            name=row["name"],
            tracks_count=int(opt("tracks_count") or 0),
        )


@dataclass(frozen=True)
class Config:
    skip_tracks_with_synced_lyrics: bool
    skip_tracks_with_plain_lyrics: bool
    download_lyrics_mode: str
    show_line_count: bool
    save_lyrics_sidecars: bool
    lyrics_sidecar_format: str
    try_embed_lyrics: bool
    lyrics_embed_format: str
    theme_mode: str
    ui_scale_percent: int
    font_size_mode: str
    show_album_art: bool
    startup_view: str
    lrclib_instance: str
    lyrics_output_dir: str
    lyrics_file_pattern: str
    lyrics_lookup_subdir: str
    scan_excluded_paths: str
    scan_excluded_patterns: str
    reaction_delay_ms: int
    playback_speed: float
    playback_volume: float
    last_library_route: str
    hotkey_bindings_json: str = ""
    ui_state_json: str = ""
    scan_lyrics_source_mode: str = "both"
    scan_worker_count: int = 4
    logging_verbosity: str = "info"
    ignore_sort_articles: bool = False
