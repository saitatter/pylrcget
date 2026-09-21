from __future__ import annotations

import os
import re
import tempfile
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
        _write_text_atomic(txt_path, plain)
        written_paths.append(str(txt_path))
    elif txt_path.exists():
        txt_path.unlink()

    if synced:
        _write_text_atomic(lrc_path, synced)
        written_paths.append(str(lrc_path))
    elif lrc_path.exists():
        lrc_path.unlink()

    return written_paths


def existing_lyrics_sidecar_paths(track: Track, config: Config) -> tuple[str, ...]:
    """Return existing sidecar files matching the configured PyLrcGet patterns.

    This intentionally only returns ``.txt``/``.lrc`` files whose names match
    one of the same candidates used by the scanner or the output writer.  It
    does not recursively search a library directory and it does not delete
    arbitrary text files.
    """
    candidate_names = _candidate_sidecar_names(track, config)
    directories: list[Path] = [Path(track.file_path).parent]

    lookup_subdir = _normalized_lookup_subdir(getattr(config, "lyrics_lookup_subdir", ""))
    if lookup_subdir:
        directories.append(Path(track.file_path).parent / lookup_subdir)

    output_dir = (getattr(config, "lyrics_output_dir", "") or "").strip()
    if output_dir:
        directories.append(Path(output_dir))

    names = {f"{name}{suffix}".casefold() for name in candidate_names for suffix in (".txt", ".lrc")}
    found: dict[str, str] = {}
    for directory in directories:
        try:
            entries = os.scandir(directory)
        except OSError:
            continue
        with entries:
            for entry in entries:
                if entry.name.casefold() not in names:
                    continue
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                normalized = os.path.normcase(os.path.abspath(entry.path))
                found.setdefault(normalized, entry.path)
    return tuple(found.values())


def delete_lyrics_sidecars(track: Track, config: Config) -> tuple[str, ...]:
    """Delete only detected sidecars matching the configured lyric patterns."""
    deleted: list[str] = []
    for path in existing_lyrics_sidecar_paths(track, config):
        Path(path).unlink()
        deleted.append(path)
    return tuple(deleted)


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


def _candidate_sidecar_names(track: Track, config: Config) -> tuple[str, ...]:
    names = [_default_output_name(track)]
    title = _safe_component(track.title)
    artist = _safe_component(track.artist_name)
    album_artist = _safe_component(track.album_artist_name or "")
    track_number = _safe_component(str(track.track_number) if track.track_number is not None else "")

    if title:
        names.append(title)
    if artist and title:
        names.append(f"{artist} - {title}")
    if album_artist and album_artist != artist and title:
        names.append(f"{album_artist} - {title}")
    if track_number and title:
        names.extend((f"{track_number}. {title}", f"{track_number} - {title}"))
        if track.track_number is not None:
            padded = f"{track.track_number:02d}"
            names.extend((f"{padded}. {title}", f"{padded} - {title}"))

    pattern = (getattr(config, "lyrics_file_pattern", "") or "").strip()
    if pattern:
        names.append(_render_pattern(pattern, track))

    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        safe = _safe_component(name)
        key = os.path.normcase(safe)
        if safe and key not in seen:
            seen.add(key)
            unique.append(safe)
    return tuple(unique)


def _normalized_lookup_subdir(value: str | None) -> str:
    raw = (value or "").strip().replace("\\", "/").strip("/")
    if not raw:
        return ""
    parts = [part for part in raw.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return ""
    return str(Path(*parts))


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


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _safe_component(value: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", (value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" .")
    # Reject path traversal components
    if cleaned in ("", ".", ".."):
        return ""
    return cleaned
