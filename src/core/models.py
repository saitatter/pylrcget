# core/models.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class TrackRow:
    track_id: int
    title: str
    artist: str | None
    duration_s: int | None
    lyrics_state: str  # "synced" | "plain" | "instrumental" | "none"

@dataclass(frozen=True)
class TrackFilters:
    synced: bool = True
    plain: bool = True
    instrumental: bool = False
    no_lyrics: bool = True

@dataclass(frozen=True)
class FsTrack:
    file_path: str      # FULL path to audio file (ca în Rust)
    file_name: str      # basename (song.mp3)
    title: str
    album: str
    artist: str
    album_artist: str
    duration: float
    txt_lyrics: str | None
    lrc_lyrics: str | None
    track_number: int | None

    # ca să nu-ți schimbi database.py (care folosește metode)
    def file_path_(self) -> str: return self.file_path
    def file_name_(self) -> str: return self.file_name
    def title_(self) -> str: return self.title
    def album_(self) -> str: return self.album
    def artist_(self) -> str: return self.artist
    def album_artist_(self) -> str: return self.album_artist
    def duration_(self) -> float: return self.duration
    def txt_lyrics_(self) -> str | None: return self.txt_lyrics
    def lrc_lyrics_(self) -> str | None: return self.lrc_lyrics
    def track_number_(self) -> int | None: return self.track_number
