from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from itertools import pairwise
from threading import Barrier
from time import monotonic
from unittest.mock import MagicMock

import pytest

from core.lrclib_client import LrcLibAPI, RateLimitError
from core.request_pacing import (
    RequestPacer,
    normalize_request_interval,
    retry_after_seconds,
)
from lyrics.source_settings import (
    load_lyrics_source_settings,
    merge_lyrics_source_settings,
)


def test_workers_share_request_spacing():
    pacer = RequestPacer(0.025)
    barrier = Barrier(4)

    def request():
        barrier.wait()
        pacer.wait("instance", lambda: False)
        return monotonic()

    with ThreadPoolExecutor(max_workers=4) as pool:
        times = sorted(pool.map(lambda _: request(), range(4)))
    assert all(right - left >= 0.020 for left, right in pairwise(times))


def test_cooldown_wait_can_be_cancelled():
    pacer = RequestPacer(0)
    pacer.defer("instance", 3600)
    with pytest.raises(InterruptedError):
        pacer.wait("instance", lambda: True)
    # Another server has an independent cooldown.
    pacer.wait("other-instance", lambda: False)


@pytest.mark.parametrize("value", [None, "invalid", "nan", "inf"])
def test_invalid_intervals_use_default(value):
    assert normalize_request_interval(value) == 1.0


def test_retry_after_supports_seconds_dates_and_bad_headers():
    assert retry_after_seconds("12") == 12
    assert retry_after_seconds("-1") == 0
    assert retry_after_seconds("bad") is None
    assert retry_after_seconds("nan") is None
    future = datetime.now(UTC) + timedelta(seconds=60)
    assert 58 <= retry_after_seconds(format_datetime(future)) <= 60


def test_request_interval_persists_without_losing_other_preferences():
    state = merge_lyrics_source_settings(
        '{"other_preference":42}', {"lrclib": {"request_interval_s": 2.5}},
    )
    assert load_lyrics_source_settings(state)["lrclib"]["request_interval_s"] == 2.5
    assert '"other_preference":42' in state


def test_rate_limited_get_retries_with_shared_cooldown(monkeypatch):
    pacer = MagicMock()
    monkeypatch.setattr("core.lrclib_client.lrclib_request_pacer", pacer)
    session = MagicMock()
    limited = MagicMock(ok=False, status_code=429, reason="Too Many Requests")
    limited.headers = {"Retry-After": "12"}
    limited.json.return_value = {}
    success = MagicMock(ok=True, status_code=200)
    success.json.return_value = {"id": 42}
    session.request.side_effect = [limited, success]
    api = LrcLibAPI("https://example.com/api", session=session)
    assert api.get_lyrics_by_id(42).id == 42
    assert pacer.wait.call_count == 2
    pacer.defer.assert_called_once_with("https://example.com/api", 12)


def test_persistent_rate_limit_has_bounded_retries(monkeypatch):
    pacer = MagicMock()
    monkeypatch.setattr("core.lrclib_client.lrclib_request_pacer", pacer)
    session = MagicMock()
    limited = MagicMock(ok=False, status_code=429, reason="Too Many Requests")
    limited.headers = {}
    limited.json.return_value = {}
    session.request.return_value = limited
    with pytest.raises(RateLimitError):
        LrcLibAPI(session=session).get_lyrics_by_id(42)
    assert session.request.call_count == 3
