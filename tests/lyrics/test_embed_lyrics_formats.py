from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mutagen.apev2 import APETextValue

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
from library.scan_library import read_embedded_lyrics_from_audio
from tests import test_support as _test_support  # noqa: F401


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

    def getall(self, key):
        return [frame for frame in self.frames if getattr(frame, "FrameID", "") == key]

    def setall(self, key, frames):
        self.frames = [frame for frame in self.frames if getattr(frame, "FrameID", "") != key]
        self.frames.extend(list(frames))

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


class _FakeFrame(SimpleNamespace):
    pass


class _FakeAudioWithTags:
    def __init__(self, tags):
        self.tags = tags


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

        self.assertEqual([], fake_tags.deleted)
        self.assertTrue(any(frame.FrameID == "USLT" and frame.text == "Plain lyrics" for frame in fake_tags.frames))
        self.assertTrue(
            any(frame.FrameID == "TXXX" and frame.desc == ID3_PLAIN_DESC and frame.text == ["Plain lyrics"] for frame in fake_tags.frames)
        )
        self.assertTrue(
            any(frame.FrameID == "TXXX" and frame.desc == ID3_SYNCED_DESC and frame.text == ["[00:01.00]Synced lyrics"] for frame in fake_tags.frames)
        )
        self.assertEqual(fake_tags.saved_path, "song.mp3")

    def test_wav_writes_id3_lyrics_tags(self):
        fake_tags = _FakeID3()
        fake_audio = _FakeMusepackAudio(tags=fake_tags)

        with patch("core.embed_lyrics.WAVE", return_value=fake_audio):
            embed_lyrics_in_file("song.wav", "Plain lyrics", "[00:01.00]Synced lyrics")

        self.assertTrue(any(frame.FrameID == "USLT" and frame.text == "Plain lyrics" for frame in fake_tags.frames))
        self.assertTrue(
            any(
                frame.FrameID == "TXXX"
                and frame.desc == ID3_SYNCED_DESC
                and frame.text == ["[00:01.00]Synced lyrics"]
                for frame in fake_tags.frames
            )
        )
        self.assertTrue(fake_audio.saved)

    def test_mp3_preserves_foreign_uslt_frames_while_replacing_managed_ones(self):
        foreign_frame = _FakeFrame(FrameID="USLT", lang="eng", desc="translation", text="Foreign lyrics")
        managed_frame = _FakeFrame(FrameID="USLT", lang="und", desc="", text="Old managed lyrics")
        fake_tags = _FakeID3()
        fake_tags.frames = [foreign_frame, managed_frame]

        with patch("core.embed_lyrics.ID3", return_value=fake_tags):
            embed_lyrics_in_file("song.mp3", "Plain lyrics", "[00:01.00]Synced lyrics")

        self.assertTrue(any(frame is foreign_frame for frame in fake_tags.frames))
        self.assertFalse(
            any(
                frame is managed_frame
                for frame in fake_tags.frames
            )
        )
        self.assertTrue(
            any(frame.FrameID == "USLT" and frame.lang == "und" and frame.desc == "" and frame.text == "Plain lyrics" for frame in fake_tags.frames)
        )

    def test_mp3_read_prefers_managed_uslt_frame(self):
        foreign_frame = _FakeFrame(FrameID="USLT", lang="eng", desc="translation", text="Foreign lyrics")
        managed_frame = _FakeFrame(FrameID="USLT", lang="und", desc="", text="Plain lyrics")
        fake_tags = _FakeID3()
        fake_tags.frames = [foreign_frame, managed_frame]
        fake_audio = _FakeAudioWithTags(fake_tags)

        plain, synced = read_embedded_lyrics_from_audio(fake_audio, "song.mp3")

        self.assertEqual(plain, "Plain lyrics")
        self.assertIsNone(synced)

    def test_mp3_read_falls_back_to_standard_sylt_frame(self):
        plain_frame = _FakeFrame(FrameID="USLT", lang="und", desc="", text="Plain lyrics")
        synced_frame = _FakeFrame(
            FrameID="SYLT",
            format=2,
            text=[("First line", 1250), ("Second line", 3675)],
        )
        fake_tags = _FakeID3()
        fake_tags.frames = [plain_frame, synced_frame]
        fake_audio = _FakeAudioWithTags(fake_tags)

        plain, synced = read_embedded_lyrics_from_audio(fake_audio, "song.mp3")

        self.assertEqual(plain, "Plain lyrics")
        self.assertEqual(
            synced,
            "[00:01.25] First line\n[00:03.68] Second line",
        )

    def test_wav_read_prefers_managed_id3_lyrics_frames(self):
        plain_frame = _FakeFrame(FrameID="USLT", lang="und", desc="", text="Plain lyrics")
        synced_frame = _FakeFrame(
            FrameID="TXXX",
            desc=ID3_SYNCED_DESC,
            text=["[00:01.00]Synced lyrics"],
        )
        fake_tags = _FakeID3()
        fake_tags.frames = [plain_frame, synced_frame]
        fake_audio = _FakeAudioWithTags(fake_tags)

        plain, synced = read_embedded_lyrics_from_audio(fake_audio, "song.wav")

        self.assertEqual(plain, "Plain lyrics")
        self.assertEqual(synced, "[00:01.00]Synced lyrics")

    def test_mp3_read_falls_back_when_easy_tags_do_not_expose_getall(self):
        managed_frame = _FakeFrame(FrameID="USLT", lang="und", desc="", text="Plain lyrics")
        fake_tags = _FakeID3()
        fake_tags.frames = [managed_frame]
        fake_audio = _FakeAudioWithTags(SimpleNamespace(get=lambda *_args, **_kwargs: None))

        with patch("library.scan_library.ID3", return_value=fake_tags):
            plain, synced = read_embedded_lyrics_from_audio(fake_audio, "song.mp3")

        self.assertEqual(plain, "Plain lyrics")
        self.assertIsNone(synced)

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
