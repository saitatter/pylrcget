# src/library/scan_library.py
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen._util import MutagenError
from mutagen.id3 import ID3, ID3NoHeaderError
from mutagen.musepack import Musepack

from core.embed_lyrics import (
    ID3_SYNCED_DESC,
    MP4_PLAIN_KEY,
    MP4_SYNCED_KEY,
    VORBIS_PLAIN_KEY,
    VORBIS_SYNCED_KEY,
)
from core.models import FsTrack
from library.scan_state import TRACK_SCAN_STATE_SIGNATURE_VERSION

logger = logging.getLogger(__name__)

AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".wma", ".asf", ".dsf", ".dff", ".mpc"}
SCAN_LYRICS_SOURCE_BOTH = "both"
SCAN_LYRICS_SOURCE_EMBEDDED_ONLY = "embedded_only"
SCAN_LYRICS_SOURCE_SIDECAR_ONLY = "sidecar_only"

ASF_PLAIN_KEYS = ("WM/Lyrics", "LYRICS", "UNSYNCEDLYRICS")
ASF_SYNCED_KEYS = ("LRCLIB_LRC", "SYNCEDLYRICS")
APE_PLAIN_KEYS = ("UNSYNCEDLYRICS", "lyrics")
APE_SYNCED_KEYS = ("LYRICS", "LRCLIB_LRC")


@dataclass(frozen=True)
class AudioMetadata:
    title: str
    album: str
    artist: str
    album_artist: str
    track_number: int | None
    duration: float


@dataclass(frozen=True)
class SidecarScanState:
    signature: str
    txt_present: bool
    lrc_present: bool


class SidecarLookupCache:
    def __init__(self) -> None:
        self._dir_entries: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    def _dir_key(self, directory: str) -> str:
        return os.path.normcase(os.path.abspath(directory))

    def candidate_exists(self, candidate: str) -> bool:
        return self.resolve_existing(candidate) is not None

    def resolve_existing(self, candidate: str) -> str | None:
        directory, filename = os.path.split(candidate)
        if not directory or not filename:
            return None

        dir_key = self._dir_key(directory)
        with self._lock:
            entries = self._dir_entries.get(dir_key)
        if entries is None:
            try:
                names = os.listdir(directory)
            except OSError:
                names = []
            entries = {os.path.normcase(name): name for name in names}
            with self._lock:
                self._dir_entries.setdefault(dir_key, entries)
        actual_name = entries.get(os.path.normcase(filename))
        if actual_name is None:
            return None
        return os.path.join(directory, actual_name)


def _read_vorbis_lyrics(audio) -> tuple[str | None, str | None]:
    plain_list = audio.get(VORBIS_PLAIN_KEY)
    synced_list = audio.get(VORBIS_SYNCED_KEY)
    plain = (plain_list[0] if isinstance(plain_list, (list, tuple)) and plain_list else None)
    synced = (synced_list[0] if isinstance(synced_list, (list, tuple)) and synced_list else None)
    return plain, synced


def _first_managed_uslt_text(tags: ID3) -> str | None:
    getall = getattr(tags, "getall", None)
    if not callable(getall):
        return None
    managed_frames = [
        frame
        for frame in getall("USLT")
        if getattr(frame, "lang", "") == "und" and getattr(frame, "desc", "") == ""
    ]
    frames = managed_frames or getall("USLT")
    if not frames:
        return None
    text = getattr(frames[0], "text", None)
    if isinstance(text, (list, tuple)) and text:
        return str(text[0])
    if isinstance(text, str):
        return text
    return None


def _first_id3_synced_lrc(tags: ID3) -> str | None:
    """Read PyLrcGet's TXXX LRC or convert a standard ID3 SYLT frame."""
    getall = getattr(tags, "getall", None)
    if not callable(getall):
        return None

    for frame in getall("TXXX"):
        if getattr(frame, "desc", "") != ID3_SYNCED_DESC:
            continue
        text = getattr(frame, "text", None)
        if isinstance(text, (list, tuple)) and text:
            return str(text[0])
        if isinstance(text, str) and text.strip():
            return text

    for frame in getall("SYLT"):
        if getattr(frame, "format", 2) != 2:
            continue
        entries = getattr(frame, "text", None)
        if not isinstance(entries, (list, tuple)):
            continue
        output: list[str] = []
        for entry in entries:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            text, timestamp_ms = entry[0], entry[1]
            text = str(text).strip()
            if not text:
                continue
            try:
                seconds = max(0.0, float(timestamp_ms) / 1000.0)
            except (TypeError, ValueError):
                continue
            total_centiseconds = round(seconds * 100)
            minutes, centiseconds = divmod(total_centiseconds, 6000)
            for line in text.splitlines() or [text]:
                line = line.strip()
                if line:
                    output.append(
                        f"[{int(minutes):02d}:{centiseconds // 100:02d}."
                        f"{centiseconds % 100:02d}] {line}"
                    )
        if output:
            return "\n".join(output)
    return None


def _split_lines(block: str | None) -> list[str]:
    return [line.strip() for line in (block or "").splitlines() if line.strip()]


