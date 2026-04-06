from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import sqlite3


@dataclass
class Track:
    id: int
    file_path: str
    file_name: str
    title: str
    album_name: str
    album_artist_name: Optional[str]
    album_id: int
    artist_name: str
    artist_id: int
    image_path: Optional[str]
    track_number: Optional[int]
    txt_lyrics: Optional[str]
    lrc_lyrics: Optional[str]
    duration: float
    instrumental: bool

    @staticmethod
    def from_row(row: sqlite3.Row) -> "Track":
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
            image_path=opt("image_path"),
            instrumental=bool(row["instrumental"]),
        )


@dataclass
class Album:
    id: int
    name: str
    image_path: Optional[str]
    artist_name: str
    album_artist_name: Optional[str]
    tracks_count: int

    @staticmethod
    def from_row(row: sqlite3.Row) -> "Album":
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
    def from_row(row: sqlite3.Row) -> "Artist":
        keys = set(row.keys())
        def opt(k: str):
            return row[k] if k in keys else None

        return Artist(
            id=row["id"],
            name=row["name"],
            tracks_count=int(opt("tracks_count") or 0),
        )


@dataclass
class Config:
    skip_tracks_with_synced_lyrics: bool
    skip_tracks_with_plain_lyrics: bool
    show_line_count: bool
    try_embed_lyrics: bool
    theme_mode: str
    lrclib_instance: str


# Keep FsTrack here too if you already have it in this file.
