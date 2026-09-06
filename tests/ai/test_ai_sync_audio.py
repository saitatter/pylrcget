from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_audio import DecodedAudioCache


class _Data:
    nbytes = 16


def test_decoded_audio_cache_reuses_validated_file_signature(tmp_path) -> None:
    path = tmp_path / "song.wav"
    path.write_bytes(b"audio")
    cache = DecodedAudioCache(max_items=2, max_bytes=100)
    calls = []

    first = cache.get(str(path), sample_rate=16000, loader=lambda: calls.append(1) or _Data())
    second = cache.get(str(path), sample_rate=16000, loader=lambda: calls.append(2) or _Data())

    assert first is second
    assert calls == [1]
    assert cache.stats()["hits"] == 1


def test_decoded_audio_cache_invalidates_when_file_changes(tmp_path) -> None:
    path = tmp_path / "song.wav"
    path.write_bytes(b"audio")
    cache = DecodedAudioCache(max_items=2, max_bytes=100)
    calls = []
    cache.get(str(path), sample_rate=16000, loader=lambda: calls.append(1) or _Data())
    path.write_bytes(b"changed audio")

    cache.get(str(path), sample_rate=16000, loader=lambda: calls.append(2) or _Data())

    assert calls == [1, 2]


def test_decoded_audio_cache_evicts_by_item_bound(tmp_path) -> None:
    cache = DecodedAudioCache(max_items=1, max_bytes=100)
    first_path = tmp_path / "one.wav"
    second_path = tmp_path / "two.wav"
    first_path.write_bytes(b"one")
    second_path.write_bytes(b"two")
    calls = []

    cache.get(str(first_path), sample_rate=16000, loader=lambda: calls.append("one") or _Data())
    cache.get(str(second_path), sample_rate=16000, loader=lambda: calls.append("two") or _Data())
    cache.get(str(first_path), sample_rate=16000, loader=lambda: calls.append("one-again") or _Data())

    assert calls == ["one", "two", "one-again"]
    assert cache.stats()["evictions"] == 2
