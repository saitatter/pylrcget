from __future__ import annotations

from dataclasses import dataclass

from core.embed_lyrics import clear_embedded_lyrics_for_track
from core.lyrics_sidecar import delete_lyrics_sidecars, existing_lyrics_sidecar_paths
from db.models import Config, Track


@dataclass(frozen=True)
class LyricsCleanupOptions:
    clear_library: bool = True
    clear_txt: bool = True
    clear_lrc: bool = True
    delete_sidecars: bool = False
    clear_embedded: bool = False
    clear_embedded_txt: bool = False
    clear_embedded_lrc: bool = False
    discard_drafts: bool = True


@dataclass(frozen=True)
class LyricsCleanupPreview:
    sidecar_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class LyricsCleanupResult:
    track_id: int
    deleted_sidecars: tuple[str, ...] = ()
    embedded_cleared: bool = False
    error: Exception | None = None


def preview_lyrics_cleanup(track: Track, config: Config) -> LyricsCleanupPreview:
    return LyricsCleanupPreview(existing_lyrics_sidecar_paths(track, config))


def apply_file_cleanup(
    track: Track,
    config: Config,
    options: LyricsCleanupOptions,
) -> LyricsCleanupResult:
    deleted_sidecars: tuple[str, ...] = ()
    embedded_cleared = False
    try:
        if options.delete_sidecars:
            deleted_sidecars = delete_lyrics_sidecars(track, config)
        if options.clear_embedded:
            clear_embedded_lyrics_for_track(track)
            embedded_cleared = True
        elif options.clear_embedded_txt or options.clear_embedded_lrc:
            clear_embedded_lyrics_for_track(
                track,
                clear_txt=options.clear_embedded_txt,
                clear_lrc=options.clear_embedded_lrc,
            )
            embedded_cleared = True
    except (OSError, ValueError, RuntimeError) as exc:
        return LyricsCleanupResult(
            track_id=int(track.id),
            deleted_sidecars=deleted_sidecars,
            embedded_cleared=embedded_cleared,
            error=exc,
        )
    return LyricsCleanupResult(
        track_id=int(track.id),
        deleted_sidecars=deleted_sidecars,
        embedded_cleared=embedded_cleared,
    )
