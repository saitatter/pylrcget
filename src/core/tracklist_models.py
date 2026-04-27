# core/tracklist_models.py
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class LyricsState(str, Enum):
    NONE = "none"
    PLAIN = "plain"
    SYNCED = "synced"
    INSTRUMENTAL = "instrumental"


class DownloadState(str, Enum):
    IDLE = "idle"
    LOADING = "loading"
    SUCCESS = "success"
    ERROR = "error"

@dataclass(frozen=True)
class TrackListRow:
    track_id: int
    title: str
    artist: str | None
    artist_id: int | None
    album: str | None
    album_id: int | None
    duration_s: int | None
    lyrics_state: LyricsState
    has_dirty_lyrics: bool = False
    download_state: DownloadState = DownloadState.IDLE
    is_duplicate: bool = False
