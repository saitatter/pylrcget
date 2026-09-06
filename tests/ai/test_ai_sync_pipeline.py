from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_pipeline import (
    _legacy_full_retries_enabled,
    _relaxed_vad_retry_configs,
)


def test_legacy_full_retry_path_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PYLRCGET_AI_LEGACY_FULL_RETRIES", raising=False)

    assert _legacy_full_retries_enabled() is False


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
