from __future__ import annotations
import os
import glob
from mutagen import File as MutagenFile
from core.models import FsTrack

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

def new_fs_track_from_path(path: str) -> FsTrack | None:
    audio = MutagenFile(path, easy=True)
    if audio is None:
        return None

    # Rust: title/album/artist required (errors). In Python, be lenient but keep good defaults.
    title = _first(audio, "title")
    album = _first(audio, "album")
    artist = _first(audio, "artist")

    # If you want strict behavior like Rust, return None when missing:
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

    txt_lyrics, lrc_lyrics = _read_sidecar(path)

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
