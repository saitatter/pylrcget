from __future__ import annotations

import re
from pathlib import Path

from db.models import Config, Track

DEFAULT_LYRICS_FILE_PATTERN = "{artist} - {title}"
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def export_lyrics_sidecars(track: Track, config: Config) -> list[str]:
    if not config.save_lyrics_sidecars:
        return []

    plain = (track.txt_lyrics or "").strip()
    synced = (track.lrc_lyrics or "").strip()
    plain, synced = _select_lyrics_for_output(
        plain,
        synced,
        getattr(config, "lyrics_sidecar_format", "both"),
    )

    base_path = _resolve_output_base(track, config)
    base_path.parent.mkdir(parents=True, exist_ok=True)

    written_paths: list[str] = []
    txt_path = base_path.parent / f"{base_path.name}.txt"
    lrc_path = base_path.parent / f"{base_path.name}.lrc"

    if plain:
        txt_path.write_text(plain, encoding="utf-8")
        written_paths.append(str(txt_path))
    elif txt_path.exists():
        txt_path.unlink()

    if synced:
        lrc_path.write_text(synced, encoding="utf-8")
        written_paths.append(str(lrc_path))
    elif lrc_path.exists():
        lrc_path.unlink()

    return written_paths


def _select_lyrics_for_output(plain: str, synced: str, output_format: str) -> tuple[str, str]:
    mode = (output_format or "both").strip()
    if mode == "synced_only":
        return "", synced
    if mode == "plain_only":
        return plain, ""
    if mode == "prefer_synced":
        if synced:
            return "", synced
        return plain, ""
    return plain, synced


def _resolve_output_base(track: Track, config: Config) -> Path:
    output_dir = (config.lyrics_output_dir or "").strip()
    if output_dir:
        pattern = (config.lyrics_file_pattern or "").strip()
        if pattern:
            filename = _render_pattern(pattern, track)
        else:
            filename = _default_output_name(track)
        result = Path(output_dir) / filename
        # Prevent path traversal outside the configured output directory
        if not result.resolve().is_relative_to(Path(output_dir).resolve()):
            result = Path(output_dir) / _default_output_name(track)
        return result

    return Path(track.file_path).with_suffix("")


def _render_pattern(pattern: str, track: Track) -> str:
    values = {
        "artist": _safe_component(track.artist_name),
        "title": _safe_component(track.title),
        "album": _safe_component(track.album_name),
        "track": _safe_component(str(track.track_number) if track.track_number is not None else ""),
        "filename": _default_output_name(track),
    }
    try:
        rendered = pattern.format(**values).strip()
    except (KeyError, ValueError, IndexError):
        rendered = ""

    return _safe_component(rendered) or _default_output_name(track)


def _default_output_name(track: Track) -> str:
    file_path = (track.file_path or "").strip()
    if file_path:
        from_path = _safe_component(Path(file_path).stem)
        if from_path:
            return from_path

    file_name = (track.file_name or "").strip()
    if file_name:
        from_name = _safe_component(Path(file_name).stem)
        if from_name:
            return from_name

    return _safe_component(f"{track.artist_name} - {track.title}") or "lyrics"


def _safe_component(value: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", (value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" .")
    # Reject path traversal components
    if cleaned in ("", ".", ".."):
        return ""
    return cleaned
