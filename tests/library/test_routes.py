from __future__ import annotations

import unittest

from tests import test_support as _test_support  # noqa: F401
from ui.library_routes import (
    LibraryRoute,
    albums_all,
    albums_artist,
    albums_detail,
    artists_album,
    artists_all,
    artists_detail,
    deserialize_route,
    route_breadcrumbs,
    serialize_route,
    tracks_album,
    tracks_all,
    tracks_artist,
)


class LibraryRouteTests(unittest.TestCase):
    def test_serialize_and_deserialize_roundtrip(self):
        route = LibraryRoute(
            tab="artists",
            mode="artist_album",
            artist_ids=(1, 2),
            album_ids=(4, 5),
            artist_label="Artist",
            album_label="Album",
        )
        payload = serialize_route(route)
        restored = deserialize_route(payload)
        self.assertEqual(restored, route)

    def test_deserialize_invalid_payload_returns_none(self):
        self.assertIsNone(deserialize_route(""))
        self.assertIsNone(deserialize_route("{not-json"))

    def test_tracks_breadcrumbs(self):
        crumbs = route_breadcrumbs(tracks_artist((42,), label="Radiohead"))
        self.assertEqual(crumbs, [("Tracks", tracks_all()), ("Radiohead", tracks_artist((42,), label="Radiohead"))])

    def test_albums_artist_album_breadcrumbs(self):
        route = artists_album((7,), (9,), artist_label="Artist", album_label="Album")
        crumbs = route_breadcrumbs(route)
        self.assertEqual(
            crumbs,
            [
                ("Artists", artists_all()),
                ("Artist", artists_detail((7,), label="Artist")),
                ("Album", route),
            ],
        )

    def test_albums_routes_build_expected_payloads(self):
        self.assertEqual(albums_all(), LibraryRoute(tab="albums", mode="root"))
        self.assertEqual(albums_artist((1, 2), label="A"), LibraryRoute(tab="albums", mode="artist", artist_ids=(1, 2), artist_label="A"))
        self.assertEqual(albums_detail((3,), label="B"), LibraryRoute(tab="albums", mode="album", album_ids=(3,), album_label="B"))

    def test_tracks_album_route(self):
        self.assertEqual(tracks_album((10,), label="Album"), LibraryRoute(tab="tracks", mode="album", album_ids=(10,), album_label="Album"))
