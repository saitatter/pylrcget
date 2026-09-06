from __future__ import annotations

from pathlib import Path

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_contracts import AlignmentOptions, AlignmentRequest
from ui.workers.ai_sync_lyrics_aligner import (
    EnglishLyricsAlignerBackend,
    _build_lrc_from_predictions,
    _result_lines,
)


def _request(lyrics: str) -> AlignmentRequest:
    return AlignmentRequest(
        job_id="test",
        audio_path="C:/read-only/song.flac",
        plain_lyrics=lyrics,
        requested_language="en",
        manual_anchors=[],
        device="cpu",
        options=AlignmentOptions(),
    )


def test_warm_backend_reuses_compatibility_result_shape_without_audio_copy(tmp_path) -> None:
    backend = EnglishLyricsAlignerBackend(tmp_path, device="cpu")
    backend._word_predictions = lambda _audio, _lyrics: [
        (1.25, "one"),
        (3.5, "two"),
    ]

    result = backend.align(_request("One\nTwo"))

    assert result.to_lrc() == "[00:01.25] One\n[00:03.50] Two"
    assert result.diagnostics["audio_copied"] is False
    assert result.diagnostics["align_subprocess"] is False
    assert result.coverage == 1.0


def test_prediction_to_lrc_preserves_existing_word_match_rules() -> None:
    result = _build_lrc_from_predictions(
        "One small road\nTwo bright stars",
        [(1.0, "one"), (1.5, "small"), (2.0, "road"), (4.0, "two"), (4.5, "bright"), (5.0, "stars")],
    )

    assert result == "[00:01.00] One small road\n[00:04.00] Two bright stars"


def test_result_lines_keep_original_source_line_indexes() -> None:
    result = _result_lines("\nOne\n\nTwo", "[00:01.00] One\n[00:03.00] Two")

    assert [line.source_line_index for line in result] == [1, 3]
    assert [line.text for line in result] == ["One", "Two"]


def test_warm_backend_does_not_require_existing_audio_for_result_parsing(tmp_path) -> None:
    backend = EnglishLyricsAlignerBackend(Path(tmp_path), device="cpu")
    backend._word_predictions = lambda _audio, _lyrics: [(0.0, "hello")]

    result = backend.align(_request("Hello"))

    assert result.lines[0].start == 0.0
