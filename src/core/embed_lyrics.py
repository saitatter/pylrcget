# core/embed_lyrics.py
from __future__ import annotations

from typing import Optional

import os

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, USLT, TXXX, ID3NoHeaderError
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.mp4 import MP4


def _strip_timestamps(lrc: str) -> str:
    """Scoate [mm:ss.xx] din LRC pentru a obține plain lyrics."""
    out_lines: list[str] = []
    for line in lrc.splitlines():
        line = line.strip()
        if not line:
            continue
        while line.startswith("[") and "]" in line:
            line = line.split("]", 1)[1].lstrip()
        out_lines.append(line)
    return "\n".join(out_lines).strip()


def _norm(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    return s or None


def embed_lyrics_for_track(track) -> None:
    """
    Embed lyrics pentru un obiect Track din DB.
    track trebuie să aibă:
      - file_path
      - txt_lyrics
      - lrc_lyrics
    """
    path = track.file_path
    plain = _norm(track.txt_lyrics)
    synced = _norm(track.lrc_lyrics)

    # dacă avem doar synced, derivăm plain din el
    if synced and not plain:
        plain = _norm(_strip_timestamps(synced))

    embed_lyrics_in_file(path, plain, synced)


def embed_lyrics_in_file(path: str, plain: Optional[str], synced: Optional[str]) -> None:
    """
    Embed lyrics în funcție de extensie:
      - .mp3  -> ID3 USLT + TXXX pentru LRC raw
      - .flac -> LYRICS + LRCLIB_LRC
      - .ogg/.oga/.opus -> LYRICS + LRCLIB_LRC
      - .m4a/.mp4 -> ©lyr + custom atom pentru LRC
    """
    ext = os.path.splitext(path)[1].lower()

    if ext == ".mp3":
        _embed_mp3(path, plain, synced)
    elif ext == ".flac":
        _embed_flac(path, plain, synced)
    elif ext in (".ogg", ".oga"):
        _embed_ogg_vorbis(path, plain, synced)
    elif ext == ".opus":
        _embed_ogg_opus(path, plain, synced)
    elif ext in (".m4a", ".mp4"):
        _embed_mp4(path, plain, synced)
    else:
        # fallback generic: încearcă text-only dacă mutagen știe ceva
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return
        if plain:
            audio["lyrics"] = [plain]
        audio.save()


def _embed_mp3(path: str, plain: Optional[str], synced: Optional[str]) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    # șterge USLT/TXXX vechi
    tags.delall("USLT")
    tags.delall("TXXX:LRCLIB_LRC")

    if plain:
        tags.add(
            USLT(
                encoding=3,      # UTF-8
                lang="eng",
                desc="",
                text=plain,
            )
        )

    if synced:
        tags.add(
            TXXX(
                encoding=3,
                desc="LRCLIB_LRC",
                text=synced,
            )
        )

    tags.save(path)


def _embed_flac(path: str, plain: Optional[str], synced: Optional[str]) -> None:
    audio = FLAC(path)

    # LYRICS pentru plain
    if plain:
        audio["LYRICS"] = [plain]
    elif "LYRICS" in audio:
        del audio["LYRICS"]

    # LRCLIB_LRC pentru synced raw
    if synced:
        audio["LRCLIB_LRC"] = [synced]
    elif "LRCLIB_LRC" in audio:
        del audio["LRCLIB_LRC"]

    audio.save()


def _embed_ogg_vorbis(path: str, plain: Optional[str], synced: Optional[str]) -> None:
    audio = OggVorbis(path)

    if plain:
        audio["LYRICS"] = [plain]
    elif "LYRICS" in audio:
        del audio["LYRICS"]

    if synced:
        audio["LRCLIB_LRC"] = [synced]
    elif "LRCLIB_LRC" in audio:
        del audio["LRCLIB_LRC"]

    audio.save()


def _embed_ogg_opus(path: str, plain: Optional[str], synced: Optional[str]) -> None:
    audio = OggOpus(path)

    if plain:
        audio["LYRICS"] = [plain]
    elif "LYRICS" in audio:
        del audio["LYRICS"]

    if synced:
        audio["LRCLIB_LRC"] = [synced]
    elif "LRCLIB_LRC" in audio:
        del audio["LRCLIB_LRC"]

    audio.save()


def _embed_mp4(path: str, plain: Optional[str], synced: Optional[str]) -> None:
    audio = MP4(path)

    # plain: standard Apple tag ©lyr
    if plain:
        audio["\xa9lyr"] = [plain]
    elif "\xa9lyr" in audio:
        del audio["\xa9lyr"]

    # synced: custom atom
    key = "----:com.lrclib:lrc"
    if synced:
        audio[key] = [synced.encode("utf-8")]
    elif key in audio:
        del audio[key]

    audio.save()
