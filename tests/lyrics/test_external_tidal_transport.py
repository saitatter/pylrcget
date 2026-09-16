from __future__ import annotations

import sys
import threading
from unittest.mock import Mock, patch

import pytest

from lyrics.providers import (
    ExternalTidalHelperError,
    ExternalTidalLyricsTransport,
    TrackLookupContext,
)


def _context() -> TrackLookupContext:
    return TrackLookupContext(
        track_id=1,
        file_path="C:/Music/song.flac",
        title="Song",
        artists=("Artist",),
        album="Album",
        album_artist="Artist",
        duration_seconds=243.2,
        track_number=1,
        isrc="USAAA0000001",
    )


def _transport(code: str, *, timeout_s: float = 2.0) -> ExternalTidalLyricsTransport:
    return ExternalTidalLyricsTransport(
        [sys.executable, "-c", code],
        timeout_s=timeout_s,
        poll_interval_s=0.01,
    )


def test_external_helper_round_trips_versioned_json_without_sending_local_path():
    code = (
        "import json,sys; "
        "request=json.load(sys.stdin); "
        "assert 'file_path' not in request['track']; "
        "print(json.dumps({'protocol_version':1,'provider':'tidal','ok':True,"
        "'provider_track_id':request['provider_track_id'],"
        "'plain_lyrics':'plain','synced_lyrics':'[00:01.00]synced'}))"
    )

    payload = _transport(code).get_lyrics("123", track=_context(), requested_mode="synced_only")

    assert payload is not None
    assert payload.plain_lyrics == "plain"
    assert payload.synced_lyrics == "[00:01.00]synced"
    assert payload.source == "external"


def test_external_helper_not_found_is_a_clean_miss():
    code = "import json; print(json.dumps({'protocol_version':1,'provider':'tidal','ok':False,'error':'not_found'}))"

    assert _transport(code).get_lyrics("123") is None


def test_external_helper_rejects_malformed_or_failed_responses():
    with pytest.raises(ExternalTidalHelperError, match="invalid JSON"):
        _transport("print('not json')").get_lyrics("123")

    code = "import sys; sys.stderr.write('helper boom'); sys.exit(3)"
    with pytest.raises(ExternalTidalHelperError, match="helper boom"):
        _transport(code).get_lyrics("123")


def test_external_helper_timeout_terminates_the_process():
    with pytest.raises(ExternalTidalHelperError, match="timed out"):
        _transport("import time; time.sleep(10)", timeout_s=0.1).get_lyrics("123")


def test_external_helper_cancellation_stops_without_returning_lyrics():
    cancelled = threading.Event()
    timer = threading.Timer(0.1, cancelled.set)
    timer.start()
    try:
        assert _transport("import time; time.sleep(10)").get_lyrics("123", cancel_event=cancelled) is None
    finally:
        timer.cancel()


def test_external_helper_requires_argv_and_never_enables_shell_execution():
    with pytest.raises(TypeError, match="argv sequence"):
        ExternalTidalLyricsTransport("python -c pass")  # type: ignore[arg-type]

    process = Mock()
    process.poll.return_value = 0
    process.returncode = 0
    process.communicate.return_value = ('{"ok":false,"error":"not_found"}', "")
    transport = ExternalTidalLyricsTransport(["helper.exe"])
    with patch("lyrics.providers.tidal_transport.subprocess.Popen", return_value=process) as popen:
        assert transport.get_lyrics("123") is None
    assert popen.call_args.kwargs["shell"] is False


def test_external_helper_rejects_output_over_configured_limit():
    code = "print('x' * 100)"
    transport = ExternalTidalLyricsTransport(
        [sys.executable, "-c", code],
        max_output_bytes=32,
        timeout_s=2.0,
        poll_interval_s=0.01,
    )

    with pytest.raises(ExternalTidalHelperError, match="exceeded 32 bytes"):
        transport.get_lyrics("123")
