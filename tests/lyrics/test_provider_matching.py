from __future__ import annotations

from lyrics.providers import (
    MatchQuality,
    TrackLookupContext,
    TrackMatchMetadata,
    normalize_isrc,
    normalize_match_text,
    score_track_match,
)


def _local(**overrides) -> TrackLookupContext:
    values = {
        "track_id": 1,
        "file_path": "C:/Music/song.flac",
        "title": "Song",
        "artists": ("Artist",),
        "album": "Album",
        "album_artist": "Artist",
        "duration_seconds": 180.0,
        "track_number": 1,
        "isrc": None,
    }
    values.update(overrides)
    return TrackLookupContext(**values)


def test_match_text_normalizes_unicode_punctuation_without_losing_unicode_letters():
    assert normalize_match_text("Beyoncé —  Song (Live)") == "beyoncé song live"


def test_normalize_isrc_accepts_standard_forms_only():
    assert normalize_isrc("us-aaa-00-00001") == "USAAA0000001"
    assert normalize_isrc("not an isrc") is None


def test_exact_isrc_with_plausible_metadata_is_exact_id():
    result = score_track_match(
        _local(isrc="USAAA0000001"),
        TrackMatchMetadata(
            title="Song",
            artists=("Artist",),
            album="Album",
            duration_seconds=181.0,
            isrc="US-AAA-00-00001",
        ),
    )

    assert result.quality is MatchQuality.EXACT_ID
    assert result.score == 100.0
    assert result.method == "exact isrc"


def test_exact_isrc_does_not_override_clear_metadata_conflict():
    result = score_track_match(
        _local(isrc="USAAA0000001"),
        TrackMatchMetadata(title="Different Song", artists=("Different Artist",), isrc="USAAA0000001"),
    )

    assert result.quality is not MatchQuality.EXACT_ID
    assert result.diagnostics["isrc_conflict"] is True


def test_strong_metadata_match_is_high_quality():
    result = score_track_match(
        _local(),
        TrackMatchMetadata(title="Song", artists=("Artist",), album="Album", duration_seconds=184.0),
    )

    assert result.quality is MatchQuality.HIGH
    assert result.score >= 80


def test_duration_scoring_has_conservative_tiers():
    near = score_track_match(
        _local(album=None),
        TrackMatchMetadata(title="Song", artists=("Artist",), duration_seconds=181.0),
    )
    far = score_track_match(
        _local(album=None),
        TrackMatchMetadata(title="Song", artists=("Artist",), duration_seconds=186.0),
    )

    assert near.diagnostics["duration_points"] == 20
    assert far.diagnostics["duration_points"] == 0
    assert near.score > far.score


def test_version_mismatch_penalties_are_visible_in_diagnostics():
    result = score_track_match(
        _local(title="Song (Live)"),
        TrackMatchMetadata(title="Song", artists=("Artist",), album="Album", duration_seconds=180.0),
    )

    assert result.diagnostics["version_penalty"] == 30


def test_multiple_artists_match_any_remote_artist():
    result = score_track_match(
        _local(artists=("Artist One", "Artist Two")),
        TrackMatchMetadata(title="Song", artists=("Artist Two",), album="Album", duration_seconds=180.0),
    )

    assert result.diagnostics["artist_similarity"] == 1.0
    assert result.diagnostics["artist_points"] == 29


def test_instrumental_mismatch_is_penalized_and_weak_match_is_rejected():
    result = score_track_match(
        _local(title="Obscure", artists=("Unknown",)),
        TrackMatchMetadata(title="Other", artists=("Else",), instrumental=True),
    )

    assert result.diagnostics["instrumental_penalty"] == 35
    assert result.quality is MatchQuality.REJECT
