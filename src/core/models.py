# core/models.py
from __future__ import annotations

from dataclasses import dataclass

from core.tracklist_models import LyricsState


@dataclass(frozen=True)
class TrackRow:
    track_id: int
    title: str
    artist: str | None
    duration_s: int | None
    lyrics_state: LyricsState


@dataclass(frozen=True)
class TrackFilters:
    synced: bool = True
    plain: bool = True
    instrumental: bool = False
    no_lyrics: bool = True


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
