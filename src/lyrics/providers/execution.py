from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderExecutionPolicy:
    """Concurrency and pacing limits for one lyrics provider."""

    max_concurrency: int
    min_request_interval: float = 0.0

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("Provider concurrency must be at least one")
        if self.min_request_interval < 0:
            raise ValueError("Provider request interval cannot be negative")


_DEFAULT_POLICIES: dict[str, ProviderExecutionPolicy] = {
    "lrclib": ProviderExecutionPolicy(max_concurrency=4),
    "musixmatch": ProviderExecutionPolicy(max_concurrency=2, min_request_interval=0.15),
}


def get_provider_execution_policy(provider_id: str) -> ProviderExecutionPolicy:
    """Return a conservative policy for known providers and unknown extensions."""

    normalized = str(provider_id or "").strip().casefold()
    return _DEFAULT_POLICIES.get(normalized, ProviderExecutionPolicy(max_concurrency=1))


class ProviderExecutionCoordinator:
    """Apply independent concurrency and request pacing limits per provider."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._next_allowed: dict[str, float] = {}

    def acquire(self, provider_id: str, is_cancelled) -> bool:
        normalized = str(provider_id or "unknown").strip().casefold() or "unknown"
        policy = get_provider_execution_policy(normalized)
        with self._condition:
            semaphore = self._semaphores.setdefault(
                normalized,
                threading.BoundedSemaphore(policy.max_concurrency),
            )
        while not semaphore.acquire(timeout=0.05):
            if is_cancelled():
                return False
        with self._condition:
            while True:
                if is_cancelled():
                    semaphore.release()
                    return False
                remaining = self._next_allowed.get(normalized, 0.0) - time.monotonic()
                if remaining <= 0:
                    self._next_allowed[normalized] = time.monotonic() + policy.min_request_interval
                    return True
                self._condition.wait(timeout=min(remaining, 0.05))

    def release(self, provider_id: str) -> None:
        normalized = str(provider_id or "unknown").strip().casefold() or "unknown"
        with self._condition:
            semaphore = self._semaphores.get(normalized)
            if semaphore is not None:
                semaphore.release()
            self._condition.notify_all()

    def record_rate_limit(self, provider_id: str, delay_s: float) -> None:
        normalized = str(provider_id or "unknown").strip().casefold() or "unknown"
        deadline = time.monotonic() + max(0.0, float(delay_s))
        with self._condition:
            self._next_allowed[normalized] = max(self._next_allowed.get(normalized, 0.0), deadline)
            self._condition.notify_all()

    def clear(self) -> None:
        with self._condition:
            self._semaphores.clear()
            self._next_allowed.clear()
