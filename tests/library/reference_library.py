from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from library.scan_library import (
    AudioMetadata,
    iter_audio_paths,
    read_audio_metadata_for_scan,
    read_lyrics_for_scan,
)


@dataclass(frozen=True)
class ReferenceTrack:
    file_path: str
    title: str
    artist: str
    album: str
    album_artist: str
    duration: float
    track_number: int | None
    txt_lyrics: str | None
    lrc_lyrics: str | None
    instrumental: bool

    def logical_state(self) -> tuple[object, ...]:
        return (
            self.title,
            self.artist,
            self.album,
            self.album_artist,
            self.duration,
            self.track_number,
            self.txt_lyrics,
            self.lrc_lyrics,
            self.instrumental,
        )


MetadataReader = Callable[[str], tuple[object, AudioMetadata] | None]


class ReferenceLibraryBuilder:
    """Deliberately complete, uncached scanner used as a test oracle."""

    def __init__(self, metadata_reader: MetadataReader = read_audio_metadata_for_scan) -> None:
        self.metadata_reader = metadata_reader

    def build(
        self,
        directories: list[str],
        *,
        lyrics_lookup_subdir: str = "",
        lyrics_file_pattern: str = "",
        scan_lyrics_source_mode: str = "both",
    ) -> dict[str, ReferenceTrack]:
        expected: dict[str, ReferenceTrack] = {}
        for path in iter_audio_paths(directories):
            metadata_result = self.metadata_reader(path)
            if metadata_result is None:
                continue
            audio, metadata = metadata_result
            lyrics = read_lyrics_for_scan(
                path,
                audio=audio,
                lyrics_lookup_subdir=lyrics_lookup_subdir,
                metadata=metadata,
                lyrics_file_pattern=lyrics_file_pattern,
                scan_lyrics_source_mode=scan_lyrics_source_mode,
            )
            lrc_lyrics = lyrics.lrc
            expected[path] = ReferenceTrack(
                file_path=path,
                title=metadata.title,
                artist=metadata.artist,
                album=metadata.album,
                album_artist=metadata.album_artist,
                duration=metadata.duration,
                track_number=metadata.track_number,
                txt_lyrics=lyrics.txt,
                lrc_lyrics=lrc_lyrics,
                instrumental=bool(lrc_lyrics and "[au: instrumental]" in lrc_lyrics.casefold()),
            )
        return expected
