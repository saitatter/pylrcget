from __future__ import annotations

import base64
import binascii
import struct
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.asf import ASF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC
from mutagen.mp4 import MP4
from mutagen.musepack import Musepack
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis


_SIDECAR_COVER_NAMES = (
    "cover.jpg",
    "cover.jpeg",
    "cover.png",
    "folder.jpg",
    "folder.jpeg",
    "folder.png",
    "front.jpg",
    "front.jpeg",
    "front.png",
    "album.jpg",
    "album.jpeg",
    "album.png",
    "artwork.jpg",
    "artwork.jpeg",
    "artwork.png",
)


def find_sidecar_cover_path(audio_path: str | None) -> Path | None:
    if not audio_path:
        return None

    folder = Path(audio_path).resolve().parent
    for name in _SIDECAR_COVER_NAMES:
        candidate = folder / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def extract_embedded_cover_bytes(audio_path: str | None) -> bytes | None:
    if not audio_path:
        return None

    try:
        audio = MutagenFile(audio_path, easy=False)
    except (OSError, ValueError):
        return None

    if audio is None:
        return None

    try:
        if isinstance(audio, ASF):
            for picture in audio.get("WM/Picture", []):
                data = getattr(picture, "data", None)
                if data:
                    return bytes(data)

        if isinstance(audio, FLAC) and getattr(audio, "pictures", None):
            picture = audio.pictures[0]
            return bytes(getattr(picture, "data", b"") or b"")

        if isinstance(audio, MP4):
            covers = audio.tags.get("covr", []) if audio.tags else []
            if covers:
                cover = covers[0]
                return bytes(cover)

        if isinstance(audio, Musepack) and getattr(audio, "tags", None):
            for key in ("Cover Art (Front)", "Cover Art (Front).jpg", "Cover Art (Front).png"):
                picture = audio.tags.get(key)
                if not picture:
                    continue
                raw = bytes(picture)
                if b"\x00" in raw:
                    _, image_data = raw.split(b"\x00", 1)
                else:
                    image_data = raw
                if image_data:
                    return image_data

        if hasattr(audio, "tags") and audio.tags:
            for tag in audio.tags.values():
                if isinstance(tag, APIC):
                    return bytes(tag.data or b"")

        if isinstance(audio, (OggVorbis, OggOpus)) and audio.tags:
            metadata_blocks = audio.tags.get("metadata_block_picture", [])
            for raw in metadata_blocks:
                try:
                    picture = Picture(base64.b64decode(raw))
                    if picture.data:
                        return bytes(picture.data)
                except (ValueError, struct.error):
                    continue

            coverart_blocks = audio.tags.get("coverart", [])
            for raw in coverart_blocks:
                try:
                    data = base64.b64decode(raw)
                    if data:
                        return data
                except (ValueError, binascii.Error):
                    continue
    except (OSError, ValueError, KeyError):
        return None

    return None
