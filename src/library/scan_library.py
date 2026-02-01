# src/library/scan_library.py
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional, Tuple

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, USLT, TXXX, ID3NoHeaderError
from mutagen.flac import FLAC
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

AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".ogg", ".opus", ".wav"}

def iter_audio_paths(directories: list[str]) -> list[str]:
    paths: list[str] = []
    for root in directories:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext in AUDIO_EXTS:
                    paths.append(os.path.join(dirpath, fn))
    return paths

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
    except Exception:
        return None

def _read_sidecar(path: str) -> tuple[str | None, str | None]:
    base, _ = os.path.splitext(path)
    txt_path = base + ".txt"
    lrc_path = base + ".lrc"

    txt = None
    lrc = None

    if os.path.isfile(txt_path):
        try:
            txt = open(txt_path, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            txt = None

    if os.path.isfile(lrc_path):
        try:
            lrc = open(lrc_path, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            lrc = None

    txt = txt.strip() if txt else None
    lrc = lrc.strip() if lrc else None
    return txt, lrc

def read_embedded_lyrics(path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Read embedded plain lyrics and synced LRC (if present) from an audio file.
    Returns (plain_lyrics_or_None, synced_lrc_or_None).

    Implementation notes:
      - MP3: reads ID3 USLT for plain lyrics and a TXXX with desc 'LRCLIB_LRC' for synced.
      - FLAC/Vorbis/Ogg: reads 'LYRICS' and 'LRCLIB_LRC' vorbis comments.
      - MP4/M4A: reads '\xa9lyr' and '----:com.lrclib:lrc' (custom atom, bytes).
      - Fallback: tries MutagenFile() and some common keys.
    """
    p = Path(path)
    ext = p.suffix.lower()
    plain: Optional[str] = None
    synced: Optional[str] = None

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

        elif ext in {".flac"}:
            audio = FLAC(path)
            # Vorbis comments are lists
            plain_list = audio.get(VORBIS_PLAIN_KEY)
            synced_list = audio.get(VORBIS_SYNCED_KEY)
            plain = plain_list[0] if plain_list else None
            synced = synced_list[0] if synced_list else None
        elif ext in {".ogg", ".oga"}:
            audio = OggVorbis(path)
            plain_list = audio.get(VORBIS_PLAIN_KEY)
            synced_list = audio.get(VORBIS_SYNCED_KEY)
            plain = (plain_list[0] if isinstance(plain_list, (list, tuple)) and plain_list else None)
            synced = (synced_list[0] if isinstance(synced_list, (list, tuple)) and synced_list else None)

        elif ext == ".opus":
            audio = OggOpus(path)
            plain_list = audio.get(VORBIS_PLAIN_KEY)
            synced_list = audio.get(VORBIS_SYNCED_KEY)
            plain = (plain_list[0] if isinstance(plain_list, (list, tuple)) and plain_list else None)
            synced = (synced_list[0] if isinstance(synced_list, (list, tuple)) and synced_list else None)

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
                    except Exception:
                        synced = None
                else:
                    synced = str(first)

        else:
            # Fallback generic MutagenFile with common keys
            audio = MutagenFile(path, easy=False)
            if audio is not None:
                # Try common keys (case-sensitive and lowercase)
                for key in (VORBIS_SYNCED_KEY, VORBIS_PLAIN_KEY, "USLT", MP4_PLAIN_KEY, MP4_SYNCED_KEY, "lyrics", "LYRICS", "LYRICS_SYNCD"):
                    val = audio.tags.get(key) if getattr(audio, "tags", None) else None
                    if val:
                        # val could be list or frame; handle politely
                        if isinstance(val, (list, tuple)):
                            plain = str(val[0])
                        else:
                            try:
                                plain = str(val)
                            except Exception:
                                plain = None
                        if plain:
                            break
    except (MutagenError, Exception) as e:
        logger.exception("Failed to read embedded lyrics from %s: %s", path, e)
        # return whatever we have (likely None, None)
    # Normalize blank -> None and strip
    def _norm(s: Optional[str]) -> Optional[str]:
        if s is None:
            return None
        s2 = str(s).strip()
        return s2 or None

    return _norm(plain), _norm(synced)


def _read_sidecar(path: str) -> tuple[Optional[str], Optional[str]]:
    """(existing function kept for sidecar preference)"""
    base, _ = os.path.splitext(path)
    txt_path = base + ".txt"
    lrc_path = base + ".lrc"

    txt = None
    lrc = None

    if os.path.isfile(txt_path):
        try:
            txt = open(txt_path, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            txt = None

    if os.path.isfile(lrc_path):
        try:
            lrc = open(lrc_path, "r", encoding="utf-8", errors="replace").read()
        except Exception:
            lrc = None

    txt = txt.strip() if txt else None
    lrc = lrc.strip() if lrc else None
    return txt, lrc


def new_fs_track_from_path(path: str) -> FsTrack | None:
    audio = MutagenFile(path, easy=True)
    if audio is None:
        return None

    # title/album/artist extraction
    def _first(easy, key: str) -> str | None:
        v = easy.get(key)
        if not v:
            return None
        if isinstance(v, list):
            return (str(v[0]).strip() if v else None) or None
        s = str(v).strip()
        return s or None

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
    except Exception:
        duration = 0.0

    # SIDE-CAR (preferred) then EMBEDDED
    txt_sidecar, lrc_sidecar = _read_sidecar(path)
    txt_embedded, lrc_embedded = read_embedded_lyrics(path)

    txt_lyrics = txt_sidecar or txt_embedded
    lrc_lyrics = lrc_sidecar or lrc_embedded

    return FsTrack(
        file_path=path,
        file_name=os.path.basename(path),
        title=title,
        album=album,
        artist=artist,
        album_artist=album_artist,
        duration=duration,
        txt_lyrics=txt_lyrics,
        lrc_lyrics=lrc_lyrics,
        track_number=track_number,
    )