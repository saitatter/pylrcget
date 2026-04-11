from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlbumListRow:
    album_ids: tuple[int, ...]
    album: str
    artist: str | None
    track_count: int


@dataclass(frozen=True)
class ArtistListRow:
    artist_ids: tuple[int, ...]
    artist: str
    albums: int
    tracks: int
