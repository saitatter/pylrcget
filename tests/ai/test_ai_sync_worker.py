"""Tests for AI sync worker helper functions (no torch/whisper required)."""
from __future__ import annotations

import builtins

import pytest

from tests import test_support as _test_support  # noqa: F401

import ui.workers.ai_sync_worker as ai_sync_worker
from ui.workers.ai_sync_worker import (
    _align_lyrics_to_segments,
    _align_lyrics_to_segments_viterbi,
    _approximate_word_timestamps_from_segments,
    _transcribe_tail_window,
    _transcribe_fixed_windows,
    _align_segments_per_chunks,
    _should_use_per_chunk_alignment,
    _build_same_phrase_rewind_targets,
    _build_speech_candidate_mask,
    _build_guided_word_ranges,
    _build_lrc_from_segments,
    _build_lrc_from_plain_lines_and_segments,
    _check_ai_sync_available,
    _clear_inference_caches,
    _get_cached_align_model,
    _get_cached_whisperx_model,
    _format_ts,
    _normalized_transcribe_language,
    _prepare_manual_line_anchors,
    _late_line_expected_position_bonus,
    _late_line_candidate_start_floor,
    _segment_alignment_quality,
    _segment_reliable_tail_seconds,
    _segment_tail_seconds,
    _should_use_relaxed_vad_result,
    _should_retry_with_relaxed_vad,
    _select_best_relaxed_segments,
    _tail_rescue_alignment_indices,
    _tail_rescue_rewind_target_lag_indices,
    _ensure_strictly_increasing_alignment_indices,
    get_missing_ai_dependencies,
)


def test_format_ts_zero():
    assert _format_ts(0) == "00:00.00"


def test_format_ts_basic():
    assert _format_ts(65.5) == "01:05.50"


def test_format_ts_negative_clamped():
    assert _format_ts(-1) == "00:00.00"


def test_format_ts_large():
    assert _format_ts(3661.99) == "61:01.99"


def test_build_lrc_empty():
    assert _build_lrc_from_segments([]) == ""


def test_approximate_word_timestamps_from_segments_preserves_tail():
    segments = [
        {"start": 10.0, "end": 14.0, "text": "first second"},
        {"start": 30.0, "end": 34.0, "text": "last line"},
    ]

    recovered = _approximate_word_timestamps_from_segments(segments)

    assert [word["word"] for word in recovered[1]["words"]] == ["last", "line"]
    assert recovered[1]["words"][0]["start"] == 30.0
    assert recovered[1]["words"][-1]["start"] == 32.0


def test_transcribe_tail_window_offsets_relative_segments():
    class _Segment:
        start = 1.0
        end = 2.0
        text = "tail words"

    class _Model:
        def transcribe(self, audio, *, language, beam_size):
            assert len(audio) == 4000
            assert language == "en"
            assert beam_size == 5
            return iter([_Segment()]), object()

    class _Pipeline:
        model = _Model()

    result = _transcribe_tail_window(_Pipeline(), [0] * 20000, tail_start=1.0, language="en")

    assert result == [{"start": 2.0, "end": 3.0, "text": "tail words"}]


def test_transcribe_fixed_windows_deduplicates_overlapping_segments():
    class _Segment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text

    class _Model:
        def transcribe(self, audio, *, language, beam_size, condition_on_previous_text):
            relative_start = 45 if len(audio) == 960000 else 0
            assert condition_on_previous_text is False
            return iter([_Segment(relative_start, relative_start + 10, "same lyric line")]), object()

    class _Pipeline:
        model = _Model()

    result = _transcribe_fixed_windows(
        _Pipeline(),
        [0] * (16000 * 90),
        duration_s=90.0,
        language="en",
        window_s=60.0,
        step_s=45.0,
    )

    assert len(result) == 1


def test_align_segments_per_chunks_aligns_each_time_bucket():
    calls = []

    class _WhisperX:
        def align(self, segments, model, metadata, audio, device):
            calls.append([segment["text"] for segment in segments])
            return {
                "segments": [
                    {
                        **segment,
                        "words": [{"word": segment["text"], "start": segment["start"]}],
                    }
                    for segment in segments
                ]
            }

    segments = [
        {"start": 61.0, "end": 62.0, "text": "late"},
        {"start": 2.0, "end": 3.0, "text": "early"},
    ]

    result = _align_segments_per_chunks(
        _WhisperX(),
        segments,
        object(),
        object(),
        [0],
        "cpu",
    )

    assert calls == [["early"], ["late"]]
    assert [segment["text"] for segment in result] == ["early", "late"]
    assert all(segment["words"] for segment in result)


