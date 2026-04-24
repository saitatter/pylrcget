from __future__ import annotations

import unittest
from types import SimpleNamespace

from tests import test_support as _test_support  # noqa: F401
from ui.services.lyrics_match_retry import build_retry_search_queries, choose_best_candidate


class LyricsMatchRetryTests(unittest.TestCase):
    def test_build_retry_search_queries_relaxes_metadata_in_order(self):
        queries = build_retry_search_queries(
            artist="Air Supply",
            title="All Out Of Love",
            album="Greatest Hits",
        )

        self.assertEqual(
            [query.label for query in queries],
            [
                "artist + title + album",
                "artist + title",
                "free text: artist title",
                "title only",
                "free text: title",
            ],
        )
        self.assertEqual(queries[0].album, "Greatest Hits")
        self.assertEqual(queries[1].album, "")

    def test_choose_best_candidate_accepts_title_artist_match_when_album_differs(self):
        results = [
            SimpleNamespace(
                artist_name="Someone Else",
                track_name="All Out Of Love",
                album_name="Lost in Love",
                duration=240,
                plain_lyrics="wrong",
                synced_lyrics=None,
                instrumental=False,
            ),
            SimpleNamespace(
                artist_name="Air Supply",
                track_name="All Out of Love",
                album_name="Lost in Love",
                duration=240,
                plain_lyrics="plain",
                synced_lyrics="[00:01.00]plain",
                instrumental=False,
            ),
        ]

        candidate = choose_best_candidate(
            track_id=7,
            track_label="Air Supply - All Out Of Love",
            artist="Air Supply",
            title="All Out Of Love",
            album="Greatest Hits",
            query_label="artist + title",
            results=results,
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.artist_name, "Air Supply")
        self.assertEqual(candidate.album_name, "Lost in Love")
        self.assertEqual(candidate.kind, "Synced")
        self.assertGreaterEqual(candidate.score, 90)


if __name__ == "__main__":
    unittest.main()
