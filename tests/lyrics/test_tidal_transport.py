from __future__ import annotations

import threading

from lyrics.providers import TidalLyricsPayload, TidalLyricsTransport


class _FakeTidalTransport:
    def get_lyrics(self, tidal_track_id: str, *, cancel_event=None):
        if cancel_event is not None and cancel_event.is_set():
            return None
        return TidalLyricsPayload(
            plain_lyrics="plain",
            synced_lyrics="[00:01.00]synced",
            source="external",
        )


def test_tidal_transport_contract_keeps_payload_provider_neutral():
    transport: TidalLyricsTransport = _FakeTidalTransport()

    payload = transport.get_lyrics("123")

    assert payload is not None
    assert payload.plain_lyrics == "plain"
    assert payload.synced_lyrics == "[00:01.00]synced"
    assert payload.source == "external"


def test_tidal_transport_receives_cancellation_event():
    transport: TidalLyricsTransport = _FakeTidalTransport()
    cancelled = threading.Event()
    cancelled.set()

    assert transport.get_lyrics("123", cancel_event=cancelled) is None
