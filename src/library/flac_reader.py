"""Read-only FLAC tag loading that leaves embedded artwork on disk."""
from __future__ import annotations

import struct
from typing import ClassVar

from mutagen.flac import FLAC, Picture


class _SkippedPicture(Picture):
    """Parse a picture block's layout and seek past its image bytes.

    Mutagen distrusts the declared size of picture blocks and walks their
    real layout instead, so the skip follows the same fields.
    """

    def load(self, data) -> None:
        self.type, length = struct.unpack(">2I", data.read(8))
        self.mime = data.read(length).decode("UTF-8", "replace")
        (length,) = struct.unpack(">I", data.read(4))
        self.desc = data.read(length).decode("UTF-8", "replace")
        self.width, self.height, self.depth, self.colors, length = struct.unpack(">5I", data.read(20))
        data.seek(length, 1)


class TagOnlyFLAC(FLAC):
    """FLAC tags and stream info without the artwork payload.

    Library scans only need tags, lyrics and duration. Cover art is commonly
    the largest part of the metadata, which matters on network shares.
    """

    METADATA_BLOCKS: ClassVar[list] = [
        _SkippedPicture if block is Picture else block for block in FLAC.METADATA_BLOCKS
    ]

    def save(self, *args, **kwargs):
        raise RuntimeError("TagOnlyFLAC is read-only; saving it would drop embedded artwork")

    def delete(self, *args, **kwargs):
        raise RuntimeError("TagOnlyFLAC is read-only; deleting through it would drop embedded artwork")


def open_flac_tags(path: str) -> TagOnlyFLAC | None:
    """Return FLAC tags for ``path``, or None when the generic loader must decide.

    Mutagen's type detection always selects FLAC for a ``.flac`` file that
    parses as FLAC, so a successful load here matches the generic result.
    """
    try:
        return TagOnlyFLAC(path)
    except Exception:  # noqa: BLE001 - the generic loader reports the real error.
        return None
