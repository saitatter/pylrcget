"""Tests for AI sync worker helper functions (no torch/whisper required)."""
from __future__ import annotations

import builtins

import pytest

from tests import test_support as _test_support  # noqa: F401

from ui.workers.ai_sync_worker import _format_ts, _build_lrc_from_segments, _check_ai_sync_available, get_missing_ai_dependencies


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


def test_ai_sync_availability_does_not_require_demucs(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"torch", "torchaudio", "soundfile", "whisper"}:
            return object()
        if name == "demucs":
            raise ImportError("demucs missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    ok, msg = _check_ai_sync_available()

    assert ok is True
    assert msg == ""


def test_ai_sync_availability_message_guides_exe_users(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"torch", "torchaudio", "soundfile", "whisper"}:
            raise ImportError(f"{name} missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    ok, msg = _check_ai_sync_available()

    assert ok is False
    assert "Missing AI dependencies:" in msg
    assert "pip install .[ai]" in msg
    assert "bundled Python" in msg


def test_get_missing_ai_dependencies_returns_expected_packages(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"torch", "soundfile"}:
            raise ImportError(f"{name} missing")
        if name in {"torchaudio", "whisper"}:
            return object()
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    missing = get_missing_ai_dependencies()

    assert missing == ["torch", "soundfile"]