def _path_variants(path: str) -> tuple[str, str]:
    normalized = os.path.normcase(os.path.abspath(os.path.expanduser(path)))
    posix = normalized.replace("\\", "/")
    return normalized, posix


def _join_normalized_path(dir_normalized: str, filename: str) -> tuple[str, str]:
    normalized = os.path.normcase(os.path.join(dir_normalized, filename))
    return normalized, normalized.replace("\\", "/")


def _normalize_excluded_paths(excluded_paths: str | None) -> list[tuple[str, str]]:
    normalized: list[tuple[str, str]] = []
    for entry in _split_lines(excluded_paths):
        native, posix = _path_variants(entry)
        normalized.append((native.rstrip("/\\"), posix.rstrip("/")))
    return normalized


def _compile_excluded_patterns(excluded_patterns: str | None) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in _split_lines(excluded_patterns):
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            logger.warning("Ignoring invalid scan exclusion regex: %s", pattern)
    return compiled


def _is_path_excluded_variants(
    path: str,
    normalized_path: str,
    posix_path: str,
    excluded_roots: list[tuple[str, str]],
    excluded_patterns: list[re.Pattern[str]],
) -> bool:
    for root_native, root_posix in excluded_roots:
        if normalized_path == root_native or normalized_path.startswith(root_native + os.sep):
            return True
        if posix_path == root_posix or posix_path.startswith(root_posix + "/"):
            return True

    for pattern in excluded_patterns:
        if pattern.search(path) or pattern.search(posix_path):
            return True

    return False


