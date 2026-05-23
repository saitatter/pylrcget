"""Tests for scan_library exclusion helpers."""
from __future__ import annotations

import re

from tests import test_support as _test_support  # noqa: F401

from library.scan_library import (
    _normalize_excluded_paths,
    _compile_excluded_patterns,
    _is_path_excluded_variants,
)


def test_normalize_excluded_paths_empty():
    assert _normalize_excluded_paths(None) == []
    assert _normalize_excluded_paths("") == []


def test_normalize_excluded_paths_strips_trailing_sep():
    result = _normalize_excluded_paths("/music/rock/\n/music/pop")
    assert len(result) == 2
    for native, posix in result:
        assert not posix.endswith("/")


def test_compile_excluded_patterns_valid():
    patterns = _compile_excluded_patterns(r"\.mp3$" + "\n" + r"test.*")
    assert len(patterns) == 2
    assert all(isinstance(p, re.Pattern) for p in patterns)


def test_compile_excluded_patterns_invalid_regex():
    patterns = _compile_excluded_patterns("[invalid")
    assert patterns == []


def test_is_path_excluded_by_root():
    roots = [("/music/rock", "/music/rock")]
    assert _is_path_excluded_variants(
        "/music/rock/song.mp3", "/music/rock/song.mp3", "/music/rock/song.mp3",
        roots, []
    )


def test_is_path_excluded_exact_root():
    roots = [("/music/rock", "/music/rock")]
    assert _is_path_excluded_variants(
        "/music/rock", "/music/rock", "/music/rock",
        roots, []
    )


def test_is_path_not_excluded():
    roots = [("/music/rock", "/music/rock")]
    assert not _is_path_excluded_variants(
        "/music/pop/song.mp3", "/music/pop/song.mp3", "/music/pop/song.mp3",
        roots, []
    )


def test_is_path_excluded_by_pattern():
    patterns = [re.compile(r"\.tmp$", re.IGNORECASE)]
    assert _is_path_excluded_variants(
        "/music/file.tmp", "/music/file.tmp", "/music/file.tmp",
        [], patterns
    )


def test_is_path_not_excluded_by_pattern():
    patterns = [re.compile(r"\.tmp$", re.IGNORECASE)]
    assert not _is_path_excluded_variants(
        "/music/file.mp3", "/music/file.mp3", "/music/file.mp3",
        [], patterns
    )
