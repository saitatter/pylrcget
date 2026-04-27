"""Tests for AI sync worker helper functions (no torch/whisper required)."""
from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401

from ui.workers.ai_sync_worker import _format_ts, _build_lrc_from_segments


def test_format_ts_zero():
    assert _format_ts(0) == "00:00.00"


def test_format_ts_basic():
    assert _format_ts(65.5) == "01:05.50"


def test_format_ts_negative_clamped():
    assert _format_ts(-1) == "00:00.00"


def test_format_ts_large():
    assert _format_ts(3661.99) == "61:01.99"


def test_build_lrc_empty():
    assert _build_lrc_from_segments([]) == ""


def test_build_lrc_basic():
    segments = [
        {"start": 5.0, "text": "Hello world"},
        {"start": 10.5, "text": "Second line"},
    ]
    result = _build_lrc_from_segments(segments)
    assert "[00:05.00] Hello world" in result
    assert "[00:10.50] Second line" in result


def test_build_lrc_skips_empty_text():
    segments = [
        {"start": 0.0, "text": ""},
        {"start": 1.0, "text": "  "},
        {"start": 2.0, "text": "Real line"},
    ]
    result = _build_lrc_from_segments(segments)
    lines = result.strip().split("\n")
    assert len(lines) == 1
    assert "Real line" in lines[0]
