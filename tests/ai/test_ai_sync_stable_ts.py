from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_contracts import AlignmentOptions, AlignmentRequest
from ui.workers.ai_sync_stable_ts import StableTsResearchBackend


def _request(**extras) -> AlignmentRequest:
    return AlignmentRequest(
        job_id="stable-ts-test",
        audio_path="fixture.wav",
        plain_lyrics="Hello world\nGood morning",
        requested_language="en",
        manual_anchors=[],
        device="cpu",
        options=AlignmentOptions(extras=extras),
    )


def _aligned_result():
    return {
        "segments": [
            {
                "words": [
                    {"word": "Hello", "start": 1.0, "end": 1.4},
                    {"word": "world", "start": 1.5, "end": 1.9},
                    {"word": "Good", "start": 8.0, "end": 8.4},
                    {"word": "morning", "start": 8.5, "end": 9.0},
                ]
            }
        ]
    }


def test_stable_ts_full_mode_maps_word_timings_to_lyric_lines() -> None:
    calls = []

    def align(model, audio, text, *, language):
        calls.append((model, audio, text, language))
        return _aligned_result()

    backend = StableTsResearchBackend(
        object(),
        align_function=align,
        model_name="tiny.en",
    )
    result = backend.align(_request())

    assert calls == [(calls[0][0], "fixture.wav", "Hello world\nGood morning", "en")]
    assert result.to_lrc() == "[00:01.00] Hello world\n[00:08.00] Good morning"
    assert result.coverage == 1.0
    assert result.diagnostics["research_only"] is True
    assert result.diagnostics["stable_ts_mode"] == "full"


def test_stable_ts_local_mode_uses_bounded_candidate_segments() -> None:
    calls = []

    def align_words(model, audio, segments, *, language):
        calls.append((model, audio, segments, language))
        return _aligned_result()

    segments = [{"start": 0.0, "end": 10.0, "text": "Hello world Good morning"}]
    backend = StableTsResearchBackend(
        object(),
        align_function=lambda *_args, **_kwargs: None,
        align_words_function=align_words,
    )
    result = backend.align(_request(stable_ts_mode="local", stable_ts_segments=segments))

    assert calls[0][1:] == ("fixture.wav", segments, "en")
    assert result.diagnostics["stable_ts_mode"] == "local"
    assert result.coverage == 1.0


def test_stable_ts_does_not_create_lines_for_unmatched_text() -> None:
    backend = StableTsResearchBackend(
        object(),
        align_function=lambda *_args, **_kwargs: {"segments": []},
    )

    result = backend.align(_request())

    assert result.lines == []
    assert result.coverage == 0.0
    assert result.to_lrc() == ""


def test_stable_ts_rejects_local_mode_without_candidates() -> None:
    backend = StableTsResearchBackend(
        object(),
        align_function=lambda *_args, **_kwargs: None,
        align_words_function=lambda *_args, **_kwargs: None,
    )

    try:
        backend.align(_request(stable_ts_mode="local"))
    except ValueError as exc:
        assert "stable_ts_segments" in str(exc)
    else:  # pragma: no cover - assertion documents the required failure.
        raise AssertionError("local stable-ts mode accepted missing candidates")
