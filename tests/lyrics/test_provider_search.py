from __future__ import annotations

from unittest.mock import patch

from lyrics.provider_search import search_configured_providers
from lyrics.providers.contracts import LyricsSearchContext, LyricsSearchResult


class _FakeProvider:
    def __init__(self, provider_id: str, *, error: Exception | None = None):
        self.provider_id = provider_id
        self.display_name = provider_id.title()
        self._error = error

    def search(self, context, *, cancel_event=None):
        del context, cancel_event
        if self._error is not None:
            raise self._error
        return [
            LyricsSearchResult(
                provider=self.provider_id,
                provider_track_id="1",
                title="Song",
                artist="Artist",
                album="Album",
                duration_seconds=180.0,
                instrumental=False,
                plain_lyrics="lyrics",
            )
        ]


def test_search_configured_providers_preserves_priority_and_partial_results():
    settings = {
        "priority": ["musixmatch", "lrclib"],
        "enabled": {"lrclib": True, "musixmatch": True},
    }
    providers = {
        "lrclib": _FakeProvider("lrclib"),
        "musixmatch": _FakeProvider("musixmatch", error=RuntimeError("temporary")),
    }

    with patch("lyrics.provider_search.LrclibProvider", return_value=providers["lrclib"]), patch(
        "lyrics.provider_search.MusixmatchProvider", return_value=providers["musixmatch"]
    ), patch("lyrics.provider_search.MusixmatchClient"):
        results, errors = search_configured_providers(
            "https://lrclib.test/api",
            settings,
            LyricsSearchContext(title="Song", artist="Artist"),
        )

    assert [result.provider for result in results] == ["lrclib"]
    assert errors == ["Musixmatch: temporary"]


def test_search_configured_providers_reports_empty_matrix():
    results, errors = search_configured_providers(
        "https://lrclib.test/api",
        {"priority": [], "enabled": {}},
        LyricsSearchContext(query="Song"),
    )

    assert results == []
    assert errors == ["No enabled lyrics providers."]
