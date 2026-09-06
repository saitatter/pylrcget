from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_local_rescue import (
    RescueWindow,
    build_rescue_windows,
    replace_segments_in_windows,
    transcribe_local_rescue,
)


def test_rescue_windows_merge_and_bound_context() -> None:
    result = build_rescue_windows(
        [(10, 12), (11, 13), (30, 32)],
        audio_duration_seconds=35,
        context_seconds=2,
        max_windows=2,
    )

    assert result == [RescueWindow(8, 15), RescueWindow(28, 34)]


def test_local_rescue_reanchors_segments_to_absolute_audio_time() -> None:
    class _Model:
        def transcribe(self, audio, **kwargs):
            assert len(audio) == 2 * 16_000
            assert kwargs == {"language": "ro"}
            return {"segments": [{"start": 0.5, "end": 1.5, "text": "local"}]}

    result = transcribe_local_rescue(
        _Model(),
        [0] * (10 * 16_000),
        [RescueWindow(4, 6)],
        language="ro",
    )

    assert result == [{"start": 4.5, "end": 5.5, "text": "local"}]


def test_rescue_replaces_only_segments_inside_suspicious_window() -> None:
    result = replace_segments_in_windows(
        [
            {"start": 0, "end": 4, "text": "keep"},
            {"start": 5, "end": 8, "text": "replace"},
            {"start": 9, "end": 12, "text": "keep"},
        ],
        [{"start": 5.5, "end": 6.5, "text": "rescued"}],
        [RescueWindow(5, 8)],
    )

    assert [segment["text"] for segment in result] == ["keep", "rescued", "keep"]
