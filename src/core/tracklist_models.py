# core/tracklist_models.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class TrackListRow:
    track_id: int
    title: str
    artist: str | None
    duration_s: int | None
    lyrics_state: str  # synced/plain/instrumental/none
