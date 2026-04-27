"""Tests for core.lrclib_client."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore[assignment]

from tests import test_support as _test_support  # noqa: F401

from core.lrclib_client import (
    LrcLibAPI,
    LrcLibError,
    NotFoundError,
    RateLimitError,
    ServerError,
    _raise_for_status,
    _lyrics_from_dict,
    _search_result_from_dict,
    solve_challenge,
    _is_nonce_valid,
)


# When pytest is not installed (e.g. CI running ``unittest discover``),
# expose an empty suite so the runner does not choke on bare functions.
if pytest is None:
    def load_tests(loader, tests, pattern):
        return unittest.TestSuite()


# ---------------------------------------------------------------------------
# _raise_for_status
# ---------------------------------------------------------------------------

def _mock_response(status_code, reason="", body=None, ok=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.reason = reason
    resp.ok = ok if ok is not None else (200 <= status_code < 400)
    if body is not None:
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.json.side_effect = ValueError
        resp.text = ""
    return resp


def test_raise_for_status_ok():
    _raise_for_status(_mock_response(200, ok=True))


def test_raise_for_status_404():
    with pytest.raises(NotFoundError) as exc_info:
        _raise_for_status(_mock_response(404, "Not Found"))
    assert exc_info.value.status_code == 404


def test_raise_for_status_429():
    with pytest.raises(RateLimitError):
        _raise_for_status(_mock_response(429, "Too Many Requests"))


def test_raise_for_status_500():
    with pytest.raises(ServerError):
        _raise_for_status(_mock_response(500, "Internal Server Error"))


def test_raise_for_status_generic():
    with pytest.raises(LrcLibError):
        _raise_for_status(_mock_response(403, "Forbidden"))


# ---------------------------------------------------------------------------
# Model helpers
# ---------------------------------------------------------------------------

def test_lyrics_from_dict():
    d = {
        "id": 42,
        "name": "test",
        "trackName": "Song",
        "artistName": "Artist",
        "albumName": "Album",
        "duration": 180,
        "instrumental": False,
        "plainLyrics": "hello",
        "syncedLyrics": "[00:00.00] hello",
    }
    lyr = _lyrics_from_dict(d)
    assert lyr.id == 42
    assert lyr.track_name == "Song"
    assert lyr.plain_lyrics == "hello"


def test_search_result_from_dict():
    d = {
        "id": 1,
        "name": "",
        "trackName": "T",
        "artistName": "A",
        "albumName": "Al",
        "duration": 60,
        "instrumental": True,
    }
    sr = _search_result_from_dict(d)
    assert sr.instrumental is True
    assert sr.plain_lyrics is None


# ---------------------------------------------------------------------------
# Challenge solver
# ---------------------------------------------------------------------------

def test_is_nonce_valid():
    import hashlib
    prefix = "test"
    nonce = 0
    digest = hashlib.sha256(f"{prefix}{nonce}".encode()).digest()
    # target must be greater than digest for validity
    target = bytes([0xFF] * 32)
    assert _is_nonce_valid(prefix, nonce, target) is True
    target = bytes([0x00] * 32)
    assert _is_nonce_valid(prefix, nonce, target) is False


def test_solve_challenge():
    # Use a very easy target (all 0xFF) so any nonce works
    target_hex = "ff" * 32
    result = solve_challenge("easy", target_hex)
    assert result.isdigit()


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class TestLrcLibAPI:
    def _make_api(self, session=None):
        with patch("core.lrclib_client._get_app_version", return_value="1.0.0"):
            return LrcLibAPI(base_url="https://example.com/api", session=session or MagicMock())

    def test_get_lyrics(self):
        session = MagicMock()
        resp = _mock_response(200, ok=True, body={
            "id": 1, "name": "", "trackName": "T", "artistName": "A",
            "albumName": "Al", "duration": 100, "instrumental": False,
        })
        session.request.return_value = resp
        api = self._make_api(session)
        lyr = api.get_lyrics("T", "A", "Al", 100)
        assert lyr.track_name == "T"

    def test_search_lyrics_empty_on_404(self):
        session = MagicMock()
        resp = _mock_response(404, "Not Found")
        session.request.return_value = resp
        api = self._make_api(session)
        result = api.search_lyrics(query="nonexistent")
        assert result == []

    def test_search_lyrics_requires_query_or_track(self):
        api = self._make_api()
        with pytest.raises(ValueError, match="Either query or track_name"):
            api.search_lyrics()

    def test_get_lyrics_by_id(self):
        session = MagicMock()
        resp = _mock_response(200, ok=True, body={
            "id": 5, "name": "", "trackName": "X", "artistName": "Y",
            "albumName": "Z", "duration": 200, "instrumental": False,
        })
        session.request.return_value = resp
        api = self._make_api(session)
        lyr = api.get_lyrics_by_id(5)
        assert lyr.id == 5
