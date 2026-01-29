from dataclasses import dataclass, asdict
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
        return Track(
            id=row["id"],
            file_path=row["file_path"],
            file_name=row["file_name"],
            title=row["title"],
            artist_name=row["artist_name"],
            artist_id=row["artist_id"],
            album_name=row["album_name"],
            album_artist_name=row.get("album_artist_name"),
            album_id=row["album_id"],
            duration=row["duration"],
            track_number=row.get("track_number"),
            txt_lyrics=row.get("txt_lyrics"),
            lrc_lyrics=row.get("lrc_lyrics"),
            image_path=row.get("image_path"),
            instrumental=bool(row["instrumental"])
        )

@dataclass
class Album:
    id: int
    name: str
    image_path: Optional[str]
    artist_name: str
    album_artist_name: Optional[str]
    tracks_count: int

@dataclass
class Artist:
    id: int
    name: str
    tracks_count: int

@dataclass
class Config:
    skip_tracks_with_synced_lyrics: bool
    skip_tracks_with_plain_lyrics: bool
    show_line_count: bool
    try_embed_lyrics: bool
    theme_mode: str
    lrclib_instance: str
