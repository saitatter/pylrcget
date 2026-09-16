from __future__ import annotations

from tools.perf.benchmark_multi_provider import run_benchmark


def test_multi_provider_benchmark_is_fixture_backed_and_deduplicates():
    result = run_benchmark(track_count=20, duplicate_every=4, workers=2)

    assert result["tracks_processed"] == 20
    assert result["unique_lookup_keys"] == 5
    assert result["duplicates_avoided"] == 15
    assert result["successful_matches"] == 20
    assert result["pending_future_high_water_mark"] <= 8
    assert result["providers"]["lrclib"]["attempted"] == 5
    assert result["providers"]["tidal"]["attempted"] == 1
    assert result["providers"]["tidal"]["synced"] == 1
    assert result["result_cache_hits"] == 0


def test_multi_provider_benchmark_reports_direct_id_and_search_paths():
    result = run_benchmark(track_count=10, duplicate_every=1, workers=1)

    lrclib = result["providers"]["lrclib"]
    assert lrclib["direct_id_lookups"] > 0
    assert lrclib["searches"] > 0
    assert result["providers"]["tidal"]["direct_id_lookups"] > 0
