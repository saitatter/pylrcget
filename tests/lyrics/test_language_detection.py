from __future__ import annotations

from lyrics.language import (
    detect_lyrics_language,
    infer_album_language,
    infer_track_language,
)

ROMANIAN = (
    "Inima mea cauta drumul prin noapte, pasii se pierd dar lumina ramane aproape "
    "si ne cheama iar acasa. Alerg prin ploaie si caut raspunsuri, simt ca lumea se "
    "schimba in fiecare zi."
)
ENGLISH = (
    "My heart keeps searching through the night, my footsteps fade but the light "
    "stays close and calls me home again. I run through rain and try to find the "
    "answer, while the world keeps changing every day."
)
FRENCH = (
    "Mon cœur cherche encore dans la nuit, mes pas disparaissent mais la lumière "
    "reste proche et me ramène chez moi. Je cours sous la pluie pour trouver des "
    "réponses tandis que le monde change chaque jour."
)


def test_detects_language_after_removing_lrc_timestamps_and_metadata():
    synced = "[ar:Artist]\n" + "\n".join(
        f"[{index:02d}:00.00]{ROMANIAN}" for index in range(3)
    )

    result = detect_lyrics_language(None, synced)

    assert result is not None
    assert result.language == "ro"
    assert result.confidence >= 0.8


def test_short_or_instrumental_text_is_not_assigned_a_language():
    assert detect_lyrics_language("Hello, my friend") is None
    assert detect_lyrics_language("[au: instrumental]") is None


def test_conflicting_plain_and_synced_languages_are_treated_as_unknown():
    assert detect_lyrics_language(ENGLISH, FRENCH) is None


def test_album_language_requires_two_tracks_and_clear_majority():
    assert infer_album_language([ROMANIAN]) is None
    assert infer_album_language([ROMANIAN, ENGLISH]) is None
    assert infer_album_language([ROMANIAN, ROMANIAN, ENGLISH]) == "ro"


def test_track_lyrics_override_album_consensus_and_self_is_excluded():
    samples = [(1, ENGLISH), (2, ROMANIAN), (3, ROMANIAN)]

    assert infer_track_language(FRENCH, None, samples, track_id=1) == "fr"
    assert infer_track_language(None, None, samples, track_id=1) == "ro"