def test_align_segments_per_chunks_recovers_failed_chunk_coarsely():
    class _WhisperX:
        def align(self, segments, model, metadata, audio, device):
            if segments[0]["start"] > 60:
                raise RuntimeError("tail alignment failure")
            return {"segments": segments}

    result = _align_segments_per_chunks(
        _WhisperX(),
        [
            {"start": 2.0, "end": 4.0, "text": "early words"},
            {"start": 61.0, "end": 65.0, "text": "late words"},
        ],
        object(),
        object(),
        [0],
        "cpu",
    )

    assert result[1]["words"][0]["start"] == 61.0


def test_should_use_per_chunk_alignment_only_after_tail_loss():
    raw = [{"start": 0.0, "end": 100.0, "text": "lyrics"}]

    assert not _should_use_per_chunk_alignment(
        raw,
        [{"start": 0.0, "end": 92.1, "text": "lyrics"}],
    )
    assert _should_use_per_chunk_alignment(
        raw,
        [{"start": 0.0, "end": 87.9, "text": "lyrics"}],
    )


def test_build_lrc_basic():
    segments = [
        {"start": 5.0, "text": "Hello world"},
        {"start": 10.5, "text": "Second line"},
    ]
    result = _build_lrc_from_segments(segments)
    assert "[00:05.00] Hello world" in result
    assert "[00:10.50] Second line" in result


def test_build_lrc_skips_empty_text():
    segments = [
        {"start": 0.0, "text": ""},
        {"start": 1.0, "text": "  "},
        {"start": 2.0, "text": "Real line"},
    ]
    result = _build_lrc_from_segments(segments)
    lines = result.strip().split("\n")
    assert len(lines) == 1
    assert "Real line" in lines[0]


def test_build_lrc_skips_music_playing_markers():
    segments = [
        {"start": 0.0, "text": "[Music playing]"},
        {"start": 1.0, "text": "music playing"},
        {"start": 2.0, "text": "Real line"},
    ]
    result = _build_lrc_from_segments(segments)
    lines = result.strip().split("\n")
    assert lines == ["[00:02.00] Real line"]


def test_build_lrc_from_plain_lines_and_segments_preserves_plain_text():
    plain_lines = ["Exact line A", "Exact line B"]
    segments = [
        {"start": 5.0, "text": "ASR one"},
        {"start": 10.0, "text": "ASR two"},
    ]

    result = _build_lrc_from_plain_lines_and_segments(plain_lines, segments)

    assert result.splitlines() == [
        "[00:05.00] Exact line A",
        "[00:10.00] Exact line B",
    ]


def test_build_lrc_from_plain_lines_and_segments_keeps_blank_lines():
    plain_lines = ["Exact line A", "", "Exact line B"]
    segments = [
        {"start": 10.0, "text": "ASR one"},
        {"start": 20.0, "text": "ASR two"},
    ]

    result = _build_lrc_from_plain_lines_and_segments(plain_lines, segments)

    assert result.splitlines() == [
        "[00:10.00] Exact line A",
        "[00:15.00]",
        "[00:20.00] Exact line B",
    ]


def test_align_greedy_without_words_keeps_plain_lines():
    plain_lines = ["Keep this line", "And this line"]
    segments = [{"start": 2.0, "text": "Whisper guessed text"}]

    result = _align_lyrics_to_segments(plain_lines, segments)

    assert "Keep this line" in result
    assert "And this line" in result
    assert "Whisper guessed text" not in result


def test_align_viterbi_keeps_blank_lines_in_layout():
    plain_lines = ["Alpha line", "", "Beta line"]
    segments = [
        {
            "words": [
                {"word": "Alpha", "start": 2.0},
                {"word": "line", "start": 2.2},
                {"word": "Beta", "start": 8.0},
                {"word": "line", "start": 8.2},
            ]
        }
    ]

    result = _align_lyrics_to_segments_viterbi(plain_lines, segments)

    assert result.splitlines() == [
        "[00:02.00] Alpha line",
        "[00:05.00]",
        "[00:08.00] Beta line",
    ]


