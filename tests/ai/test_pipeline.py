from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai.pipeline import (
    _legacy_full_retries_enabled,
    _relaxed_vad_retry_configs,
)


def test_legacy_full_retry_path_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PYLRCGET_AI_LEGACY_FULL_RETRIES", raising=False)

    assert _legacy_full_retries_enabled() is False


def test_manual_anchors_keep_the_guided_alignment_path(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from ui.workers.ai.pipeline import _try_lyrics_aligner

    monkeypatch.setattr("ui.workers.ai.pipeline._lyrics_aligner_available", lambda: True)
    router = Mock()
    worker = SimpleNamespace(manual_anchors=[{"line_index": 0, "time_ms": 2000}])
    assert _try_lyrics_aligner(worker, device="cpu", stage=2, stage_message="English", router=router) is None
    router.assert_not_called()


def test_legacy_full_retry_path_accepts_explicit_compatibility_values(monkeypatch) -> None:
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv("PYLRCGET_AI_LEGACY_FULL_RETRIES", value)
        assert _legacy_full_retries_enabled() is True


def test_default_cpu_retry_policy_runs_only_one_relaxed_vad_pass() -> None:
    configs = _relaxed_vad_retry_configs(device="cpu", legacy_full_retries=False)

    assert configs == ({"vad_onset": 0.15, "vad_offset": 0.05},)


def test_compatibility_retry_policy_keeps_all_cpu_relaxed_vad_passes() -> None:
    configs = _relaxed_vad_retry_configs(device="cpu", legacy_full_retries=True)

    assert configs == (
        {"vad_onset": 0.15, "vad_offset": 0.05},
        {"vad_onset": 0.10, "vad_offset": 0.03},
        {"vad_onset": 0.02, "vad_offset": 0.01},
    )


def test_cuda_retry_policy_is_already_single_pass() -> None:
    assert _relaxed_vad_retry_configs(
        device="cuda", legacy_full_retries=False
    ) == ({"vad_onset": 0.15, "vad_offset": 0.05},)
    assert _relaxed_vad_retry_configs(
        device="cuda", legacy_full_retries=True
    ) == ({"vad_onset": 0.15, "vad_offset": 0.05},)


def test_automatic_device_runs_the_english_aligner_on_cpu_and_separation_on_the_accelerator(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from ui.workers.ai.pipeline import _try_lyrics_aligner, align_with_optional_demucs

    monkeypatch.setattr("ui.workers.ai.pipeline._lyrics_aligner_available", lambda: True)
    devices: list[tuple[str, str]] = []

    @contextmanager
    def separated_audio(_path, *, device):
        devices.append(("separation", device))
        yield "vocals.wav"

    def aligner(path, lyrics, *, device):
        devices.append((path, device))
        return f"[00:01.00] {lyrics}"

    def router(*args, **kwargs):
        return align_with_optional_demucs(
            *args,
            **kwargs,
            aligner=aligner,
            demucs_available=lambda: True,
            separated_audio=separated_audio,
            quality=lambda _lrc, _lyrics: 0.0,
        )

    def run(requested: str) -> list[tuple[str, str]]:
        devices.clear()
        worker = SimpleNamespace(
            manual_anchors=[],
            audio_path="mix.flac",
            plain_lyrics="line",
            _device=requested,
            _enable_demucs_candidate=True,
            _emit_stage=lambda *_args: None,
        )
        assert _try_lyrics_aligner(worker, device="cuda", stage=2, stage_message="English", router=router)
        return list(devices)

    assert run("auto") == [("mix.flac", "cpu"), ("separation", "cuda"), ("vocals.wav", "cpu")]
    assert run("cuda") == [("mix.flac", "cuda"), ("separation", "cuda"), ("vocals.wav", "cuda")]
