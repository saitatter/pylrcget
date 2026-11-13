"""Numerical and fallback checks for inference-only English model DTW."""
from types import SimpleNamespace

import pytest

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai.ai_sync_lyrics_aligner import _patch_inference_dtw


def tensor_runtime():
    return pytest.importorskip("torch")


@pytest.mark.parametrize("device", ["cpu", "cuda"])
@pytest.mark.parametrize("seed", [0, 7, 19])
def test_model_dtw_preserves_float32_accumulation_and_device(device, seed):
    torch = tensor_runtime()
    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA unavailable")
    generator = torch.Generator().manual_seed(seed)
    scores = torch.randn((2, 11, 5), generator=generator, dtype=torch.float32).to(device)
    expected = torch.full((2, 12, 6), -100000.0, device=device)
    expected[:, 0, 0] = 200000
    for row in range(1, 12):
        for column in range(1, 6):
            expected[:, row, column] = scores[:, row - 1, column - 1] + torch.maximum(
                expected[:, row - 1, column], expected[:, row - 1, column - 1],
            )
    def unexpected_fallback(*args, **kwargs):
        pytest.fail("Inference unexpectedly used the upstream implementation")
    module = SimpleNamespace(dtw_matrix=unexpected_fallback)
    _patch_inference_dtw(module)
    with torch.no_grad():
        actual = module.dtw_matrix(scores)
    assert actual.device == scores.device
    assert actual.dtype == torch.float32
    assert torch.equal(actual, expected[:, 1:, 1:])


def test_model_dtw_preserves_autograd_through_original_implementation():
    torch = tensor_runtime()
    calls = []
    def original(scores, **kwargs):
        calls.append(kwargs)
        return scores * 2
    module = SimpleNamespace(dtw_matrix=original)
    _patch_inference_dtw(module)
    scores = torch.ones((1, 3, 2), requires_grad=True)
    module.dtw_matrix(scores).sum().backward()
    assert torch.equal(scores.grad, torch.full_like(scores, 2))
    assert calls == [{"mode": "faster", "idx_to_skip": None}]


@pytest.mark.parametrize("options", [{"mode": "other"}, {"idx_to_skip": [1]}, {"dtype": "float64"}])
def test_model_dtw_delegates_unsupported_cases(options):
    torch = tensor_runtime()
    sentinel = object()
    module = SimpleNamespace(dtw_matrix=lambda *args, **kwargs: sentinel)
    _patch_inference_dtw(module)
    kwargs = {key: value for key, value in options.items() if key != "dtype"}
    dtype = torch.float64 if "dtype" in options else torch.float32
    with torch.no_grad():
        assert module.dtw_matrix(torch.ones((1, 3, 2), dtype=dtype), **kwargs) is sentinel


def test_model_dtw_patch_is_idempotent():
    module = SimpleNamespace(dtw_matrix=lambda *args, **kwargs: None)
    _patch_inference_dtw(module)
    first = module.dtw_matrix
    _patch_inference_dtw(module)
    assert module.dtw_matrix is first
