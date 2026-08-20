# core/embed_lyrics.py
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from mutagen import File as MutagenFile
from mutagen.apev2 import APETextValue
from mutagen.asf import ASF, ASFUnicodeAttribute
from mutagen.dsf import DSF
from mutagen.dsdiff import DSDIFF
from mutagen.id3 import ID3, USLT, TXXX, ID3NoHeaderError
from mutagen.flac import FLAC
from mutagen.musepack import Musepack
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.mp4 import MP4
from mutagen.wave import WAVE

from core.utils import plain_text_from_lrc

if TYPE_CHECKING:
    from db.models import Track

# Convention:
#   - Synced LRC goes into:   LYRICS
#   - Unsynced (plain) goes into: UNSYNCEDLYRICS
VORBIS_SYNCED_KEY = "LYRICS"
VORBIS_PLAIN_KEY = "UNSYNCEDLYRICS"

ID3_SYNCED_DESC = "LYRICS"
ID3_PLAIN_DESC = "UNSYNCEDLYRICS"

MP4_PLAIN_KEY = "\xa9lyr"
MP4_SYNCED_KEY = "----:com.lrclib:LYRICS"  # custom atom name; keep stable across app versions
ASF_PLAIN_KEY = "WM/Lyrics"
ASF_SYNCED_KEY = "LRCLIB_LRC"

logger = logging.getLogger(__name__)
_MANAGED_ID3_TXXX_DESCS = {ID3_PLAIN_DESC, ID3_SYNCED_DESC}


def _norm(s: str | None) -> str | None:
    """Normalize optional strings (strip + convert empty to None)."""
    if not s:
        return None
    s = s.strip()
    return s or None


def _is_managed_uslt(frame: USLT) -> bool:
    return getattr(frame, "lang", "") == "und" and getattr(frame, "desc", "") == ""


def _prune_managed_id3_frames(tags: ID3) -> None:
    uslt_frames = [frame for frame in tags.getall("USLT") if not _is_managed_uslt(frame)]
    tags.setall("USLT", uslt_frames)
    txxx_frames = [frame for frame in tags.getall("TXXX") if getattr(frame, "desc", "") not in _MANAGED_ID3_TXXX_DESCS]
    tags.setall("TXXX", txxx_frames)


def embed_lyrics_for_track(track: Track, output_format: str = "both") -> None:
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
    output_format = (output_format or "both").strip() or "both"
    plain, synced = _select_lyrics_for_output(plain, synced, output_format)
    if output_format == "both" and synced and not plain:
        plain = _norm(plain_text_from_lrc(synced))

    embed_lyrics_in_file(path, plain, synced)


def _select_lyrics_for_output(
    plain: str | None,
    synced: str | None,
    output_format: str,
) -> tuple[str | None, str | None]:
    mode = (output_format or "both").strip()
    if mode == "synced_only":
        return None, synced
    if mode == "plain_only":
        return plain, None
    if mode == "prefer_synced":
        if synced:
            return None, synced
        return plain, None
    return plain, synced


def embed_lyrics_in_file(path: str, plain: str | None, synced: str | None) -> None:
    """
    Embed lyrics depending on file extension:
      - .mp3/.wav       -> ID3: USLT for plain + TXXX for synced (LYRICS)
      - .flac           -> Vorbis comments: UNSYNCEDLYRICS + LYRICS
      - .ogg/.oga/.opus -> Vorbis comments: UNSYNCEDLYRICS + LYRICS
      - .m4a/.mp4       -> MP4: ©lyr for plain + custom atom for synced
      - .mpc            -> APEv2: UNSYNCEDLYRICS + LYRICS
    """
    EMBEDDER_MAP = {
        ".mp3": _embed_mp3,
        ".wav": _embed_wav,
        ".flac": _embed_flac,
        ".ogg": _embed_ogg_vorbis,
        ".oga": _embed_ogg_vorbis,
        ".opus": _embed_ogg_opus,
        ".m4a": _embed_mp4,
        ".mp4": _embed_mp4,
        ".wma": _embed_asf,
        ".asf": _embed_asf,
        ".dsf": _embed_dsf,
        ".dff": _embed_dsdiff,
        ".mpc": _embed_musepack,
    }

    ext = Path(path).suffix.lower()
    embedder = EMBEDDER_MAP.get(ext)
    if embedder:
        try:
            embedder(path, plain, synced)
        except Exception as exc:
            logger.warning("Failed to embed lyrics in %s: %s", path, exc)
            raise
        return

    # Fallback: try a simple text-only lyrics field if mutagen supports it.
    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return

        if plain:
            audio["lyrics"] = [plain]
        elif "lyrics" in audio:
            del audio["lyrics"]

        audio.save()
    except Exception as exc:
        logger.warning("Failed to embed lyrics in %s (fallback): %s", path, exc)


