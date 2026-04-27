# core/models.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FsTrack:
    file_path: str
    file_name: str
    title: str
    album: str
    artist: str
    album_artist: str
    duration: float
    txt_lyrics: str | None
    lrc_lyrics: str | None
    track_number: int | None
    modified_time: float | None = None
    file_size: int | None = None
    instrumental: bool = False
