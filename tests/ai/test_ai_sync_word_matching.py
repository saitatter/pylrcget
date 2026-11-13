"""Keep lyric-to-prediction matching semantics when exact words are common."""
from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai import ai_sync_lyrics_aligner as aligner


def test_exact_predictions_do_not_need_fuzzy_comparisons(monkeypatch):
    def unexpected_fuzzy(*args, **kwargs):
        raise AssertionError("Exact words must not invoke SequenceMatcher")
    monkeypatch.setattr(aligner, "SequenceMatcher", unexpected_fuzzy)
    assert aligner._build_lrc_from_predictions(
        "One small road\nTwo bright stars",
        [(1, "one"), (2, "small"), (3, "road"), (4, "two"), (5, "bright"), (6, "stars")],
    ) == "[00:01.00] One small road\n[00:04.00] Two bright stars"


def test_later_exact_prediction_beats_an_earlier_fuzzy_match():
    assert aligner._build_lrc_from_predictions(
        "abcdefghijklmnopqrst", [(1, "abcdefghijklmnopqrsx"), (2, "abcdefghijklmnopqrst")],
    ) == "[00:02.00] abcdefghijklmnopqrst"


def test_fuzzy_matching_remains_available():
    assert aligner._build_lrc_from_predictions(
        "abcdefghijklmnopqrst", [(1, "abcdefghijklmnopqrsx")],
    ) == "[00:01.00] abcdefghijklmnopqrst"


def test_repeated_exact_words_use_the_first_available_occurrence():
    assert aligner._build_lrc_from_predictions(
        "Same\nSame", [(1, "same"), (2, "same"), (3, "same")],
    ) == "[00:01.00] Same\n[00:02.00] Same"


def test_matching_does_not_expand_the_eight_prediction_window():
    predictions = [(index, "noise") for index in range(8)] + [(9, "target")]
    assert aligner._build_lrc_from_predictions("Target", predictions) == ""


def test_missing_first_word_does_not_invent_a_line_timestamp():
    assert aligner._build_lrc_from_predictions(
        "Absent hello\nNext", [(1, "hello"), (3, "next")],
    ) == "[00:03.00] Next"
