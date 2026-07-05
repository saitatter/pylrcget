# src/library/scan_library.py
from __future__ import annotations

import os
import logging
import re
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Callable

from mutagen import File as MutagenFile
from mutagen.asf import ASF
from mutagen.dsf import DSF
from mutagen.dsdiff import DSDIFF
from mutagen.id3 import ID3, USLT, TXXX, ID3NoHeaderError
from mutagen.flac import FLAC
from mutagen.musepack import Musepack
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.mp4 import MP4
from mutagen._util import MutagenError

from core.models import FsTrack

from core.embed_lyrics import (
    VORBIS_PLAIN_KEY, VORBIS_SYNCED_KEY,
    ID3_PLAIN_DESC, ID3_SYNCED_DESC,
    MP4_PLAIN_KEY, MP4_SYNCED_KEY
)

logger = logging.getLogger(__name__)

AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav", ".wma", ".asf", ".dsf", ".dff", ".mpc"}

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


def _read_vorbis_lyrics(audio) -> tuple[str | None, str | None]:
    plain_list = audio.get(VORBIS_PLAIN_KEY)
    synced_list = audio.get(VORBIS_SYNCED_KEY)
    plain = (plain_list[0] if isinstance(plain_list, (list, tuple)) and plain_list else None)
    synced = (synced_list[0] if isinstance(synced_list, (list, tuple)) and synced_list else None)
    return plain, synced


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


