from __future__ import annotations

import threading
from dataclasses import dataclass

from .tidal import TidalCatalogueError
from .tidal_transport import ExternalTidalHelperError


@dataclass
class _ProviderStatus:
    unavailable: bool = False
    fatal_error: str | None = None
    failures: int = 0
    skipped: int = 0


def is_fatal_provider_error(error: Exception) -> bool:
    """Return whether an error makes a provider unusable for this batch."""

    if isinstance(error, ExternalTidalHelperError):
        return True
    if isinstance(error, TidalCatalogueError):
        return error.status_code in {401, 403}
    return False


class ProviderHealthState:
    """Track provider availability for one operation without persistent state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._statuses: dict[str, _ProviderStatus] = {}

    def is_available(self, provider_id: str) -> bool:
        normalized = _normalize_provider_id(provider_id)
        with self._lock:
            status = self._statuses.get(normalized)
            if status is None or not status.unavailable:
                return True
            status.skipped += 1
            return False

    def record_failure(self, provider_id: str, error: Exception) -> bool:
        if not is_fatal_provider_error(error):
            return False
        normalized = _normalize_provider_id(provider_id)
        with self._lock:
            status = self._statuses.setdefault(normalized, _ProviderStatus())
            status.unavailable = True
            status.failures += 1
            status.fatal_error = str(error)
        return True

    def snapshot(self) -> dict[str, dict[str, object]]:
        with self._lock:
            return {
                provider_id: {
                    "available": not status.unavailable,
                    "fatal_error": status.fatal_error,
                    "failures": status.failures,
                    "skipped": status.skipped,
                }
                for provider_id, status in self._statuses.items()
            }

    def clear(self) -> None:
        with self._lock:
            self._statuses.clear()


def _normalize_provider_id(provider_id: str) -> str:
    return str(provider_id or "unknown").strip().casefold() or "unknown"
