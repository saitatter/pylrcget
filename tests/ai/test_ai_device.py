from __future__ import annotations

import sys
from types import SimpleNamespace

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_runtime import available_torch_devices, resolve_torch_device


def _fake_torch(*, cuda: bool, mps: bool):
    return SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: cuda),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
    )


def test_auto_prefers_cuda_when_available(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=True, mps=True))

    assert resolve_torch_device("auto") == "cuda"
    assert available_torch_devices() == ["cuda", "mps", "cpu"]


def test_auto_falls_back_to_mps_then_cpu(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=False, mps=True))
    assert resolve_torch_device("auto") == "mps"

    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=False, mps=False))
    assert resolve_torch_device("auto") == "cpu"


def test_explicit_cuda_rejects_cpu_only_runtime(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=False, mps=False))

    try:
        resolve_torch_device("cuda")
    except RuntimeError as exc:
        assert "no CUDA support" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("CPU-only runtime unexpectedly accepted CUDA")
