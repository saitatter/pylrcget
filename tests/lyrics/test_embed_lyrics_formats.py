from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mutagen.apev2 import APETextValue

from tests import test_support as _test_support  # noqa: F401
from core.embed_lyrics import (
    ASF_PLAIN_KEY,
    ASF_SYNCED_KEY,
    ID3_PLAIN_DESC,
    ID3_SYNCED_DESC,
    MP4_PLAIN_KEY,
    MP4_SYNCED_KEY,
    VORBIS_PLAIN_KEY,
    VORBIS_SYNCED_KEY,
    embed_lyrics_for_track,
    embed_lyrics_in_file,
)


class _FakeTagAudio(dict):
    def __init__(self, tags=None):
        super().__init__(tags or {})
        self.saved = False

    def save(self, *args, **kwargs):
        self.saved = True


class _FakeID3:
    def __init__(self):
        self.frames = []
        self.deleted = []
        self.saved_path = ""

    def delall(self, key):
        self.deleted.append(key)
        self.frames = [
            frame
            for frame in self.frames
            if getattr(frame, "FrameID", "") != key and f"TXXX:{getattr(frame, 'desc', '')}" != key
        ]

    def add(self, frame):
        self.frames.append(frame)

    def save(self, path):
        self.saved_path = path


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


class EmbedLyricsFormatTests(unittest.TestCase):
    def test_flac_writes_vorbis_plain_and_synced_tags(self):
        fake_audio = _FakeTagAudio()

        with patch("core.embed_lyrics.FLAC", return_value=fake_audio):
            embed_lyrics_in_file("song.flac", "Plain lyrics", "[00:01.00]Synced lyrics")

        self.assertEqual(fake_audio[VORBIS_PLAIN_KEY], ["Plain lyrics"])
        self.assertEqual(fake_audio[VORBIS_SYNCED_KEY], ["[00:01.00]Synced lyrics"])
        self.assertTrue(fake_audio.saved)

    def test_flac_prefer_synced_removes_old_plain_tag(self):
        fake_audio = _FakeTagAudio({VORBIS_PLAIN_KEY: ["Old plain"]})
        track = SimpleNamespace(
            file_path="song.flac",
            txt_lyrics="Plain lyrics",
            lrc_lyrics="[00:01.00]Synced lyrics",
        )

        with patch("core.embed_lyrics.FLAC", return_value=fake_audio):
            embed_lyrics_for_track(track, output_format="prefer_synced")

        self.assertNotIn(VORBIS_PLAIN_KEY, fake_audio)
        self.assertEqual(fake_audio[VORBIS_SYNCED_KEY], ["[00:01.00]Synced lyrics"])

    def test_flac_plain_only_removes_old_synced_tag(self):
        fake_audio = _FakeTagAudio({VORBIS_SYNCED_KEY: ["[00:01.00]Old synced"]})
        track = SimpleNamespace(
            file_path="song.flac",
            txt_lyrics="Plain lyrics",
            lrc_lyrics="[00:01.00]Synced lyrics",
        )

        with patch("core.embed_lyrics.FLAC", return_value=fake_audio):
            embed_lyrics_for_track(track, output_format="plain_only")

        self.assertEqual(fake_audio[VORBIS_PLAIN_KEY], ["Plain lyrics"])
        self.assertNotIn(VORBIS_SYNCED_KEY, fake_audio)

    def test_ogg_and_opus_share_vorbis_tag_behavior(self):
        for filename, patch_target in (
            ("song.ogg", "core.embed_lyrics.OggVorbis"),
            ("song.opus", "core.embed_lyrics.OggOpus"),
        ):
            with self.subTest(filename=filename):
                fake_audio = _FakeTagAudio()
                with patch(patch_target, return_value=fake_audio):
                    embed_lyrics_in_file(filename, "Plain lyrics", "[00:01.00]Synced lyrics")

                self.assertEqual(fake_audio[VORBIS_PLAIN_KEY], ["Plain lyrics"])
                self.assertEqual(fake_audio[VORBIS_SYNCED_KEY], ["[00:01.00]Synced lyrics"])

    def test_mp3_writes_uslt_plain_and_txxx_synced_frames(self):
        fake_tags = _FakeID3()

        with patch("core.embed_lyrics.ID3", return_value=fake_tags):
            embed_lyrics_in_file("song.mp3", "Plain lyrics", "[00:01.00]Synced lyrics")

        self.assertIn("USLT", fake_tags.deleted)
        self.assertIn(f"TXXX:{ID3_PLAIN_DESC}", fake_tags.deleted)
        self.assertIn(f"TXXX:{ID3_SYNCED_DESC}", fake_tags.deleted)
        self.assertTrue(any(frame.FrameID == "USLT" and frame.text == "Plain lyrics" for frame in fake_tags.frames))
        self.assertTrue(
            any(frame.FrameID == "TXXX" and frame.desc == ID3_PLAIN_DESC and frame.text == ["Plain lyrics"] for frame in fake_tags.frames)
        )
        self.assertTrue(
            any(frame.FrameID == "TXXX" and frame.desc == ID3_SYNCED_DESC and frame.text == ["[00:01.00]Synced lyrics"] for frame in fake_tags.frames)
        )
        self.assertEqual(fake_tags.saved_path, "song.mp3")

    def test_mp3_synced_only_does_not_write_plain_frames(self):
        fake_tags = _FakeID3()
        track = SimpleNamespace(
            file_path="song.mp3",
            txt_lyrics="Plain lyrics",
            lrc_lyrics="[00:01.00]Synced lyrics",
        )

        with patch("core.embed_lyrics.ID3", return_value=fake_tags):
            embed_lyrics_for_track(track, output_format="synced_only")

        self.assertFalse(any(frame.FrameID == "USLT" for frame in fake_tags.frames))
        self.assertFalse(any(frame.FrameID == "TXXX" and frame.desc == ID3_PLAIN_DESC for frame in fake_tags.frames))
        self.assertTrue(any(frame.FrameID == "TXXX" and frame.desc == ID3_SYNCED_DESC for frame in fake_tags.frames))

    def test_mp4_writes_plain_and_synced_atoms(self):
        fake_audio = _FakeTagAudio()

        with patch("core.embed_lyrics.MP4", return_value=fake_audio):
            embed_lyrics_in_file("song.m4a", "Plain lyrics", "[00:01.00]Synced lyrics")

        self.assertEqual(fake_audio[MP4_PLAIN_KEY], ["Plain lyrics"])
        self.assertEqual(fake_audio[MP4_SYNCED_KEY], [b"[00:01.00]Synced lyrics"])
        self.assertTrue(fake_audio.saved)

    def test_mp4_prefer_synced_removes_old_plain_atom(self):
        fake_audio = _FakeTagAudio({MP4_PLAIN_KEY: ["Old plain"]})
        track = SimpleNamespace(
            file_path="song.m4a",
            txt_lyrics="Plain lyrics",
            lrc_lyrics="[00:01.00]Synced lyrics",
        )

        with patch("core.embed_lyrics.MP4", return_value=fake_audio):
            embed_lyrics_for_track(track, output_format="prefer_synced")

        self.assertNotIn(MP4_PLAIN_KEY, fake_audio)
        self.assertEqual(fake_audio[MP4_SYNCED_KEY], [b"[00:01.00]Synced lyrics"])

    def test_asf_writes_plain_and_synced_tags(self):
        fake_audio = _FakeTagAudio()

        with patch("core.embed_lyrics.ASF", return_value=fake_audio):
            embed_lyrics_in_file("song.wma", "Plain lyrics", "[00:01.00]Synced lyrics")

        self.assertEqual(str(fake_audio[ASF_PLAIN_KEY][0]), "Plain lyrics")
        self.assertEqual(str(fake_audio[ASF_SYNCED_KEY][0]), "[00:01.00]Synced lyrics")
        self.assertTrue(fake_audio.saved)

    def test_asf_prefer_synced_removes_old_plain_tag(self):
        fake_audio = _FakeTagAudio({ASF_PLAIN_KEY: ["Old plain"]})
        track = SimpleNamespace(
            file_path="song.wma",
            txt_lyrics="Plain lyrics",
            lrc_lyrics="[00:01.00]Synced lyrics",
        )

        with patch("core.embed_lyrics.ASF", return_value=fake_audio):
            embed_lyrics_for_track(track, output_format="prefer_synced")

        self.assertNotIn(ASF_PLAIN_KEY, fake_audio)
        self.assertEqual(str(fake_audio[ASF_SYNCED_KEY][0]), "[00:01.00]Synced lyrics")

    def test_musepack_writes_plain_and_synced_tags(self):
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

    def test_musepack_derives_plain_from_synced_for_both_format(self):
        fake_audio = _FakeMusepackAudio(tags=None)
        track = SimpleNamespace(
            file_path="song.mpc",
            txt_lyrics=None,
            lrc_lyrics="[00:01.00]Synced lyrics",
        )

        with patch("core.embed_lyrics.Musepack", return_value=fake_audio):
            embed_lyrics_for_track(track)

        self.assertEqual(str(fake_audio.tags["UNSYNCEDLYRICS"]), "Synced lyrics")
        self.assertEqual(str(fake_audio.tags["LYRICS"]), "[00:01.00]Synced lyrics")

    def test_musepack_respects_synced_only_format(self):
        fake_audio = _FakeMusepackAudio(tags={"UNSYNCEDLYRICS": APETextValue("Old plain")})
        track = SimpleNamespace(
            file_path="song.mpc",
            txt_lyrics="Plain lyrics",
            lrc_lyrics="[00:01.00]Synced lyrics",
        )

        with patch("core.embed_lyrics.Musepack", return_value=fake_audio):
            embed_lyrics_for_track(track, output_format="synced_only")

        self.assertNotIn("UNSYNCEDLYRICS", fake_audio.tags)
        self.assertEqual(str(fake_audio.tags["LYRICS"]), "[00:01.00]Synced lyrics")

    def test_musepack_prefer_synced_embeds_only_synced_when_available(self):
        fake_audio = _FakeMusepackAudio(tags={"UNSYNCEDLYRICS": APETextValue("Old plain")})
        track = SimpleNamespace(
            file_path="song.mpc",
            txt_lyrics="Plain lyrics",
            lrc_lyrics="[00:01.00]Synced lyrics",
        )

        with patch("core.embed_lyrics.Musepack", return_value=fake_audio):
            embed_lyrics_for_track(track, output_format="prefer_synced")

        self.assertNotIn("UNSYNCEDLYRICS", fake_audio.tags)
        self.assertEqual(str(fake_audio.tags["LYRICS"]), "[00:01.00]Synced lyrics")

    def test_musepack_prefer_synced_falls_back_to_only_plain(self):
        fake_audio = _FakeMusepackAudio(tags={"LYRICS": APETextValue("[00:01.00]Old synced")})
        track = SimpleNamespace(
            file_path="song.mpc",
            txt_lyrics="Plain lyrics",
            lrc_lyrics=None,
        )

        with patch("core.embed_lyrics.Musepack", return_value=fake_audio):
            embed_lyrics_for_track(track, output_format="prefer_synced")

        self.assertNotIn("LYRICS", fake_audio.tags)
        self.assertEqual(str(fake_audio.tags["UNSYNCEDLYRICS"]), "Plain lyrics")


if __name__ == "__main__":
    unittest.main()
