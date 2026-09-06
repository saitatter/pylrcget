from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_contracts import AlignedLine, AlignmentOptions, AlignmentRequest, AlignmentResult
from ui.workers.ai_sync_ctc import CtcModelRegistry, CtcModelSpec, GenericCtcBackend


def _request() -> AlignmentRequest:
    return AlignmentRequest(
        job_id="ctc-test",
        audio_path="C:/read-only/song.wav",
        plain_lyrics="one",
        requested_language="ro",
        manual_anchors=[],
        device="cpu",
        options=AlignmentOptions(),
    )


def _result() -> AlignmentResult:
    return AlignmentResult(
        lines=[AlignedLine(0, "one", 1.0, None, 0.9, "fixture")],
        language="ro",
        backend="fixture",
        coverage=1.0,
        confidence=0.9,
        structural_score=0.9,
        runtime_ms=2.0,
    )


def test_generic_ctc_backend_keeps_model_metadata_and_normalizes_backend_name() -> None:
    class _Engine:
        def align(self, request, model):
            assert request.job_id == "ctc-test"
            assert model.model_id == "fixture/ro"
            return _result()

    spec = CtcModelSpec(
        model_id="fixture/ro",
        language="ro",
        license="Apache-2.0",
        backend="ctranslate2",
        revision="abc123",
        tested_on_singing=True,
    )
    backend = GenericCtcBackend(spec, _Engine())

    result = backend.align(_request())

    assert backend.supports_language("RO")
    assert result.backend == "generic-ctc:fixture/ro"
    assert result.diagnostics["ctc_engine"] == "ctranslate2"
    assert backend.is_eligible() is False
    assert backend.is_eligible(allow_experimental=True) is True


def test_ctc_registry_does_not_mark_noncommercial_models_production_eligible() -> None:
    registry = CtcModelRegistry()
    registry.register(
        CtcModelSpec(
            model_id="restricted/ro",
            language="ro",
            license="CC-BY-NC 4.0",
            backend="torch",
            tested_on_singing=True,
            default_enabled=True,
        )
    )

    assert registry.get("ro", "restricted/ro") is not None
    assert registry.production_eligible("ro") == ()
