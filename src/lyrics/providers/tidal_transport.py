from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class TidalLyricsPayload:
    plain_lyrics: str | None
    synced_lyrics: str | None
    source: str | None = None


class TidalLyricsTransport(Protocol):
    """Lyrics transport kept independent from TIDAL catalogue resolution."""

    def get_lyrics(
        self,
        tidal_track_id: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> TidalLyricsPayload | None:
        ...
