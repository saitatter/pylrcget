from __future__ import annotations

import threading
from collections import OrderedDict
from typing import cast

from .contracts import LyricsProviderResult

LookupKey = tuple[str, str, str, str, str, int | None]


class ProviderLookupResultCache:
    """Thread-safe, in-memory cache scoped to one bulk lyrics operation."""

    _NOT_CACHED = object()

    def __init__(self, max_entries: int = 8192) -> None:
        if int(max_entries) < 1:
            raise ValueError("Provider result cache must allow at least one entry")
        self._lock = threading.Lock()
        self._max_entries = int(max_entries)
        self._values: OrderedDict[LookupKey, LyricsProviderResult | None] = OrderedDict()
        self._hits = 0

    def get(self, key: LookupKey) -> tuple[bool, LyricsProviderResult | None]:
        with self._lock:
            value = self._values.get(key, self._NOT_CACHED)
            if value is self._NOT_CACHED:
                return False, None
            self._values.move_to_end(key)
            self._hits += 1
            return True, cast(LyricsProviderResult | None, value)

    def put(self, key: LookupKey, result: LyricsProviderResult | None) -> None:
        """Store only completed lookups; callers must not store raised errors."""

        with self._lock:
            self._values[key] = result
            self._values.move_to_end(key)
            while len(self._values) > self._max_entries:
                self._values.popitem(last=False)

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
