from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mutagen.apev2 import APEBinaryValue

from tests.test_support import touch_text
from core.artwork import extract_embedded_cover_bytes
from core.embed_lyrics import embed_lyrics_in_file
from library.scan_library import new_fs_track_from_path, read_embedded_lyrics


class _FakeEasyAudio(dict):
    def __init__(self, **values):
        super().__init__(values)
        self.info = SimpleNamespace(length=213.5)


class _FakeMusepackAudio:
    def __init__(self, tags=None):
        self.tags = tags
        self.saved = False
        self.add_tags_called = False

    def add_tags(self):
        self.tags = {}
        self.add_tags_called = True

    def save(self):
        self.saved = True


class MusepackSupportTests(unittest.TestCase):
    def test_read_embedded_lyrics_reads_musepack_ape_tags(self):
        fake_audio = _FakeMusepackAudio(
            tags={
                "UNSYNCEDLYRICS": ["Plain lyrics"],
                "LYRICS": ["[00:01.00]Synced lyrics"],
            }
        )

        with patch("library.scan_library.Musepack", return_value=fake_audio):
            plain, synced = read_embedded_lyrics("song.mpc")

        self.assertEqual(plain, "Plain lyrics")
        self.assertEqual(synced, "[00:01.00]Synced lyrics")

    def test_new_fs_track_from_path_builds_track_for_musepack_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "track.mpc"
            touch_text(path, "audio")
            fake_audio = _FakeEasyAudio(
                title=["Song Title"],
                album=["Album Name"],
                artist=["Artist Name"],
                albumartist=["Album Artist"],
                tracknumber=["03/10"],
            )

            with patch("library.scan_library.MutagenFile", return_value=fake_audio), patch(
                "library.scan_library.read_embedded_lyrics",
                return_value=("Plain lyrics", "[00:01.00]Synced lyrics"),
            ):
                track = new_fs_track_from_path(str(path))

        self.assertIsNotNone(track)
        assert track is not None
        self.assertEqual(track.title, "Song Title")
        self.assertEqual(track.album, "Album Name")
        self.assertEqual(track.artist, "Artist Name")
        self.assertEqual(track.album_artist, "Album Artist")
        self.assertEqual(track.track_number, 3)
        self.assertEqual(track.txt_lyrics, "Plain lyrics")
        self.assertEqual(track.lrc_lyrics, "[00:01.00]Synced lyrics")

    def test_embed_lyrics_in_file_writes_musepack_tags(self):
        fake_audio = _FakeMusepackAudio(tags=None)

        with patch("core.embed_lyrics.Musepack", return_value=fake_audio):
            embed_lyrics_in_file(
                "song.mpc",
                "Plain lyrics",
                "[00:01.00]Synced lyrics",
            )

        self.assertTrue(fake_audio.add_tags_called)
        self.assertTrue(fake_audio.saved)
        self.assertEqual(str(fake_audio.tags["UNSYNCEDLYRICS"]), "Plain lyrics")
        self.assertEqual(str(fake_audio.tags["LYRICS"]), "[00:01.00]Synced lyrics")

    def test_extract_embedded_cover_bytes_reads_musepack_ape_binary_value(self):
        class FakeMusepackForArtwork:
            def __init__(self, tags):
                self.tags = tags

        fake_audio = FakeMusepackForArtwork(
            tags={
                "Cover Art (Front)": APEBinaryValue(b"cover.jpg\x00PNGDATA"),
            }
        )

        with patch("core.artwork.Musepack", FakeMusepackForArtwork), patch(
            "core.artwork.MutagenFile",
            return_value=fake_audio,
        ):
            cover = extract_embedded_cover_bytes("song.mpc")

        self.assertEqual(cover, b"PNGDATA")


if __name__ == "__main__":
    unittest.main()
