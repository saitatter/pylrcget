from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from lyrics.providers import MatchQuality, TidalCatalogueClient, TrackLookupContext

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "tidal_matching_cases.json"
CASES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _context(case: dict) -> TrackLookupContext:
    local = case["local"]
    return TrackLookupContext(
        track_id=1,
        file_path="C:/Music/song.flac",
        title=local["title"],
        artists=(local["artist"],),
        album=local["album"],
        album_artist=local["artist"],
        duration_seconds=float(local["duration"]),
        track_number=local["track_number"],
        isrc=local["isrc"],
    )


def _response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(status_code=200, text="", json=lambda: payload)


def test_fixture_exact_isrc_match_is_deterministic_and_single_request():
    case = CASES["exact_isrc"]
    session = Mock()
    session.get.return_value = _response(case["payload"])
    client = TidalCatalogueClient("token", session=session)

    result = client.resolve_track(_context(case))

    assert result is not None
    assert result.track.provider_track_id == "tidal-exact"
    assert result.score.quality is MatchQuality.EXACT_ID
    assert result.score.method == "exact isrc"
    assert result.score.diagnostics["isrc_lookup"] == "hit"
    assert result.score.diagnostics["candidate_count"] == 1
    assert result.score.diagnostics["selected_remote_id"] == "tidal-exact"
    assert session.get.call_count == 1


def test_fixture_metadata_tie_uses_stable_provider_id_order():
    case = CASES["metadata_tie"]
    session = Mock()
    session.get.return_value = _response(case["payload"])
    client = TidalCatalogueClient("token", session=session)

    result = client.resolve_track(_context(case))

    assert result is not None
    assert result.track.provider_track_id == "100"
    assert result.score.quality is MatchQuality.HIGH


def test_fixture_rejects_metadata_mismatch():
    case = CASES["reject_mismatch"]
    session = Mock()
    session.get.return_value = _response(case["payload"])
    client = TidalCatalogueClient("token", session=session)

    assert client.resolve_track(_context(case)) is None