def iter_audio_paths(
    directories: list[str],
    *,
    excluded_paths: str | None = None,
    excluded_patterns: str | None = None,
) -> list[str]:
    excluded_roots = _normalize_excluded_paths(excluded_paths)
    compiled_patterns = _compile_excluded_patterns(excluded_patterns)
    paths: list[str] = []
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
                if not _is_path_excluded_variants(file_path, normalized, posix_path, excluded_roots, compiled_patterns):
                    seen.add(normalized)
                    paths.append(file_path)
    return paths


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
) -> tuple[float | None, int | None]:
    return get_audio_file_signature_with_lookup(
        path,
        lyrics_lookup_subdir,
        metadata=metadata,
        lyrics_file_pattern=lyrics_file_pattern,
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


def get_audio_file_signature_with_lookup(
    path: str,
    lyrics_lookup_subdir: str | None = None,
    *,
    metadata: AudioMetadata | None = None,
    lyrics_file_pattern: str | None = None,
) -> tuple[float | None, int | None]:
    newest_mtime: float | None = None
    total_size = 0
    candidates = [path]
    for base in _sidecar_base_candidates(
        path,
        lyrics_lookup_subdir,
        metadata=metadata,
        lyrics_file_pattern=lyrics_file_pattern,
    ):
        candidates.extend([base + ".txt", base + ".lrc"])

    for candidate in candidates:
        try:
            stat = os.stat(candidate)
        except OSError:
            continue
        candidate_mtime = float(stat.st_mtime)
        newest_mtime = candidate_mtime if newest_mtime is None else max(newest_mtime, candidate_mtime)
        total_size += int(stat.st_size)

    return newest_mtime, total_size if newest_mtime is not None else None

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


def read_audio_metadata(path: str) -> tuple[object, AudioMetadata] | None:
    audio = MutagenFile(path, easy=True)
    if audio is None:
        return None

    title = _first(audio, "title")
    album = _first(audio, "album")
    artist = _first(audio, "artist")

    title = title or os.path.splitext(os.path.basename(path))[0]
    album = album or "Unknown Album"
    artist = artist or "Unknown Artist"

    album_artist = (
        _first(audio, "albumartist")
        or _first(audio, "album artist")
        or artist
    )

    track_number = _parse_track_number(_first(audio, "tracknumber"))

    duration = 0.0
    try:
        if getattr(audio, "info", None) and getattr(audio.info, "length", None):
            duration = float(audio.info.length)
    except (TypeError, ValueError):
        duration = 0.0

    return audio, AudioMetadata(
        title=title,
        album=album,
        artist=artist,
        album_artist=album_artist,
        track_number=track_number,
        duration=duration,
    )


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


def _read_sidecar(
    path: str,
    lyrics_lookup_subdir: str | None = None,
    *,
    metadata: AudioMetadata | None = None,
    lyrics_file_pattern: str | None = None,
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

        if txt is None and os.path.isfile(txt_path):
            try:
                txt = Path(txt_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                txt = None

        if lrc is None and os.path.isfile(lrc_path):
            try:
                lrc = Path(lrc_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                lrc = None

        if txt is not None and lrc is not None:
            break

    txt = txt.strip() if txt else None
    lrc = lrc.strip() if lrc else None
    return txt, lrc

def read_embedded_lyrics(path: str) -> tuple[str | None, str | None]:
    """
    Read embedded plain lyrics and synced LRC (if present) from an audio file.
    Returns (plain_lyrics_or_None, synced_lrc_or_None).

    Implementation notes:
      - MP3: reads ID3 USLT for plain lyrics and a TXXX with desc 'LYRICS' for synced.
      - FLAC/Vorbis/Ogg: reads 'LYRICS' and 'LRCLIB_LRC' vorbis comments.
      - MP4/M4A: reads '\xa9lyr' and '----:com.lrclib:lrc' (custom atom, bytes).
      - WMA/ASF: reads ASF string attributes for plain and synced lyrics.
      - DSF/DSDIFF (.dff): reads ID3 lyrics frames.
      - Fallback: tries MutagenFile() and some common keys.
    """
    p = Path(path)
    ext = p.suffix.lower()
    plain: str | None = None
    synced: str | None = None

    try:
        if ext == ".mp3":
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()  # empty

            # USLT frames: use first available
            uslt_frames = tags.getall("USLT")
            if uslt_frames:
                # USLT.text can be a str
                plain = uslt_frames[0].text if getattr(uslt_frames[0], "text", None) else None

            # TXXX custom frames: find one with desc == LRCLIB_LRC (case-sensitive)
            txxx_frames = tags.getall("TXXX")
            for t in txxx_frames:
                if getattr(t, "desc", "") == ID3_SYNCED_DESC:
                    # TXXX.text is usually a list-like (mutagen uses [text]) but can be str
                    txt = getattr(t, "text", None)
                    if isinstance(txt, (list, tuple)) and txt:
                        synced = str(txt[0])
                    elif isinstance(txt, str):
                        synced = txt
                    break

        elif ext in {".dsf", ".dff"}:
            audio = DSF(path) if ext == ".dsf" else DSDIFF(path)
            tags = getattr(audio, "tags", None)

            if tags:
                uslt_frames = tags.getall("USLT")
                if uslt_frames:
                    plain = uslt_frames[0].text if getattr(uslt_frames[0], "text", None) else None

                txxx_frames = tags.getall("TXXX")
                for t in txxx_frames:
                    if getattr(t, "desc", "") == ID3_SYNCED_DESC:
                        txt = getattr(t, "text", None)
                        if isinstance(txt, (list, tuple)) and txt:
                            synced = str(txt[0])
                        elif isinstance(txt, str):
                            synced = txt
                        break

        elif ext in {".flac"}:
            audio = FLAC(path)
            plain, synced = _read_vorbis_lyrics(audio)
        elif ext in {".ogg", ".oga"}:
            audio = OggVorbis(path)
            plain, synced = _read_vorbis_lyrics(audio)

        elif ext == ".opus":
            audio = OggOpus(path)
            plain, synced = _read_vorbis_lyrics(audio)

        elif ext in {".m4a", ".mp4"}:
            audio = MP4(path)
            # plain lyrics: '\xa9lyr'
            plain_list = audio.get(MP4_PLAIN_KEY)
            if isinstance(plain_list, (list, tuple)) and plain_list:
                plain = str(plain_list[0])
            elif isinstance(plain_list, str):
                plain = plain_list

            # synced: custom atom '----:com.lrclib:lrc' -> stored as bytes inside a list
            key = MP4_SYNCED_KEY
            atom = audio.get(key)
            if isinstance(atom, (list, tuple)) and atom:
                first = atom[0]
                # MP4 custom atom often stores bytes; attempt decode if so
                if isinstance(first, (bytes, bytearray)):
                    try:
                        synced = first.decode("utf-8", errors="replace")
                    except (UnicodeDecodeError, AttributeError):
                        synced = None
                else:
                    synced = str(first)

        elif ext in {".wma", ".asf"}:
            audio = ASF(path)

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
            audio = Musepack(path)
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
            # Fallback generic MutagenFile with common keys
            audio = MutagenFile(path, easy=False)
            if audio is not None:
                # Try common keys (case-sensitive and lowercase)
                for key in (VORBIS_SYNCED_KEY, VORBIS_PLAIN_KEY, "USLT", MP4_PLAIN_KEY, MP4_SYNCED_KEY, *ASF_PLAIN_KEYS, *ASF_SYNCED_KEYS, "lyrics", "LYRICS", "LYRICS_SYNCD"):
                    val = audio.tags.get(key) if getattr(audio, "tags", None) else None
                    if val:
                        # val could be list or frame; handle politely
                        if isinstance(val, (list, tuple)):
                            plain = str(val[0])
                        else:
                            try:
                                plain = str(val)
                            except (TypeError, ValueError):
                                plain = None
                        if plain:
                            break
    except (MutagenError, Exception) as e:
        logger.exception("Failed to read embedded lyrics from %s: %s", path, e)
        # return whatever we have (likely None, None)
    # Normalize blank -> None and strip
    def _norm(s: str | None) -> str | None:
        if s is None:
            return None
        s2 = str(s).strip()
        return s2 or None

    return _norm(plain), _norm(synced)


def new_fs_track_from_path(
    path: str,
    *,
    signature: tuple[float | None, int | None] | None = None,
    lyrics_lookup_subdir: str | None = None,
    lyrics_file_pattern: str | None = None,
    metadata: AudioMetadata | None = None,
    timing_hook: Callable[[str, float], None] | None = None,
) -> FsTrack | None:
    try:
        metadata_result = None if metadata is not None else read_audio_metadata(path)
        if metadata is None:
            if metadata_result is None:
                return None
            _audio, metadata = metadata_result

        # Preferred order: embedded, same-folder sidecars, then optional subfolder sidecars.
        embedded_started = time.perf_counter()
        txt_embedded, lrc_embedded = read_embedded_lyrics(path)
        if timing_hook is not None:
            timing_hook("embedded_lyrics_read_s", time.perf_counter() - embedded_started)

        sidecar_started = time.perf_counter()
        txt_sidecar, lrc_sidecar = _read_sidecar(
            path,
            lyrics_lookup_subdir,
            metadata=metadata,
            lyrics_file_pattern=lyrics_file_pattern,
        )
        if timing_hook is not None:
            timing_hook("sidecar_lookup_s", time.perf_counter() - sidecar_started)

        txt_lyrics = txt_embedded or txt_sidecar
        lrc_lyrics = lrc_embedded or lrc_sidecar

        modified_time, file_size = (
            signature
            if signature is not None
            else get_audio_file_signature_with_lookup(
                path,
                lyrics_lookup_subdir,
                metadata=metadata,
                lyrics_file_pattern=lyrics_file_pattern,
            )
        )

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
    except (MutagenError, Exception) as exc:
        logger.warning("Skipping unreadable audio file during scan: %s (%s)", path, exc)
        return None
