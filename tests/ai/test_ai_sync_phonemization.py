from __future__ import annotations

from tests import test_support as _test_support  # noqa: F401
from ui.workers.ai_sync_phonemization import EnglishG2PPhonemizer


def test_english_g2p_phonemizer_caches_normalized_words() -> None:
    calls = []

    def factory():
        def convert(word):
            calls.append(word)
            return ["HH", "EH1", "L", "OW0"]

        return convert

    phonemizer = EnglishG2PPhonemizer(g2p_factory=factory)

    first = phonemizer.phonemize("Hello", "en")
    second = phonemizer.phonemize("hello", "EN")

    assert first.phonemes == (">", "HH", "EH", "L", "OW", ">")
    assert second.words == ("hello",)
    assert calls == ["hello"]
    assert phonemizer.cache_size == 1


def test_english_g2p_phonemizer_rejects_other_languages() -> None:
    phonemizer = EnglishG2PPhonemizer(g2p_factory=lambda: lambda word: ["AH"])

    assert phonemizer.supports_language("ro") is False
    try:
        phonemizer.phonemize("salut", "ro")
    except ValueError as exc:
        assert "only supports" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-English phonemization should be rejected")


def test_english_g2p_phonemizer_has_bounded_cache() -> None:
    phonemizer = EnglishG2PPhonemizer(
        g2p_factory=lambda: lambda word: ["AH"],
        max_words=2,
    )

    phonemizer.phonemize_word("one")
    phonemizer.phonemize_word("two")
    phonemizer.phonemize_word("three")

    assert phonemizer.cache_size == 2