def _embed_vorbis_comment(audio_cls, path: str, plain: str | None, synced: str | None) -> None:
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


def _embed_flac(path: str, plain: str | None, synced: str | None) -> None:
    _embed_vorbis_comment(FLAC, path, plain, synced)


def _embed_ogg_vorbis(path: str, plain: str | None, synced: str | None) -> None:
    _embed_vorbis_comment(OggVorbis, path, plain, synced)


def _embed_ogg_opus(path: str, plain: str | None, synced: str | None) -> None:
    _embed_vorbis_comment(OggOpus, path, plain, synced)


def _embed_mp3(path: str, plain: str | None, synced: str | None) -> None:
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    # Remove only the lyric frames owned by PyLrcGet.
    _prune_managed_id3_frames(tags)

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


def _embed_wav(path: str, plain: str | None, synced: str | None) -> None:
    audio = WAVE(path)
    if getattr(audio, "tags", None) is None:
        audio.add_tags()
    _write_id3_lyrics(audio.tags, plain, synced)
    audio.save()


def _write_id3_lyrics(tags: ID3, plain: str | None, synced: str | None) -> None:
    _prune_managed_id3_frames(tags)

    if plain:
        tags.add(
            USLT(
                encoding=3,
                lang="und",
                desc="",
                text=plain,
            )
        )
        tags.add(
            TXXX(
                encoding=3,
                desc=ID3_PLAIN_DESC,
                text=plain,
            )
        )

    if synced:
        tags.add(
            TXXX(
                encoding=3,
                desc=ID3_SYNCED_DESC,
                text=synced,
            )
        )


def _embed_mp4(path: str, plain: str | None, synced: str | None) -> None:
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


def _embed_asf(path: str, plain: str | None, synced: str | None) -> None:
    audio = ASF(path)

    if ASF_PLAIN_KEY in audio:
        del audio[ASF_PLAIN_KEY]
    if ASF_SYNCED_KEY in audio:
        del audio[ASF_SYNCED_KEY]

    if plain:
        audio[ASF_PLAIN_KEY] = [ASFUnicodeAttribute(plain)]
    if synced:
        audio[ASF_SYNCED_KEY] = [ASFUnicodeAttribute(synced)]

    audio.save()


def _embed_musepack(path: str, plain: str | None, synced: str | None) -> None:
    audio = Musepack(path)
    if getattr(audio, "tags", None) is None:
        audio.add_tags()

    tags = audio.tags
    for key in ("UNSYNCEDLYRICS", "LYRICS", "lyrics", "LRCLIB_LRC"):
        if key in tags:
            del tags[key]

    if plain:
        tags["UNSYNCEDLYRICS"] = APETextValue(plain)
    if synced:
        tags["LYRICS"] = APETextValue(synced)

    audio.save()


def _embed_dsf(path: str, plain: str | None, synced: str | None) -> None:
    audio = DSF(path)
    if getattr(audio, "tags", None) is None:
        audio.add_tags()
    _write_id3_lyrics(audio.tags, plain, synced)
    audio.save()


def _embed_dsdiff(path: str, plain: str | None, synced: str | None) -> None:
    audio = DSDIFF(path)
    if getattr(audio, "tags", None) is None:
        audio.add_tags()
    _write_id3_lyrics(audio.tags, plain, synced)
    audio.save()
