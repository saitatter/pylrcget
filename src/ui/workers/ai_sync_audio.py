"""Bounded decoded-audio cache for alignment stages."""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(slots=True, frozen=True)
class DecodedAudio:
    data: Any
    sample_rate: int
    size_bytes: int


class DecodedAudioCache:
    def __init__(self, *, max_items: int = 2, max_bytes: int = 512 * 1024 * 1024) -> None:
        self.max_items = max(1, int(max_items))
        self.max_bytes = max(1, int(max_bytes))
        self._entries: OrderedDict[tuple[str, int, int, int], DecodedAudio] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(
        self,
        path: str,
        *,
        sample_rate: int,
        loader: Callable[[], Any],
    ) -> Any:
        key = _audio_key(path, sample_rate)
        if key is not None:
            with self._lock:
                cached = self._entries.get(key)
                if cached is not None:
                    self._entries.move_to_end(key)
                    self.hits += 1
                    return cached.data
                self.misses += 1
        data = loader()
        if key is None:
            return data
        size_bytes = _estimate_size_bytes(data)
        if size_bytes > self.max_bytes:
            return data
        entry = DecodedAudio(data, int(sample_rate), size_bytes)
        with self._lock:
            previous = self._entries.pop(key, None)
            if previous is not None:
                self._bytes -= previous.size_bytes
            self._entries[key] = entry
            self._bytes += size_bytes
            self._evict_locked()
        return data

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0
            self.hits = 0
            self.misses = 0
            self.evictions = 0

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "bytes": self._bytes,
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
            }

    def _evict_locked(self) -> None:
        while len(self._entries) > self.max_items or self._bytes > self.max_bytes:
            _key, entry = self._entries.popitem(last=False)
            self._bytes -= entry.size_bytes
            self.evictions += 1


def _audio_key(path: str, sample_rate: int) -> tuple[str, int, int, int] | None:
    try:
        source = Path(path).resolve()
        stat = source.stat()
    except (OSError, RuntimeError, ValueError):
        return None
    return (str(source), int(stat.st_mtime_ns), int(stat.st_size), int(sample_rate))


def _estimate_size_bytes(data: Any) -> int:
    value = getattr(data, "nbytes", None)
    if isinstance(value, (int, float)):
        return max(1, int(value))
    try:
        return max(1, int(len(data)) * 4)
    except (TypeError, AttributeError):
        return 1


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


_DECODED_AUDIO_CACHE = DecodedAudioCache(
    max_items=_env_int("PYLRCGET_AI_AUDIO_CACHE_ITEMS", 2),
    max_bytes=_env_int("PYLRCGET_AI_AUDIO_CACHE_MB", 512) * 1024 * 1024,
)


def get_cached_audio(path: str, *, sample_rate: int, loader: Callable[[], Any]) -> Any:
    return _DECODED_AUDIO_CACHE.get(path, sample_rate=sample_rate, loader=loader)


def clear_audio_cache() -> None:
    _DECODED_AUDIO_CACHE.clear()


def get_audio_cache_stats() -> dict[str, int]:
    return _DECODED_AUDIO_CACHE.stats()


__all__ = [
    "DecodedAudio",
    "DecodedAudioCache",
    "clear_audio_cache",
    "get_audio_cache_stats",
    "get_cached_audio",
]
