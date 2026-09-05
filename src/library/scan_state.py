from __future__ import annotations

from dataclasses import dataclass


TRACK_SCAN_STATE_SIGNATURE_VERSION = 1


@dataclass(frozen=True)
class TrackScanState:
    """Filesystem provenance persisted separately from application lyrics state."""

    track_id: int
    audio_mtime_ns: int | None = None
    audio_size: int | None = None
    sidecar_signature: str | None = None
    embedded_txt_present: bool | None = None
    embedded_lrc_present: bool | None = None
    sidecar_txt_present: bool | None = None
    sidecar_lrc_present: bool | None = None
    embedded_txt_lyrics: str | None = None
    embedded_lrc_lyrics: str | None = None
    signature_version: int = TRACK_SCAN_STATE_SIGNATURE_VERSION
    last_scan_at: float | None = None
