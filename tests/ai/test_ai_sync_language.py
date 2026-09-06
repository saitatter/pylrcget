from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers import ai_sync_pipeline
from ui.workers.ai_sync_demucs import AlignmentCandidate
from ui.workers.ai_sync_language import LanguageDetection, detect_text_language


def test_text_detector_identifies_ordinary_english_lyrics() -> None:
    result = detect_text_language(
        "I know the road is open\nAnd you will see me there\nWe are going home"
    )

    assert result.language == "en"
    assert result.confidence >= 0.74
    assert result.source == "text"


def test_text_detector_identifies_romanian_with_diacritics() -> None:
    result = detect_text_language("Șoapta rămâne în aer\nMâine începe aici")

    assert result.language == "ro"
    assert result.confidence >= 0.74


def test_text_detector_keeps_ambiguous_short_or_romanized_text_on_acoustic_fallback() -> None:
    assert detect_text_language("la la la").language is None
    assert detect_text_language("sakura hikari yume").language is None


def test_text_detector_marks_japanese_script_without_external_dependency() -> None:
    result = detect_text_language("静かな朝\n光が進む")

    assert result == LanguageDetection("ja", 0.99, "text-script")


def test_auto_known_english_routes_before_whisper_language_detection(monkeypatch) -> None:
    class _Emitter:
        def __init__(self):
            self.values = []

        def emit(self, *values):
            self.values.append(values)

    class _Worker:
        audio_path = "song.flac"
        plain_lyrics = "I know the road is open\nAnd you will see me there\nWe are going home"
        _language = "auto"
        _enable_demucs_candidate = False
        progress = _Emitter()
        completed = _Emitter()

        def _resolve_device(self):
            return "cpu"

        def _emit_stage(self, current, total, message):
            self.progress.emit(current, total, message)

        def isInterruptionRequested(self):
            return False

    monkeypatch.setattr(ai_sync_pipeline, "_check_ai_sync_available", lambda: (True, ""))
    monkeypatch.setattr(ai_sync_pipeline, "_lyrics_aligner_available", lambda: True)

    def router(*_args, **_kwargs):
        return AlignmentCandidate("[00:01.00] I know the road is open", "mix", 1.0)

    worker = _Worker()
    ai_sync_pipeline.run_ai_sync_pipeline(worker, align_optional_demucs=router)

    assert worker.completed.values == [
        (True, "Lyrics synchronized successfully with lyrics-aligner (mix).", "[00:01.00] I know the road is open")
    ]
