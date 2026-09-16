from __future__ import annotations

import threading
from typing import cast

from .contracts import LyricsProviderResult

LookupKey = tuple[str, str, str, str, str, int | None]


class ProviderLookupResultCache:
    """Thread-safe, in-memory cache scoped to one bulk lyrics operation."""

    _NOT_CACHED = object()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[LookupKey, LyricsProviderResult | None] = {}
        self._hits = 0

    def get(self, key: LookupKey) -> tuple[bool, LyricsProviderResult | None]:
        with self._lock:
            value = self._values.get(key, self._NOT_CACHED)
            if value is self._NOT_CACHED:
                return False, None
            self._hits += 1
            return True, cast(LyricsProviderResult | None, value)

    def put(self, key: LookupKey, result: LyricsProviderResult | None) -> None:
        """Store only completed lookups; callers must not store raised errors."""

        with self._lock:
            self._values[key] = result

    @property
    def hits(self) -> int:
        with self._lock:
            return self._hits

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._values)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._hits = 0