def test_align_viterbi_without_words_keeps_plain_lines():
    plain_lines = ["Keep this line", "And this line"]
    segments = [{"start": 2.0, "text": "Whisper guessed text"}]

    result = _align_lyrics_to_segments_viterbi(plain_lines, segments)

    assert "Keep this line" in result
    assert "And this line" in result
    assert "Whisper guessed text" not in result


def test_align_viterbi_does_not_duplicate_tail_after_missing_candidate():
    plain_lines = ["alpha", "beta", "gamma"]
    segments = [
        {
            "words": [
                {"word": "alpha", "start": 1.0, "score": 0.95},
                {"word": "beta", "start": 2.0, "score": 0.05},
                {"word": "gamma", "start": 10.0, "score": 0.95},
            ]
        }
    ]

    result = _align_lyrics_to_segments_viterbi(plain_lines, segments)

    assert result.splitlines() == [
        "[00:01.00] alpha",
        "[00:02.00] beta",
        "[00:10.00] gamma",
    ]


def test_ensure_strictly_increasing_alignment_indices_unstacks_tail():
    assert _ensure_strictly_increasing_alignment_indices(
        [1, 2, 3, 9, 9, 9],
        num_words=10,
    ) == [1, 2, 3, 7, 8, 9]


def test_ai_sync_availability_does_not_require_demucs(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"torch", "torchaudio", "soundfile", "whisperx"}:
            return object()
        if name == "demucs":
            raise ImportError("demucs missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    ok, msg = _check_ai_sync_available()

    assert ok is True
    assert msg == ""


def test_ai_sync_availability_message_guides_exe_users(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"torch", "torchaudio", "soundfile", "whisperx"}:
            raise ImportError(f"{name} missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    ok, msg = _check_ai_sync_available()

    assert ok is False
    assert "Missing AI dependencies:" in msg
    assert "pip install .[ai]" in msg
    assert "bundled Python" in msg


def test_get_missing_ai_dependencies_returns_expected_packages(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"torch", "soundfile"}:
            raise ImportError(f"{name} missing")
        if name in {"torchaudio", "whisperx"}:
            return object()
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    missing = get_missing_ai_dependencies()

    assert missing == ["torch", "soundfile"]


def test_prepare_manual_line_anchors_maps_to_nearest_word_index():
    plain_lines = ["line1", "line2", "line3"]
    words = [
        {"word": "a", "start": 1.0},
        {"word": "b", "start": 2.0},
        {"word": "c", "start": 3.1},
        {"word": "d", "start": 5.0},
    ]
    manual = [
        {"line_index": 0, "time_ms": 1900},
        {"line_index": 2, "time_ms": 4900},
    ]

    targets = _prepare_manual_line_anchors(plain_lines, words, manual)

    assert targets == {0: 1, 2: 3}


def test_prepare_manual_line_anchors_ignores_invalid_entries():
    plain_lines = ["line1"]
    words = [{"word": "a", "start": 0.5}]
    manual = [
        {"line_index": -1, "time_ms": 1000},
        {"line_index": 3, "time_ms": 1000},
        {"line_index": 0, "time_ms": "bad"},
        {"line_index": "x", "time_ms": 1000},
    ]

    targets = _prepare_manual_line_anchors(plain_lines, words, manual)

    assert targets == {}


def test_normalized_transcribe_language_auto_returns_none():
    assert _normalized_transcribe_language("auto") is None
    assert _normalized_transcribe_language("") is None
    assert _normalized_transcribe_language(None) is None


def test_normalized_transcribe_language_specific_code():
    assert _normalized_transcribe_language("EN") == "en"
    assert _normalized_transcribe_language(" ro ") == "ro"


def test_get_cached_whisperx_model_reuses_same_key():
    class _FakeWhisperX:
        def __init__(self):
            self.calls = 0

        def load_model(self, model_name, **kwargs):
            self.calls += 1
            return {"model_name": model_name, "kwargs": kwargs, "id": self.calls}

    fake = _FakeWhisperX()
    _clear_inference_caches()

    m1 = _get_cached_whisperx_model(fake, "base", device="cuda", compute_type="float16")
    m2 = _get_cached_whisperx_model(fake, "base", device="cuda", compute_type="float16")

    assert m1 is m2
    assert fake.calls == 1


def test_get_cached_align_model_reuses_same_key():
    class _FakeWhisperX:
        def __init__(self):
            self.calls = 0

        def load_align_model(self, language_code, device):
            self.calls += 1
            return (f"align-{language_code}-{device}-{self.calls}", {"meta": self.calls})

    fake = _FakeWhisperX()
    _clear_inference_caches()

    a1, m1 = _get_cached_align_model(fake, language_code="en", device="cuda")
    a2, m2 = _get_cached_align_model(fake, language_code="EN", device="cuda")

    assert a1 == a2
    assert m1 == m2
    assert fake.calls == 1


def test_build_guided_word_ranges_from_manual_targets():
    ranges = _build_guided_word_ranges(
        num_lines=6,
        num_words=200,
        manual_targets={1: 40, 4: 120},
        half_window=10,
    )

    assert len(ranges) == 6
    assert ranges[1][0] <= 40 < ranges[1][1]
    assert ranges[4][0] <= 120 < ranges[4][1]
    assert all(0 <= start < end <= 200 for start, end in ranges.values())


def test_build_speech_candidate_mask_uses_confidence_and_token_quality():
    plain_lines = ["Hi there"]
    words = [
        {"word": "Hi", "score": 0.9},
        {"word": "uh", "score": 0.1},
        {"word": "...", "score": 0.95},
        {"word": "there", "score": 0.4},
        {"word": "unknown", "score": 0.6},
        {"word": "unknown", "score": 0.9},
    ]

    mask = _build_speech_candidate_mask(
        words,
        plain_lines,
        min_confidence_in_vocab=0.35,
        min_confidence_out_vocab=0.78,
    )

    assert mask == [True, False, False, True, False, True]


def test_viterbi_ignores_low_confidence_candidates_for_matching():
    plain_lines = ["alpha line", "beta line"]
    segments = [
        {
            "words": [
                {"word": "alpha", "start": 1.0, "score": 0.10},
                {"word": "line", "start": 1.2, "score": 0.10},
                {"word": "beta", "start": 1.4, "score": 0.10},
                {"word": "line", "start": 1.6, "score": 0.10},
                {"word": "alpha", "start": 12.0, "score": 0.95},
                {"word": "line", "start": 12.2, "score": 0.95},
                {"word": "beta", "start": 16.0, "score": 0.95},
                {"word": "line", "start": 16.2, "score": 0.95},
            ]
        }
    ]

    result = _align_lyrics_to_segments_viterbi(plain_lines, segments)

    assert result.splitlines() == [
        "[00:12.00] alpha line",
        "[00:16.00] beta line",
    ]


def test_build_speech_candidate_mask_suppresses_sparse_tail_candidates():
    plain_lines = ["alpha beta gamma delta noise tail"]
    words = [
        {"word": "alpha", "start": 1.0, "score": 0.9},
        {"word": "beta", "start": 1.4, "score": 0.9},
        {"word": "gamma", "start": 1.8, "score": 0.9},
        {"word": "delta", "start": 2.2, "score": 0.9},
        {"word": "noise", "start": 2.6, "score": 0.9},
        {"word": "tail", "start": 20.0, "score": 0.95},
        {"word": "tail", "start": 24.0, "score": 0.95},
        {"word": "tail", "start": 28.0, "score": 0.95},
        {"word": "tail", "start": 32.0, "score": 0.95},
        {"word": "tail", "start": 36.0, "score": 0.95},
        {"word": "tail", "start": 40.0, "score": 0.95},
        {"word": "tail", "start": 44.0, "score": 0.95},
    ]

    mask = _build_speech_candidate_mask(
        words,
        plain_lines,
        min_confidence_in_vocab=0.3,
        min_confidence_out_vocab=0.3,
    )

    assert mask[:5] == [True, True, True, True, True]
    assert mask[5:] == [False, False, False, False, False, False, False]


def test_build_speech_candidate_mask_keeps_late_reentry_phrase_in_vocab():
    plain_lines = ["alpha beta gamma delta epsilon zeta eta theta you don't know nothing"]
    words = [
        {"word": "alpha", "start": 1.0, "score": 0.9},
        {"word": "beta", "start": 1.2, "score": 0.9},
        {"word": "gamma", "start": 1.4, "score": 0.9},
        {"word": "delta", "start": 1.6, "score": 0.9},
        {"word": "epsilon", "start": 1.8, "score": 0.9},
        {"word": "zeta", "start": 2.0, "score": 0.9},
        {"word": "eta", "start": 2.2, "score": 0.9},
        {"word": "theta", "start": 2.4, "score": 0.9},
        {"word": "you", "start": 28.0, "score": 0.92},
        {"word": "don't", "start": 28.2, "score": 0.01},
        {"word": "know", "start": 28.4, "score": 0.01},
        {"word": "nothing", "start": 28.6, "score": 0.01},
    ]

    mask = _build_speech_candidate_mask(
        words,
        plain_lines,
        min_confidence_in_vocab=0.3,
        min_confidence_out_vocab=0.3,
    )

    assert mask[:8] == [True, True, True, True, True, True, True, True]
    assert mask[8:] == [True, True, True, True]


def test_segment_tail_seconds_prefers_last_word_start():
    segments = [
        {"start": 0.0, "end": 10.0, "words": [{"word": "a", "start": 1.0}]},
        {"start": 10.0, "end": 20.0, "words": [{"word": "b", "start": 14.5}]},
    ]
    assert _segment_tail_seconds(segments) == 14.5


def test_segment_reliable_tail_seconds_ignores_isolated_outlier():
    segments = [
        {
            "start": 0.0,
            "end": 230.0,
            "words": [
                {"word": "a", "start": 100.0},
                {"word": "b", "start": 101.0},
                {"word": "c", "start": 103.0},
                {"word": "z", "start": 225.0},
            ],
        }
    ]

    assert _segment_tail_seconds(segments) == 225.0
    assert _segment_reliable_tail_seconds(segments) == 103.0


def test_should_retry_with_relaxed_vad_when_tail_coverage_is_low():
    audio_samples = [0.0] * (16000 * 240)  # 240s
    plain_lines = [f"line {i}" for i in range(20)]
    segments = [{"end": 60.0, "words": [{"word": "hello", "start": 58.0}]}]

    assert _should_retry_with_relaxed_vad(audio_samples, segments, plain_lines) is True


def test_should_retry_with_relaxed_vad_when_tail_has_only_isolated_outlier():
    audio_samples = [0.0] * (16000 * 240)  # 240s
    plain_lines = [f"line {i}" for i in range(20)]
    segments = [
        {
            "end": 230.0,
            "words": [
                {"word": "alpha", "start": 100.0},
                {"word": "beta", "start": 101.0},
                {"word": "gamma", "start": 103.0},
                {"word": "noise", "start": 225.0},
            ],
        }
    ]

    assert _should_retry_with_relaxed_vad(audio_samples, segments, plain_lines) is True


def test_should_not_retry_with_relaxed_vad_when_coverage_is_sufficient():
    audio_samples = [0.0] * (16000 * 240)  # 240s
    plain_lines = [f"line {i}" for i in range(20)]
    segments = [
        {
            "end": 230.0,
            "words": [
                {"word": "hello", "start": 223.0},
                {"word": "world", "start": 225.0},
                {"word": "again", "start": 227.0},
            ],
        }
    ]

    assert _should_retry_with_relaxed_vad(audio_samples, segments, plain_lines) is False


def test_segment_alignment_quality_penalizes_out_of_vocab_over_detection():
    """An over-detecting pass that dilutes real lyrics with out-of-vocabulary
    instrumental noise must score lower than a clean pass, because the strongly
    weighted vocab_ratio term drops as noise words are added."""
    plain = ["hello world", "goodbye moon"]

    def words_seg(pairs):
        return [{"words": [{"word": w, "start": t} for w, t in pairs], "end": pairs[-1][1] + 1.0}]

    clean = words_seg([("hello", 5.0), ("world", 6.0), ("goodbye", 60.0), ("moon", 61.0)])
    # Same real words at the same positions, but padded with noise tokens.
    noisy = words_seg(
        [
            ("hello", 5.0), ("world", 6.0),
            ("qzx", 20.0), ("wrp", 25.0), ("blm", 30.0), ("kvn", 35.0),
            ("goodbye", 60.0), ("moon", 61.0),
            ("zzt", 70.0), ("frb", 75.0), ("gnx", 80.0), ("plq", 85.0),
        ]
    )

    clean_quality = _segment_alignment_quality(clean, plain, 120.0)
    noisy_quality = _segment_alignment_quality(noisy, plain, 120.0)
    assert clean_quality > noisy_quality


def test_segment_alignment_quality_returns_low_value_without_words():
    quality = _segment_alignment_quality([{"start": 0.0, "text": "hello"}], ["line one"], 180.0)
    assert quality < -1e8


def test_should_use_relaxed_vad_result_when_tail_gain_is_large():
    default_segments = [{"words": [{"word": "a", "start": 80.0}], "end": 81.0}]
    relaxed_segments = [{"words": [{"word": "a", "start": 100.0}], "end": 101.0}]
    assert _should_use_relaxed_vad_result(default_segments, relaxed_segments, ["a"], 140.0) is True


def test_should_use_relaxed_vad_result_when_quality_gain_is_material(monkeypatch):
    default_segments = [{"words": [{"word": "a", "start": 80.0}], "end": 81.0}]
    relaxed_segments = [{"words": [{"word": "a", "start": 81.0}], "end": 82.0}]

    def fake_quality(segments, plain_lines, duration_s):
        return 0.80 if segments is relaxed_segments else 0.70

    monkeypatch.setattr(ai_sync_worker, "_segment_alignment_quality", fake_quality)
    assert _should_use_relaxed_vad_result(default_segments, relaxed_segments, ["a"], 140.0) is True


def test_select_best_relaxed_segments_picks_highest_quality_candidate(monkeypatch):
    default_segments = [{"words": [{"word": "a", "start": 80.0}], "end": 81.0}]
    cand_low = [{"words": [{"word": "a", "start": 100.0}], "end": 101.0}]
    cand_high = [{"words": [{"word": "a", "start": 100.0}], "end": 101.0}]

    # Both candidates clear the tail-gain gate (start 100 vs default 80, dur 140).
    quality_map = {id(default_segments): 0.70, id(cand_low): 0.80, id(cand_high): 0.95}
    monkeypatch.setattr(
        ai_sync_worker,
        "_segment_alignment_quality",
        lambda segments, plain_lines, duration_s: quality_map[id(segments)],
    )
    best = _select_best_relaxed_segments(default_segments, [cand_low, cand_high], ["a"], 140.0)
    assert best is cand_high


def test_select_best_relaxed_segments_returns_none_when_no_candidate_beats_default(monkeypatch):
    default_segments = [{"words": [{"word": "a", "start": 80.0}], "end": 130.0}]
    # Candidate has same/earlier tail and lower quality -> should be rejected.
    weak_candidate = [{"words": [{"word": "a", "start": 79.0}], "end": 129.0}]
    quality_map = {id(default_segments): 0.90, id(weak_candidate): 0.70}
    monkeypatch.setattr(
        ai_sync_worker,
        "_segment_alignment_quality",
        lambda segments, plain_lines, duration_s: quality_map[id(segments)],
    )
    assert _select_best_relaxed_segments(default_segments, [weak_candidate], ["a"], 140.0) is None


def test_late_line_expected_position_bonus_prefers_expected_region_for_weak_lines():
    near = _late_line_expected_position_bonus(
        line_idx=16,
        word_idx=160,
        num_lines=30,
        num_words=280,
        line_peak_emission=0.25,
    )
    far = _late_line_expected_position_bonus(
        line_idx=16,
        word_idx=80,
        num_lines=30,
        num_words=280,
        line_peak_emission=0.25,
    )
    assert near > 0.0
    assert near > far


def test_late_line_expected_position_bonus_disabled_for_strong_or_early_lines():
    strong = _late_line_expected_position_bonus(
        line_idx=18,
        word_idx=160,
        num_lines=30,
        num_words=280,
        line_peak_emission=0.9,
    )
    early = _late_line_expected_position_bonus(
        line_idx=4,
        word_idx=40,
        num_lines=30,
        num_words=280,
        line_peak_emission=0.2,
    )
    assert strong == 0.0
    assert early == 0.0


def test_late_line_candidate_start_floor_applies_only_for_weak_late_lines():
    floor = _late_line_candidate_start_floor(
        line_idx=24,
        num_lines=30,
        num_words=240,
        line_peak_emission=0.30,
    )
    assert floor is not None
    assert floor >= 0

    no_floor_strong = _late_line_candidate_start_floor(
        line_idx=24,
        num_lines=30,
        num_words=240,
        line_peak_emission=0.90,
    )
    assert no_floor_strong is None

    no_floor_early = _late_line_candidate_start_floor(
        line_idx=6,
        num_lines=30,
        num_words=240,
        line_peak_emission=0.20,
    )
    assert no_floor_early is None


def test_tail_rescue_alignment_indices_keeps_values_when_no_collapse():
    aligned = [i * 5 for i in range(20)]
    peaks = [0.8] * 20
    rescued = _tail_rescue_alignment_indices(aligned, peaks, num_words=200)
    assert rescued == aligned


def test_tail_rescue_alignment_indices_pushes_late_weak_collapsed_lines_forward():
    aligned = [i * 5 for i in range(14)] + [40, 41, 42, 43, 44, 45]
    peaks = [0.8] * 14 + [0.2] * 6
    rescued = _tail_rescue_alignment_indices(aligned, peaks, num_words=220)

    # Tail should be pushed forward and remain monotonic.
    assert rescued[-1] > aligned[-1]
    assert all(rescued[i] < rescued[i + 1] for i in range(len(rescued) - 1))


def test_tail_rescue_alignment_indices_uses_time_based_floor_on_sparse_tail():
    aligned = [5 * i for i in range(14)] + [70, 71, 72, 73, 74, 75]
    peaks = [0.8] * 14 + [0.2] * 6
    # Sparse timeline: last words extend much farther in time.
    starts = [float(i) for i in range(80)] + [160.0, 170.0, 180.0, 190.0, 200.0, 210.0]
    rescued = _tail_rescue_alignment_indices(
        aligned,
        peaks,
        num_words=len(starts),
        word_starts=starts,
    )
    assert rescued[-1] > aligned[-1]
    assert all(rescued[i] < rescued[i + 1] for i in range(len(rescued) - 1))


def test_same_phrase_rewind_targets_expand_tail_when_clusters_are_few():
    plain_lines = [
        "repeat line",
        "other",
        "repeat line",
        "other",
        "repeat line",
        "other",
        "repeat line",
    ]
    # Only one strong cluster detected for the repeated phrase around index ~10.
    # Tail expansion should synthesize later targets for later occurrences.
    emissions = [
        [0.0] * 60,
        [0.0] * 60,
        [0.0] * 60,
        [0.0] * 60,
        [0.0] * 60,
        [0.0] * 60,
        [0.0] * 60,
    ]
    for li in (0, 2, 4, 6):
        emissions[li][10] = 0.9

    targets = _build_same_phrase_rewind_targets(plain_lines, emissions, score_threshold=0.8, min_cluster_gap=3)

    assert targets[0] == 10
    assert targets[2] > targets[0]
    assert targets[4] > targets[2]
    assert targets[6] > targets[4]


def test_tail_rescue_rewind_target_lag_indices_pushes_confident_late_repeats_forward():
    aligned = [i * 4 for i in range(16)] + [60, 62, 64, 66, 68, 70]
    peaks = [0.8] * len(aligned)
    rewind_targets = {
        16: 96,
        17: 101,
        18: 106,
        19: 111,
        20: 116,
        21: 121,
    }

    rescued = _tail_rescue_rewind_target_lag_indices(
        aligned,
        rewind_targets,
        peaks,
        num_words=150,
    )

    assert rescued[-1] > aligned[-1]
    assert all(rescued[i] < rescued[i + 1] for i in range(len(rescued) - 1))


def test_tail_rescue_rewind_target_lag_indices_keeps_alignment_when_not_lagging():
    aligned = [i * 5 for i in range(20)]
    peaks = [0.9] * 20
    rewind_targets = {16: 82, 17: 87, 18: 92, 19: 97}

    rescued = _tail_rescue_rewind_target_lag_indices(
        aligned,
        rewind_targets,
        peaks,
        num_words=140,
    )

    assert rescued == aligned
