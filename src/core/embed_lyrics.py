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

# Convention:
#   - Synced LRC goes into:   LYRICS
#   - Unsynced (plain) goes into: UNSYNCEDLYRICS
VORBIS_SYNCED_KEY = "LYRICS"
VORBIS_PLAIN_KEY = "UNSYNCEDLYRICS"

ID3_SYNCED_DESC = "LYRICS"
ID3_PLAIN_DESC = "UNSYNCEDLYRICS"

MP4_PLAIN_KEY = "\xa9lyr"
MP4_SYNCED_KEY = "----:com.lrclib:LYRICS"  # custom atom name; keep stable across app versions


def _strip_timestamps(lrc: str) -> str:
    """Remove [mm:ss.xx] tokens from LRC to derive plain lyrics."""
    out_lines: list[str] = []
    for line in lrc.splitlines():
        line = line.strip()
        if not line:
            continue
        # Remove any leading [....] blocks (timestamps or tags) repeatedly.
        while line.startswith("[") and "]" in line:
            line = line.split("]", 1)[1].lstrip()
        out_lines.append(line)
    return "\n".join(out_lines).strip()


def _norm(s: Optional[str]) -> Optional[str]:
    """Normalize optional strings (strip + convert empty to None)."""
    if not s:
        return None
    s = s.strip()
    return s or None


def embed_lyrics_for_track(track) -> None:
    """
    Embed lyrics for a Track object from the DB.
    The object is expected to have:
      - file_path
      - txt_lyrics (unsynced/plain)
      - lrc_lyrics (synced/LRC)
    """
    path = track.file_path
    plain = _norm(getattr(track, "txt_lyrics", None))
    synced = _norm(getattr(track, "lrc_lyrics", None))

    # If we only have synced lyrics, derive plain lyrics from it.
    if synced and not plain:
        plain = _norm(_strip_timestamps(synced))

    embed_lyrics_in_file(path, plain, synced)


def embed_lyrics_in_file(path: str, plain: Optional[str], synced: Optional[str]) -> None:
    """
    Embed lyrics depending on file extension:
      - .mp3            -> ID3: USLT for plain + TXXX for synced (LYRICS)
      - .flac           -> Vorbis comments: UNSYNCEDLYRICS + LYRICS
      - .ogg/.oga/.opus -> Vorbis comments: UNSYNCEDLYRICS + LYRICS
      - .m4a/.mp4       -> MP4: ©lyr for plain + custom atom for synced
    """
    EMBEDDER_MAP = {
        ".mp3": _embed_mp3,
        ".flac": _embed_flac,
        ".ogg": _embed_ogg_vorbis,
        ".oga": _embed_ogg_vorbis,
        ".opus": _embed_ogg_opus,
        ".m4a": _embed_mp4,
        ".mp4": _embed_mp4,
    }

    ext = os.path.splitext(path)[1].lower()
    embedder = EMBEDDER_MAP.get(ext)
    if embedder:
        embedder(path, plain, synced)
        return

    # Fallback: try a simple text-only lyrics field if mutagen supports it.
    audio = MutagenFile(path, easy=True)
    if audio is None:
        return

    if plain:
        audio["lyrics"] = [plain]
    elif "lyrics" in audio:
        del audio["lyrics"]

    audio.save()


def _embed_vorbis_comment(audio_cls, path: str, plain: Optional[str], synced: Optional[str]) -> None:
    """Helper for formats that use Vorbis comments (FLAC/Vorbis/Opus)."""
    audio = audio_cls(path)

    if plain:
        audio[VORBIS_PLAIN_KEY] = [plain]
    elif VORBIS_PLAIN_KEY in audio:
        del audio[VORBIS_PLAIN_KEY]

    if synced:
        audio[VORBIS_SYNCED_KEY] = [synced]
    elif VORBIS_SYNCED_KEY in audio:
        del audio[VORBIS_SYNCED_KEY]

    audio.save()


def _embed_flac(path: str, plain: Optional[str], synced: Optional[str]) -> None:
    _embed_vorbis_comment(FLAC, path, plain, synced)


def _embed_ogg_vorbis(path: str, plain: Optional[str], synced: Optional[str]) -> None:
    _embed_vorbis_comment(OggVorbis, path, plain, synced)


def _embed_ogg_opus(path: str, plain: Optional[str], synced: Optional[str]) -> None:
    _embed_vorbis_comment(OggOpus, path, plain, synced)


def _embed_mp3(path: str, plain: Optional[str], synced: Optional[str]) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    # Remove old frames we manage.
    tags.delall("USLT")
    tags.delall(f"TXXX:{ID3_SYNCED_DESC}")
    tags.delall(f"TXXX:{ID3_PLAIN_DESC}")

    # Plain lyrics: use USLT. ID3 requires a 3-letter language code, but we avoid
    # a real language and use "und" (undefined).
    if plain:
        tags.add(
            USLT(
                encoding=3,  # UTF-8
                lang="und",  # undefined language
                desc="",
                text=plain,
            )
        )

        # Optional: also mirror plain lyrics into a TXXX for easier access in some tools.
        tags.add(
            TXXX(
                encoding=3,
                desc=ID3_PLAIN_DESC,
                text=plain,
            )
        )

    # Synced lyrics (raw LRC): store in a custom TXXX with desc="LYRICS".
    if synced:
        tags.add(
            TXXX(
                encoding=3,
                desc=ID3_SYNCED_DESC,
                text=synced,
            )
        )

    tags.save(path)


def _embed_mp4(path: str, plain: Optional[str], synced: Optional[str]) -> None:
    audio = MP4(path)

    # Plain lyrics: standard Apple tag ©lyr.
    if plain:
        audio[MP4_PLAIN_KEY] = [plain]
    elif MP4_PLAIN_KEY in audio:
        del audio[MP4_PLAIN_KEY]

    # Synced lyrics: custom atom.
    if synced:
        audio[MP4_SYNCED_KEY] = [synced.encode("utf-8")]
    elif MP4_SYNCED_KEY in audio:
        del audio[MP4_SYNCED_KEY]

    audio.save()
