from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from lyrics.providers import ProviderLookupResultCache
from tests.lyrics.test_bulk_provider_dedup import _job
from ui.workers.bulk_lyrics_download_worker import BulkLyricsDownloadWorker


def _key():
    return ("lrclib", "isrc", "artist", "title", "album", 180)


def test_provider_result_cache_distinguishes_clean_miss_from_uncached_key():
    cache = ProviderLookupResultCache()

    assert cache.get(_key()) == (False, None)
    cache.put(_key(), None)
    assert cache.get(_key()) == (True, None)
    assert cache.hits == 1
    assert cache.size == 1


def test_provider_result_cache_can_store_successful_match():
    cache = ProviderLookupResultCache()
    result = SimpleNamespace(provider="lrclib")

    cache.put(_key(), result)

    hit, cached = cache.get(_key())
    assert hit is True
    assert cached is result


def test_bulk_worker_reuses_completed_lookup_result():
    worker = BulkLyricsDownloadWorker("unused.sqlite", [], "https://lrclib.net/api")
    job = _job(track_id=1)
    fake_lyrics = SimpleNamespace(
        synced_lyrics=None,
        plain_lyrics="plain lyrics",
        track_name="Song",
        artist_name="Artist",
        album_name="Album",
        duration=180,
    )

    with patch("ui.workers.bulk_lyrics_download_worker.LrcLibAPI") as api_cls:
        api_cls.return_value.get_lyrics.return_value = fake_lyrics
        first = worker._fetch_job_match(job)
        second = worker._fetch_job_match(job)

    assert first.match is not None
    assert second.match is first.match
    assert api_cls.return_value.get_lyrics.call_count == 1
    assert worker._lookup_result_cache.hits == 1


def test_bulk_worker_does_not_cache_transient_lookup_errors():
    worker = BulkLyricsDownloadWorker("unused.sqlite", [], "https://lrclib.net/api")
    job = _job(track_id=1)

    with patch("ui.workers.bulk_lyrics_download_worker.LrcLibAPI") as api_cls:
        api_cls.return_value.get_lyrics.side_effect = RuntimeError("temporary")
        first = worker._fetch_job_match(job)
        second = worker._fetch_job_match(job)

    assert first.error == "temporary"
    assert second.error == "temporary"
    assert api_cls.return_value.get_lyrics.call_count == 2
