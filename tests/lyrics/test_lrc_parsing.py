"""Tests for LRC parsing functions moved to core.utils."""
from __future__ import annotations

from core.utils import _ts_to_ms, ms_to_ts, parse_lrc, parse_ts_str
from tests import test_support as _test_support  # noqa: F401


def test_ms_to_ts_basic():
    assert ms_to_ts(0) == "00:00.00"
    assert ms_to_ts(61230) == "01:01.23"
    assert ms_to_ts(3600000) == "60:00.00"


def test_ms_to_ts_negative_clamped():
    assert ms_to_ts(-100) == "00:00.00"


def test_parse_ts_str_valid():
    assert parse_ts_str("01:23.45") == 83450
    assert parse_ts_str("0:05") == 5000
    assert parse_ts_str("1:02.5") == 62500


def test_parse_ts_str_comma():
    assert parse_ts_str("1:02,50") == 62500


def test_parse_ts_str_invalid():
    assert parse_ts_str("") is None
    assert parse_ts_str("abc") is None
    assert parse_ts_str(None) is None


def test_ts_to_ms():
    assert _ts_to_ms("1", "30", "50") == 90500
    assert _ts_to_ms("0", "0", None) == 0
    assert _ts_to_ms("0", "1", "5") == 1500


def test_parse_lrc_empty():
    assert parse_lrc("") == []
    assert parse_lrc(None) == []


def test_parse_lrc_basic():
    lrc = "[00:05.00] Hello\n[00:10.00] World"
    result = parse_lrc(lrc)
    assert len(result) == 2
    assert result[0] == (5000, "Hello")
    assert result[1] == (10000, "World")


def test_parse_lrc_sorted():
    lrc = "[00:10.00] Second\n[00:05.00] First"
    result = parse_lrc(lrc)
    assert result[0][1] == "First"
    assert result[1][1] == "Second"


def test_parse_lrc_ignores_metadata():
    lrc = "[ar: Artist]\n[ti: Title]\n[00:01.00] Lyrics"
    result = parse_lrc(lrc)
    assert len(result) == 1
    assert result[0][1] == "Lyrics"


def test_parse_lrc_multiple_timestamps():
    lrc = "[00:05.00][00:15.00] Repeated line"
    result = parse_lrc(lrc)
    assert len(result) == 2
    assert result[0] == (5000, "Repeated line")
    assert result[1] == (15000, "Repeated line")


def test_parse_lrc_empty_text_line():
    lrc = "[00:05.00]"
    result = parse_lrc(lrc)
    assert len(result) == 1
    assert result[0] == (5000, "")