def _iter_audio_paths_core(
    directories: list[str],
    *,
    excluded_paths: str | None = None,
    excluded_patterns: str | None = None,
) -> tuple[
    list[str],
    dict[str, tuple[float | None, int | None]],
    dict[str, tuple[int | None, int | None]],
]:
    excluded_roots = _normalize_excluded_paths(excluded_paths)
    compiled_patterns = _compile_excluded_patterns(excluded_patterns)
    paths: list[str] = []
    signatures: dict[str, tuple[float | None, int | None]] = {}
    audio_signatures_ns: dict[str, tuple[int | None, int | None]] = {}
    seen: set[str] = set()
    for root in directories:
        if not root or not os.path.isdir(root):
            continue
        stack = [root]
        while stack:
            dirpath = stack.pop()
            normalized_dir, posix_dir = _path_variants(dirpath)
            if _is_path_excluded_variants(dirpath, normalized_dir, posix_dir, excluded_roots, compiled_patterns):
                continue

            child_dirs: list[str] = []
            try:
                with os.scandir(dirpath) as it:
                    for entry in it:
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            continue

                        if is_dir:
                            child_path = entry.path
                            child_normalized, child_posix = _join_normalized_path(normalized_dir, entry.name)
                            if _is_path_excluded_variants(child_path, child_normalized, child_posix, excluded_roots, compiled_patterns):
                                continue
                            child_dirs.append(child_path)
                            continue

                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext not in AUDIO_EXTS:
                            continue
                        file_path = entry.path
                        normalized, posix_path = _join_normalized_path(normalized_dir, entry.name)
                        if normalized in seen:
                            continue
                        if not _is_path_excluded_variants(file_path, normalized, posix_path, excluded_roots, compiled_patterns):
                            seen.add(normalized)
                            paths.append(file_path)
                            try:
                                stat = entry.stat(follow_symlinks=False)
                            except OSError:
                                pass
                            else:
                                signatures[file_path] = (float(stat.st_mtime), int(stat.st_size))
                                audio_signatures_ns[file_path] = (int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                continue

            stack.extend(reversed(child_dirs))
    return paths, signatures, audio_signatures_ns


def iter_audio_paths(
    directories: list[str],
    *,
    excluded_paths: str | None = None,
    excluded_patterns: str | None = None,
) -> list[str]:
    paths, _signatures, _audio_signatures_ns = _iter_audio_paths_core(
        directories,
        excluded_paths=excluded_paths,
        excluded_patterns=excluded_patterns,
    )
    return paths


def iter_audio_paths_with_signatures(
    directories: list[str],
    *,
    excluded_paths: str | None = None,
    excluded_patterns: str | None = None,
) -> tuple[list[str], dict[str, tuple[float | None, int | None]]]:
    paths, signatures, _audio_signatures_ns = _iter_audio_paths_core(
        directories,
        excluded_paths=excluded_paths,
        excluded_patterns=excluded_patterns,
    )
    return paths, signatures


def iter_audio_paths_with_audio_signatures(
    directories: list[str],
    *,
    excluded_paths: str | None = None,
    excluded_patterns: str | None = None,
) -> tuple[list[str], dict[str, tuple[int | None, int | None]]]:
    """Enumerate audio and return an ns-precision audio-only signature."""
    paths, _signatures, audio_signatures_ns = _iter_audio_paths_core(
        directories,
        excluded_paths=excluded_paths,
        excluded_patterns=excluded_patterns,
    )
    return paths, audio_signatures_ns


def preview_audio_path_exclusions(
    directories: list[str],
    *,
    excluded_paths: str | None = None,
    excluded_patterns: str | None = None,
) -> tuple[list[str], list[str]]:
    excluded_roots = _normalize_excluded_paths(excluded_paths)
    compiled_patterns = _compile_excluded_patterns(excluded_patterns)
    included: list[str] = []
    excluded: list[str] = []
    seen: set[str] = set()

    for root in directories:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            normalized_dir, posix_dir = _path_variants(dirpath)
            if _is_path_excluded_variants(dirpath, normalized_dir, posix_dir, excluded_roots, compiled_patterns):
                dirnames[:] = []
                continue

            kept_dirnames: list[str] = []
            for dirname in dirnames:
                child_path = os.path.join(dirpath, dirname)
                child_normalized, child_posix = _join_normalized_path(normalized_dir, dirname)
                if _is_path_excluded_variants(child_path, child_normalized, child_posix, excluded_roots, compiled_patterns):
                    continue
                kept_dirnames.append(dirname)
            dirnames[:] = kept_dirnames

            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in AUDIO_EXTS:
                    continue
                file_path = os.path.join(dirpath, fn)
                normalized, posix_path = _join_normalized_path(normalized_dir, fn)
                if normalized in seen:
                    continue
                seen.add(normalized)
                if _is_path_excluded_variants(file_path, normalized, posix_path, excluded_roots, compiled_patterns):
                    excluded.append(file_path)
                else:
                    included.append(file_path)

    return included, excluded


def get_audio_file_signature(
    path: str,
    lyrics_lookup_subdir: str | None = None,
    *,
    metadata: AudioMetadata | None = None,
    lyrics_file_pattern: str | None = None,
    scan_lyrics_source_mode: str | None = None,
    audio_signature: tuple[float | None, int | None] | None = None,
    sidecar_lookup_cache: SidecarLookupCache | None = None,
    timing_hook: Callable[[str, float], None] | None = None,
    count_hook: Callable[[str, int], None] | None = None,
) -> tuple[float | None, int | None]:
    return get_audio_file_signature_with_lookup(
        path,
        lyrics_lookup_subdir,
        metadata=metadata,
        lyrics_file_pattern=lyrics_file_pattern,
        scan_lyrics_source_mode=scan_lyrics_source_mode,
        audio_signature=audio_signature,
        sidecar_lookup_cache=sidecar_lookup_cache,
        timing_hook=timing_hook,
        count_hook=count_hook,
    )


def _normalized_lyrics_lookup_subdir(lyrics_lookup_subdir: str | None) -> str:
    raw = (lyrics_lookup_subdir or "").strip().replace("\\", "/")
    if not raw:
        return ""
    if os.path.isabs(raw) or re.match(r"^[a-zA-Z]:", raw):
        return ""
    parts = [part.strip() for part in raw.split("/") if part.strip() not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        return ""
    return os.path.join(*parts)


def _normalize_scan_lyrics_source_mode(mode: str | None) -> str:
    value = (mode or SCAN_LYRICS_SOURCE_BOTH).strip().lower()
    if value in {"embedded", "embedded_only", "embedded-only"}:
        return SCAN_LYRICS_SOURCE_EMBEDDED_ONLY
    if value in {"sidecar", "sidecar_only", "sidecar-only"}:
        return SCAN_LYRICS_SOURCE_SIDECAR_ONLY
    return SCAN_LYRICS_SOURCE_BOTH


def _scan_lyrics_source_flags(mode: str | None) -> tuple[bool, bool]:
    normalized = _normalize_scan_lyrics_source_mode(mode)
    if normalized == SCAN_LYRICS_SOURCE_EMBEDDED_ONLY:
        return True, False
    if normalized == SCAN_LYRICS_SOURCE_SIDECAR_ONLY:
        return False, True
    return True, True


def get_audio_file_signature_with_lookup(
    path: str,
    lyrics_lookup_subdir: str | None = None,
    *,
    metadata: AudioMetadata | None = None,
    lyrics_file_pattern: str | None = None,
    scan_lyrics_source_mode: str | None = None,
    audio_signature: tuple[float | None, int | None] | None = None,
    sidecar_lookup_cache: SidecarLookupCache | None = None,
    timing_hook: Callable[[str, float], None] | None = None,
    count_hook: Callable[[str, int], None] | None = None,
) -> tuple[float | None, int | None]:
    _use_embedded, use_sidecar = _scan_lyrics_source_flags(scan_lyrics_source_mode)
    newest_mtime: float | None = None
    total_size = 0
    sidecar_candidates: list[str] = []
    if use_sidecar:
        for base in _sidecar_base_candidates(
            path,
            lyrics_lookup_subdir,
            metadata=metadata,
            lyrics_file_pattern=lyrics_file_pattern,
        ):
            sidecar_candidates.extend([base + ".txt", base + ".lrc"])

    if count_hook is not None:
        count_hook("signature_sidecar_candidate_count", len(sidecar_candidates))

    if audio_signature is not None:
        newest_mtime, total_size = audio_signature
    else:
        audio_started = time.perf_counter()
        try:
            stat = os.stat(path)
        except OSError:
            stat = None
        if timing_hook is not None:
            timing_hook("signature_audio_stat_s", time.perf_counter() - audio_started)
        if stat is not None:
            newest_mtime = float(stat.st_mtime)
            total_size += int(stat.st_size)

    if use_sidecar:
        sidecar_started = time.perf_counter()
        for candidate in sidecar_candidates:
            if sidecar_lookup_cache is not None and not sidecar_lookup_cache.candidate_exists(candidate):
                continue
            try:
                stat = os.stat(candidate)
            except OSError:
                continue
            candidate_mtime = float(stat.st_mtime)
            newest_mtime = candidate_mtime if newest_mtime is None else max(newest_mtime, candidate_mtime)
            total_size += int(stat.st_size)
        if timing_hook is not None:
            timing_hook("signature_sidecar_stat_s", time.perf_counter() - sidecar_started)
    elif timing_hook is not None:
        timing_hook("signature_sidecar_stat_s", 0.0)

    return newest_mtime, total_size if newest_mtime is not None else None


def get_audio_signature(
    path: str,
    *,
    audio_signature: tuple[int | None, int | None] | None = None,
    timing_hook: Callable[[str, float], None] | None = None,
) -> tuple[int | None, int | None]:
    """Return the audio-only fingerprint used by the incremental scanner."""
    if audio_signature is not None:
        return audio_signature

    started = time.perf_counter()
    try:
        stat = os.stat(path)
    except OSError:
        result = (None, None)
    else:
        result = (int(stat.st_mtime_ns), int(stat.st_size))
    if timing_hook is not None:
        timing_hook("audio_signature_stat_s", time.perf_counter() - started)
    return result

def _first(easy, key: str) -> str | None:
    v = easy.get(key)
    if not v:
        return None
    if isinstance(v, list):
        return (str(v[0]).strip() if v else None) or None
    s = str(v).strip()
    return s or None

def _parse_track_number(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        head = str(raw).split("/")[0].strip()
        return int(head)
    except (ValueError, IndexError):
        return None


def _normalize_tag_key(key: str) -> str:
    k = str(key).lower()
    if ":" in k:
        k = k.split(":")[-1]
    return k.replace("_", "").replace(" ", "").replace("-", "")


def _extract_text_from_mutagen_value(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    text = getattr(value, "text", None)
    if isinstance(text, (list, tuple)):
        if text:
            text = text[0]
        else:
            text = None
    if text is None:
        text = getattr(value, "value", value)
    if isinstance(text, (list, tuple)):
        if not text:
            return None
        text = text[0]
    if isinstance(text, bytes):
        try:
            rendered = text.decode("utf-8", errors="replace").strip()
        except Exception:  # noqa: BLE001
            rendered = str(text).strip()
    else:
        rendered = str(text).strip()
    if rendered.startswith("b'") and rendered.endswith("'"):
        rendered = rendered[2:-1].strip()
    if rendered:
        return rendered
    return None


def _first_audio_tag_text(audio, keys: tuple[str, ...]) -> str | None:
    tags = getattr(audio, "tags", None)
    for key in keys:
        for source in (audio, tags):
            if source is None:
                continue
            getter = getattr(source, "get", None)
            if not callable(getter):
                continue
            try:
                value = getter(key)
            except Exception:  # noqa: BLE001, S112
                continue
            if value is None:
                continue
            extracted = _extract_text_from_mutagen_value(value)
            if extracted:
                return extracted

    req_norms = {_normalize_tag_key(k) for k in keys}
    for source in (audio, tags):
        if source is None:
            continue
        keys_func = getattr(source, "keys", None)
        getter = getattr(source, "get", None)
        if not callable(keys_func) or not callable(getter):
            continue
        try:
            source_keys = list(keys_func())
        except Exception:  # noqa: BLE001, S112
            continue
        for skey in source_keys:
            if _normalize_tag_key(str(skey)) in req_norms:
                try:
                    val = getter(skey)
                    extracted = _extract_text_from_mutagen_value(val)
                    if extracted:
                        return extracted
                except Exception:  # noqa: BLE001, S110
                    pass
    return None


def _parse_track_number_value(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    if isinstance(value, tuple) and value:
        value = value[0]
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return _parse_track_number(value)
    try:
        return _parse_track_number(str(value))
    except (TypeError, ValueError):
        return None


def read_audio_metadata_from_audio(audio, path: str) -> AudioMetadata:
    ext = Path(path).suffix.lower()

    if ext in {".mp3", ".wav"}:
        title = _first_audio_tag_text(audio, ("TIT2",)) or os.path.splitext(os.path.basename(path))[0]
        album = _first_audio_tag_text(audio, ("TALB",)) or "Unknown Album"
        artist = _first_audio_tag_text(audio, ("TPE1", "artist", "author")) or "Unknown Artist"
        album_artist = (
            _first_audio_tag_text(
                audio,
                (
                    "TPE2",
                    "TXXX:ALBUM ARTIST",
                    "TXXX:ALBUMARTIST",
                    "TXXX:Album Artist",
                    "TXXX:albumartist",
                    "TXXX:album artist",
                    "TXXX:ALBUM_ARTIST",
                    "TXXX:album_artist",
                    "albumartist",
                    "album artist",
                    "album_artist",
                ),
            )
            or artist
        )
        track_number = _parse_track_number(_first_audio_tag_text(audio, ("TRCK",)))
    elif ext in {".flac", ".ogg", ".oga", ".opus", ".mpc"}:
        title = _first_audio_tag_text(audio, ("title",)) or os.path.splitext(os.path.basename(path))[0]
        album = _first_audio_tag_text(audio, ("album",)) or "Unknown Album"
        artist = _first_audio_tag_text(audio, ("artist", "TPE1")) or "Unknown Artist"
        album_artist = (
            _first_audio_tag_text(
                audio,
                (
                    "albumartist",
                    "album artist",
                    "album_artist",
                    "ALBUMARTIST",
                    "ALBUM ARTIST",
                    "ALBUM_ARTIST",
                    "TPE2",
                    "aART",
                ),
            )
            or artist
        )
        track_number = _parse_track_number(_first_audio_tag_text(audio, ("tracknumber",)))
    elif ext in {".m4a", ".mp4"}:
        title = _first_audio_tag_text(audio, ("©nam",)) or os.path.splitext(os.path.basename(path))[0]
        album = _first_audio_tag_text(audio, ("©alb",)) or "Unknown Album"
        artist = _first_audio_tag_text(audio, ("©ART", "artist")) or "Unknown Artist"
        album_artist = (
            _first_audio_tag_text(
                audio,
                (
                    "aART",
                    "----:com.apple.iTunes:ALBUMARTIST",
                    "----:com.apple.iTunes:ALBUM ARTIST",
                    "----:com.apple.iTunes:albumartist",
                    "----:com.apple.iTunes:album artist",
                    "albumartist",
                    "album artist",
                    "album_artist",
                    "soaa",
                ),
            )
            or artist
        )
        track_raw = None
        getter = getattr(getattr(audio, "tags", None), "get", None)
        if callable(getter):
            try:
                track_raw = getter("trkn")
            except Exception:  # noqa: BLE001
                track_raw = None
        track_number = _parse_track_number_value(track_raw)
    elif ext in {".wma", ".asf"}:
        title = _first_audio_tag_text(audio, ("Title",)) or os.path.splitext(os.path.basename(path))[0]
        album = _first_audio_tag_text(audio, ("WM/AlbumTitle",)) or "Unknown Album"
        artist = _first_audio_tag_text(audio, ("Author", "WM/Artist", "artist")) or "Unknown Artist"
        album_artist = (
            _first_audio_tag_text(
                audio,
                (
                    "WM/AlbumArtist",
                    "albumartist",
                    "album artist",
                    "album_artist",
                    "WM/Artist",
                    "Author",
                ),
            )
            or artist
        )
        track_number = _parse_track_number(_first_audio_tag_text(audio, ("WM/TrackNumber",)))
    elif ext in {".dsf", ".dff"}:
        title = _first_audio_tag_text(audio, ("TIT2",)) or os.path.splitext(os.path.basename(path))[0]
        album = _first_audio_tag_text(audio, ("TALB",)) or "Unknown Album"
        artist = _first_audio_tag_text(audio, ("TPE1", "artist")) or "Unknown Artist"
        album_artist = (
            _first_audio_tag_text(
                audio,
                (
                    "TPE2",
                    "TXXX:ALBUM ARTIST",
                    "TXXX:ALBUMARTIST",
                    "TXXX:Album Artist",
                    "albumartist",
                    "album artist",
                ),
            )
            or artist
        )
        track_number = _parse_track_number(_first_audio_tag_text(audio, ("TRCK",)))
    else:
        title = _first_audio_tag_text(audio, ("title", "TIT2", "©nam", "Title")) or os.path.splitext(os.path.basename(path))[0]
        album = _first_audio_tag_text(audio, ("album", "TALB", "©alb", "WM/AlbumTitle")) or "Unknown Album"
        artist = _first_audio_tag_text(audio, ("artist", "TPE1", "©ART", "Author", "WM/Artist")) or "Unknown Artist"
        album_artist = (
            _first_audio_tag_text(
                audio,
                (
                    "albumartist",
                    "album artist",
                    "album_artist",
                    "TPE2",
                    "aART",
                    "WM/AlbumArtist",
                    "TXXX:ALBUM ARTIST",
                    "----:com.apple.iTunes:ALBUMARTIST",
                ),
            )
            or artist
        )
        track_number = _parse_track_number(
            _first_audio_tag_text(audio, ("tracknumber", "TRCK", "trkn", "WM/TrackNumber"))
        )

    duration = 0.0
    try:
        if getattr(audio, "info", None) and getattr(audio.info, "length", None):
            duration = float(audio.info.length)
    except (TypeError, ValueError):
        duration = 0.0

    return AudioMetadata(
        title=title,
        album=album,
        artist=artist,
        album_artist=album_artist,
        track_number=track_number,
        duration=duration,
    )


def read_audio_metadata(path: str) -> tuple[object, AudioMetadata] | None:
    audio = MutagenFile(path, easy=True)
    if audio is None:
        return None

    metadata = read_audio_metadata_from_audio(audio, path)
    return audio, metadata


def read_audio_metadata_for_scan(path: str) -> tuple[object, AudioMetadata] | None:
    audio = MutagenFile(path, easy=False)
    if audio is None:
        return None
    return audio, read_audio_metadata_from_audio(audio, path)


def _safe_sidecar_component(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .")


def _render_sidecar_pattern(pattern: str, path: str, metadata: AudioMetadata) -> str:
    values = {
        "artist": _safe_sidecar_component(metadata.artist),
        "title": _safe_sidecar_component(metadata.title),
        "album": _safe_sidecar_component(metadata.album),
        "track": _safe_sidecar_component(str(metadata.track_number) if metadata.track_number is not None else ""),
        "filename": _safe_sidecar_component(Path(path).stem),
    }
    try:
        rendered = pattern.format(**values).strip()
    except (KeyError, ValueError, IndexError):
        rendered = ""
    return _safe_sidecar_component(rendered)


def _metadata_sidecar_names(
    path: str,
    metadata: AudioMetadata | None,
    lyrics_file_pattern: str | None = None,
) -> list[str]:
    names = [_safe_sidecar_component(Path(path).stem)]
    if metadata is not None:
        title = _safe_sidecar_component(metadata.title)
        artist = _safe_sidecar_component(metadata.artist)
        album_artist = _safe_sidecar_component(metadata.album_artist)
        track = _safe_sidecar_component(str(metadata.track_number) if metadata.track_number is not None else "")

        if title:
            names.append(title)
        if artist and title:
            names.append(f"{artist} - {title}")
        if album_artist and album_artist != artist and title:
            names.append(f"{album_artist} - {title}")
        if track and title:
            names.append(f"{track}. {title}")
            names.append(f"{track} - {title}")
            if metadata.track_number is not None:
                padded_track = f"{metadata.track_number:02d}"
                names.append(f"{padded_track}. {title}")
                names.append(f"{padded_track} - {title}")

        rendered = _render_sidecar_pattern(lyrics_file_pattern or "", path, metadata)
        if rendered:
            names.append(rendered)

    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not name:
            continue
        key = os.path.normcase(name)
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    return unique


def _sidecar_base_candidates(
    path: str,
    lyrics_lookup_subdir: str | None = None,
    *,
    metadata: AudioMetadata | None = None,
    lyrics_file_pattern: str | None = None,
) -> list[str]:
    audio_path = Path(path)
    names = _metadata_sidecar_names(path, metadata, lyrics_file_pattern)
    dirs: list[Path] = [audio_path.parent]

    normalized_subdir = _normalized_lyrics_lookup_subdir(lyrics_lookup_subdir)
    if normalized_subdir:
        dirs.append(audio_path.parent / normalized_subdir)

    unique: list[str] = []
    seen: set[str] = set()
    for directory in dirs:
        for name in names:
            candidate = directory / name
            rendered = os.path.normcase(str(candidate))
            if rendered in seen:
                continue
            seen.add(rendered)
            unique.append(str(candidate))
    return unique


def get_sidecar_scan_state(
    path: str,
    lyrics_lookup_subdir: str | None = None,
    *,
    metadata: AudioMetadata | None = None,
    lyrics_file_pattern: str | None = None,
    scan_lyrics_source_mode: str | None = None,
    sidecar_lookup_cache: SidecarLookupCache | None = None,
    timing_hook: Callable[[str, float], None] | None = None,
) -> SidecarScanState:
    """Return a deterministic signature and presence state for candidate sidecars."""
    _use_embedded, use_sidecar = _scan_lyrics_source_flags(scan_lyrics_source_mode)
    if not use_sidecar:
        digest = hashlib.sha256(str(TRACK_SCAN_STATE_SIGNATURE_VERSION).encode("ascii")).hexdigest()
        return SidecarScanState(signature=digest, txt_present=False, lrc_present=False)

    started = time.perf_counter()
    records: list[str] = []
    seen_paths: set[str] = set()
    txt_present = False
    lrc_present = False
    for base in _sidecar_base_candidates(
        path,
        lyrics_lookup_subdir,
        metadata=metadata,
        lyrics_file_pattern=lyrics_file_pattern,
    ):
        for suffix in (".txt", ".lrc"):
            candidate = base + suffix
            resolved = (
                sidecar_lookup_cache.resolve_existing(candidate)
                if sidecar_lookup_cache is not None
                else candidate if os.path.isfile(candidate) else None
            )
            if resolved is None:
                continue
            normalized = os.path.normcase(os.path.abspath(resolved))
            if normalized in seen_paths:
                continue
            try:
                stat = os.stat(resolved)
            except OSError:
                continue
            seen_paths.add(normalized)
            records.append(f"{normalized}|{int(stat.st_mtime_ns)}|{int(stat.st_size)}")
            if suffix == ".txt":
                txt_present = True
            else:
                lrc_present = True

    serialized = "\n".join(sorted(records))
    digest_input = f"{TRACK_SCAN_STATE_SIGNATURE_VERSION}\n{serialized}".encode("utf-8")
    digest = hashlib.sha256(digest_input).hexdigest()
    if timing_hook is not None:
        timing_hook("sidecar_signature_stat_s", time.perf_counter() - started)
    return SidecarScanState(
        signature=digest,
        txt_present=txt_present,
        lrc_present=lrc_present,
    )


def _read_sidecar(
    path: str,
    lyrics_lookup_subdir: str | None = None,
    *,
    metadata: AudioMetadata | None = None,
    lyrics_file_pattern: str | None = None,
    sidecar_lookup_cache: SidecarLookupCache | None = None,
) -> tuple[str | None, str | None]:
    txt = None
    lrc = None

    for base in _sidecar_base_candidates(
        path,
        lyrics_lookup_subdir,
        metadata=metadata,
        lyrics_file_pattern=lyrics_file_pattern,
    ):
        txt_path = base + ".txt"
        lrc_path = base + ".lrc"

        resolved_txt_path = (
            sidecar_lookup_cache.resolve_existing(txt_path)
            if sidecar_lookup_cache is not None
            else txt_path if os.path.isfile(txt_path) else None
        )
        if txt is None and resolved_txt_path is not None:
            try:
                txt = Path(resolved_txt_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                txt = None

        resolved_lrc_path = (
            sidecar_lookup_cache.resolve_existing(lrc_path)
            if sidecar_lookup_cache is not None
            else lrc_path if os.path.isfile(lrc_path) else None
        )
        if lrc is None and resolved_lrc_path is not None:
            try:
                lrc = Path(resolved_lrc_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                lrc = None

        if txt is not None and lrc is not None:
            break

    txt = txt.strip() if txt else None
    lrc = lrc.strip() if lrc else None
    return txt, lrc


def read_embedded_lyrics_from_audio(audio, path: str) -> tuple[str | None, str | None]:
    p = Path(path)
    ext = p.suffix.lower()
    plain: str | None = None
    synced: str | None = None

    try:
        if ext in {".mp3", ".wav"}:
            try:
                tags = audio if callable(getattr(audio, "getall", None)) else getattr(audio, "tags", None) or ID3(path)
                if not callable(getattr(tags, "getall", None)):
                    tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()

            plain = _first_managed_uslt_text(tags)

            synced = _first_id3_synced_lrc(tags)

        elif ext in {".dsf", ".dff"}:
            tags = getattr(audio, "tags", None)
            if tags:
                plain = _first_managed_uslt_text(tags)

                synced = _first_id3_synced_lrc(tags)

        elif ext in {".flac"} or ext in {".ogg", ".oga"} or ext == ".opus":
            plain, synced = _read_vorbis_lyrics(audio)

        elif ext in {".m4a", ".mp4"}:
            plain_list = audio.get(MP4_PLAIN_KEY)
            if isinstance(plain_list, (list, tuple)) and plain_list:
                plain = str(plain_list[0])
            elif isinstance(plain_list, str):
                plain = plain_list

            atom = audio.get(MP4_SYNCED_KEY)
            if isinstance(atom, (list, tuple)) and atom:
                first = atom[0]
                if isinstance(first, (bytes, bytearray)):
                    try:
                        synced = first.decode("utf-8", errors="replace")
                    except (UnicodeDecodeError, AttributeError):
                        synced = None
                else:
                    synced = str(first)

        elif ext in {".wma", ".asf"}:
            def _first_asf_text(keys: tuple[str, ...]) -> str | None:
                for key in keys:
                    values = audio.get(key)
                    if not values:
                        continue
                    for value in values:
                        text = getattr(value, "value", value)
                        if text is None:
                            continue
                        rendered = str(text).strip()
                        if rendered:
                            return rendered
                return None

            plain = _first_asf_text(ASF_PLAIN_KEYS)
            synced = _first_asf_text(ASF_SYNCED_KEYS)

        elif ext == ".mpc":
            tags = getattr(audio, "tags", None)

            def _first_ape_text(keys: tuple[str, ...]) -> str | None:
                if not tags:
                    return None
                for key in keys:
                    value = tags.get(key)
                    if not value:
                        continue
                    if isinstance(value, (list, tuple)) and value:
                        rendered = str(value[0]).strip()
                    else:
                        rendered = str(value).strip()
                    if rendered:
                        return rendered
                return None

            plain = _first_ape_text(APE_PLAIN_KEYS)
            synced = _first_ape_text(APE_SYNCED_KEYS)

        else:
            for key in (
                VORBIS_SYNCED_KEY,
                VORBIS_PLAIN_KEY,
                "USLT",
                MP4_PLAIN_KEY,
                MP4_SYNCED_KEY,
                *ASF_PLAIN_KEYS,
                *ASF_SYNCED_KEYS,
                "lyrics",
                "LYRICS",
                "LYRICS_SYNCD",
            ):
                val = audio.tags.get(key) if getattr(audio, "tags", None) else None
                if val:
                    if isinstance(val, (list, tuple)):
                        plain = str(val[0])
                    else:
                        try:
                            plain = str(val)
                        except (TypeError, ValueError):
                            plain = None
                    if plain:
                        break
    except (MutagenError, Exception):
        logger.exception("Failed to read embedded lyrics from %s", path)

    def _norm(s: str | None) -> str | None:
        if s is None:
            return None
        s2 = str(s).strip()
        return s2 or None

    return _norm(plain), _norm(synced)

def read_embedded_lyrics(path: str) -> tuple[str | None, str | None]:
    """
    Read embedded plain lyrics and synced LRC (if present) from an audio file.
    Returns (plain_lyrics_or_None, synced_lrc_or_None).

    Implementation notes:
      - MP3/WAV: reads ID3 USLT for plain lyrics and a TXXX with desc 'LYRICS' for synced.
      - FLAC/Vorbis/Ogg: reads 'LYRICS' and 'LRCLIB_LRC' vorbis comments.
      - MP4/M4A: reads '\xa9lyr' and '----:com.lrclib:lrc' (custom atom, bytes).
      - WMA/ASF: reads ASF string attributes for plain and synced lyrics.
      - DSF/DSDIFF (.dff): reads ID3 lyrics frames.
      - Fallback: tries MutagenFile() and some common keys.
    """
    plain: str | None = None
    synced: str | None = None
    ext = Path(path).suffix.lower()
    try:
        audio = MutagenFile(path, easy=False)
        if audio is not None:
            plain, synced = read_embedded_lyrics_from_audio(audio, path)
    except (MutagenError, Exception):
        if ext == ".mpc":
            try:
                audio = Musepack(path)
                plain, synced = read_embedded_lyrics_from_audio(audio, path)
            except (MutagenError, Exception):
                logger.exception("Failed to read embedded lyrics from %s", path)
        else:
            logger.exception("Failed to read embedded lyrics from %s", path)
    return plain, synced


def new_fs_track_from_path(
    path: str,
    *,
    signature: tuple[float | None, int | None] | None = None,
    audio_signature: tuple[float | None, int | None] | None = None,
    lyrics_lookup_subdir: str | None = None,
    lyrics_file_pattern: str | None = None,
    scan_lyrics_source_mode: str | None = None,
    sidecar_lookup_cache: SidecarLookupCache | None = None,
    metadata: AudioMetadata | None = None,
    audio=None,
    timing_hook: Callable[[str, float], None] | None = None,
) -> FsTrack | None:
    try:
        metadata_result = None if metadata is not None else read_audio_metadata(path)
        if metadata is None:
            if metadata_result is None:
                return None
            _audio, metadata = metadata_result

        use_embedded, use_sidecar = _scan_lyrics_source_flags(scan_lyrics_source_mode)
        # Preferred order: embedded, same-folder sidecars, then optional subfolder sidecars.
        embedded_started = time.perf_counter()
        txt_embedded: str | None
        lrc_embedded: str | None
        if use_embedded and audio is not None:
            txt_embedded, lrc_embedded = read_embedded_lyrics_from_audio(audio, path)
        elif use_embedded:
            txt_embedded, lrc_embedded = read_embedded_lyrics(path)
        else:
            txt_embedded, lrc_embedded = None, None
        if timing_hook is not None:
            timing_hook("embedded_lyrics_read_s", time.perf_counter() - embedded_started)

        if use_sidecar:
            sidecar_started = time.perf_counter()
            txt_sidecar, lrc_sidecar = _read_sidecar(
                path,
                lyrics_lookup_subdir,
                metadata=metadata,
                lyrics_file_pattern=lyrics_file_pattern,
                sidecar_lookup_cache=sidecar_lookup_cache,
            )
            if timing_hook is not None:
                timing_hook("sidecar_lookup_s", time.perf_counter() - sidecar_started)
        else:
            txt_sidecar, lrc_sidecar = None, None
            if timing_hook is not None:
                timing_hook("sidecar_lookup_s", 0.0)

        txt_lyrics = txt_embedded or txt_sidecar
        lrc_lyrics = lrc_embedded or lrc_sidecar

        signature_source = (
            signature
            if signature is not None
            else get_audio_file_signature_with_lookup(
                path,
                lyrics_lookup_subdir,
                metadata=metadata,
                lyrics_file_pattern=lyrics_file_pattern,
                scan_lyrics_source_mode=scan_lyrics_source_mode,
                audio_signature=audio_signature,
                sidecar_lookup_cache=sidecar_lookup_cache,
            )
        )
        modified_time, file_size = signature_source

        return FsTrack(
            file_path=path,
            file_name=os.path.basename(path),
            title=metadata.title,
            album=metadata.album,
            artist=metadata.artist,
            album_artist=metadata.album_artist,
            duration=metadata.duration,
            txt_lyrics=txt_lyrics,
            lrc_lyrics=lrc_lyrics,
            track_number=metadata.track_number,
            modified_time=modified_time,
            file_size=file_size,
        )
    except (MutagenError, Exception) as exc:  # noqa: BLE001
        logger.warning("Skipping unreadable audio file during scan: %s (%s)", path, exc)
        return None
