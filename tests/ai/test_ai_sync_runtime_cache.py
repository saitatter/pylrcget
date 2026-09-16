from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers import ai_sync_runtime


def test_whisperx_cache_is_lru_bounded(monkeypatch) -> None:
    class _FakeWhisperX:
        def __init__(self):
            self.calls = []

        def load_model(self, model_name, **kwargs):
            self.calls.append(model_name)
            return {"model": model_name, "kwargs": kwargs}

    monkeypatch.setenv("PYLRCGET_AI_WHISPER_CACHE_SIZE", "1")
    monkeypatch.setattr(ai_sync_runtime, "_patch_whisperx_audio_loading", lambda: None)
    monkeypatch.setattr(ai_sync_runtime, "_patch_faster_whisper_compatibility", lambda: None)
    monkeypatch.setattr(ai_sync_runtime, "_patch_pyannote_compatibility", lambda: None)
    fake = _FakeWhisperX()
    ai_sync_runtime._clear_inference_caches()

    first = ai_sync_runtime._get_cached_whisperx_model(
        fake, "base", device="cpu", compute_type="int8"
    )
    ai_sync_runtime._get_cached_whisperx_model(
        fake, "small", device="cpu", compute_type="int8"
    )
    again = ai_sync_runtime._get_cached_whisperx_model(
        fake, "base", device="cpu", compute_type="int8"
    )

    assert first is not again
    assert fake.calls == ["base", "small", "base"]
    stats = ai_sync_runtime.get_inference_cache_stats()
    assert stats["whisperx_evictions"] == 2
    assert stats["whisperx_loads"] == 3


def test_align_model_cache_is_lru_bounded(monkeypatch) -> None:
    class _FakeWhisperX:
        def __init__(self):
            self.calls = []

        def load_align_model(self, language_code, device):
            self.calls.append(language_code)
            return language_code, {"device": device}

    monkeypatch.setenv("PYLRCGET_AI_ALIGN_CACHE_SIZE", "1")
    fake = _FakeWhisperX()
    ai_sync_runtime._clear_inference_caches()

    ai_sync_runtime._get_cached_align_model(fake, language_code="en", device="cpu")
    ai_sync_runtime._get_cached_align_model(fake, language_code="ro", device="cpu")
    ai_sync_runtime._get_cached_align_model(fake, language_code="en", device="cpu")

    assert fake.calls == ["en", "ro", "en"]
    assert ai_sync_runtime.get_inference_cache_stats()["align_evictions"] == 2
