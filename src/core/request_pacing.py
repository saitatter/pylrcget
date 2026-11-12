"""Process-wide, cancellable request pacing for LRCLIB instances."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

DEFAULT_REQUEST_INTERVAL_S = 1.0


def normalize_request_interval(value: object) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_REQUEST_INTERVAL_S
    return min(60.0, max(0.0, interval)) if math.isfinite(interval) else DEFAULT_REQUEST_INTERVAL_S


def retry_after_seconds(value: object) -> float | None:
    if not isinstance(value, (str, int, float)):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        try:
            target = parsedate_to_datetime(str(value))
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            seconds = (target - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


class RequestPacer:
    def __init__(self, interval_s: float = DEFAULT_REQUEST_INTERVAL_S) -> None:
        self._condition = threading.Condition()
        self._interval_s = normalize_request_interval(interval_s)
        self._last_started: dict[str, float] = {}
        self._cooldowns: dict[str, float] = {}

    def configure(self, interval_s: float) -> None:
        with self._condition:
            self._interval_s = normalize_request_interval(interval_s)
            self._condition.notify_all()

    def wait(self, instance: str, is_cancelled: Callable[[], bool]) -> None:
        with self._condition:
            while True:
                if is_cancelled():
                    raise InterruptedError("LRCLIB request cancelled")
                now = time.monotonic()
                last = self._last_started.get(instance)
                deadline = max(
                    (last + self._interval_s) if last is not None else now,
                    self._cooldowns.get(instance, 0.0),
                )
                if deadline <= now:
                    self._last_started[instance] = now
                    return
                self._condition.wait(timeout=min(deadline - now, 0.05))

    def defer(self, instance: str, delay_s: float) -> None:
        with self._condition:
            self._cooldowns[instance] = max(
                self._cooldowns.get(instance, 0.0), time.monotonic() + delay_s,
            )
            self._condition.notify_all()


lrclib_request_pacer = RequestPacer()
