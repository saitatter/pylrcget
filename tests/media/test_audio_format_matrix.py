from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from mutagen._vorbis import VCommentDict
from mutagen.apev2 import APETextValue, APEv2
from mutagen.asf import ASFTags, ASFUnicodeAttribute
from mutagen.id3 import ID3, TALB, TIT2, TPE1, TPE2, TRCK, TXXX, USLT
from mutagen.mp4 import MP4Tags

from core.embed_lyrics import (
    ASF_PLAIN_KEY,
    ASF_SYNCED_KEY,
    ID3_SYNCED_DESC,
    MP4_PLAIN_KEY,
    MP4_SYNCED_KEY,
    VORBIS_PLAIN_KEY,
    VORBIS_SYNCED_KEY,
    embed_lyrics_in_file,
)
from library.scan_library import (
    AudioMetadata,
    read_audio_metadata_from_audio,
    read_embedded_lyrics,
    read_embedded_lyrics_from_audio,
)

PLAIN_LYRICS = "First line\nSecond line"
SYNCED_LYRICS = "[00:01.00] First line\n[00:02.00] Second line"
EXPECTED_METADATA = {
    "title": "Matrix Song",
    "album": "Matrix Album",
    "artist": "Matrix Artist",
    "album_artist": "Matrix Album Artist",
    "track_number": 3,
    "duration": 12.5,
}


class _TagAudio:
    def __init__(self, tags) -> None:
        self.tags = tags
        self.info = SimpleNamespace(length=EXPECTED_METADATA["duration"])

    def get(self, key, default=None):
        return self.tags.get(key, default)


def _id3_tags() -> ID3:
    tags = ID3()
    tags.add(TIT2(encoding=3, text=EXPECTED_METADATA["title"]))
    tags.add(TALB(encoding=3, text=EXPECTED_METADATA["album"]))
    tags.add(TPE1(encoding=3, text=EXPECTED_METADATA["artist"]))
    tags.add(TPE2(encoding=3, text=EXPECTED_METADATA["album_artist"]))
    tags.add(TRCK(encoding=3, text="3/10"))
    tags.add(USLT(encoding=3, lang="und", desc="", text=PLAIN_LYRICS))
    tags.add(TXXX(encoding=3, desc=ID3_SYNCED_DESC, text=SYNCED_LYRICS))
    return tags


def _vorbis_tags() -> VCommentDict:
    tags = VCommentDict()
    tags["title"] = [EXPECTED_METADATA["title"]]
    tags["album"] = [EXPECTED_METADATA["album"]]
    tags["artist"] = [EXPECTED_METADATA["artist"]]
    tags["albumartist"] = [EXPECTED_METADATA["album_artist"]]
    tags["tracknumber"] = ["3/10"]
    tags[VORBIS_PLAIN_KEY] = [PLAIN_LYRICS]
    tags[VORBIS_SYNCED_KEY] = [SYNCED_LYRICS]
    return tags


def _mp4_tags() -> MP4Tags:
    tags = MP4Tags()
    tags["\xa9nam"] = [EXPECTED_METADATA["title"]]
    tags["\xa9alb"] = [EXPECTED_METADATA["album"]]
    tags["\xa9ART"] = [EXPECTED_METADATA["artist"]]
    tags["aART"] = [EXPECTED_METADATA["album_artist"]]
    tags["trkn"] = [(3, 10)]
    tags[MP4_PLAIN_KEY] = [PLAIN_LYRICS]
    tags[MP4_SYNCED_KEY] = [SYNCED_LYRICS.encode()]
    return tags


def _asf_tags() -> ASFTags:
    tags = ASFTags()
    tags["Title"] = [ASFUnicodeAttribute(EXPECTED_METADATA["title"])]
    tags["WM/AlbumTitle"] = [ASFUnicodeAttribute(EXPECTED_METADATA["album"])]
    tags["Author"] = [ASFUnicodeAttribute(EXPECTED_METADATA["artist"])]
    tags["WM/AlbumArtist"] = [ASFUnicodeAttribute(EXPECTED_METADATA["album_artist"])]
    tags["WM/TrackNumber"] = [ASFUnicodeAttribute("3")]
    tags[ASF_PLAIN_KEY] = [ASFUnicodeAttribute(PLAIN_LYRICS)]
    tags[ASF_SYNCED_KEY] = [ASFUnicodeAttribute(SYNCED_LYRICS)]
    return tags


def _ape_tags() -> APEv2:
    tags = APEv2()
    tags["title"] = APETextValue(EXPECTED_METADATA["title"])
    tags["album"] = APETextValue(EXPECTED_METADATA["album"])
    tags["artist"] = APETextValue(EXPECTED_METADATA["artist"])
    tags["albumartist"] = APETextValue(EXPECTED_METADATA["album_artist"])
    tags["tracknumber"] = APETextValue("3/10")
    tags["UNSYNCEDLYRICS"] = APETextValue(PLAIN_LYRICS)
    tags["LYRICS"] = APETextValue(SYNCED_LYRICS)
    return tags


@pytest.mark.parametrize(
    ("extension", "tag_factory"),
    [
        (".mp3", _id3_tags),
        (".wav", _id3_tags),
        (".flac", _vorbis_tags),
        (".ogg", _vorbis_tags),
        (".oga", _vorbis_tags),
        (".opus", _vorbis_tags),
        (".m4a", _mp4_tags),
        (".mp4", _mp4_tags),
        (".wma", _asf_tags),
        (".asf", _asf_tags),
        (".dsf", _id3_tags),
        (".dff", _id3_tags),
        (".mpc", _ape_tags),
    ],
)
def test_supported_formats_normalize_real_mutagen_tags(extension, tag_factory) -> None:
    audio = _TagAudio(tag_factory())

    metadata = read_audio_metadata_from_audio(audio, f"matrix{extension}")
    assert metadata == AudioMetadata(**EXPECTED_METADATA)

    plain, synced = read_embedded_lyrics_from_audio(audio, f"matrix{extension}")
    assert (plain, synced) == (PLAIN_LYRICS, SYNCED_LYRICS)


def test_wav_lyrics_round_trip_uses_real_mutagen_file(tmp_path: Path) -> None:
    path = tmp_path / "matrix.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(b"\0\0" * 16)

    embed_lyrics_in_file(str(path), PLAIN_LYRICS, SYNCED_LYRICS)

    assert read_embedded_lyrics(str(path)) == (PLAIN_LYRICS, SYNCED_LYRICS)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("extension", "codec"),
    [
        (".mp3", "libmp3lame"),
        (".flac", "flac"),
        (".ogg", "libvorbis"),
        (".oga", "libvorbis"),
        (".opus", "libopus"),
        (".m4a", "aac"),
        (".mp4", "aac"),
        (".wma", "wmav2"),
        (".asf", "wmav2"),
    ],
)
def test_ffmpeg_generated_formats_round_trip_when_encoder_is_available(
    tmp_path: Path,
    extension: str,
    codec: str,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is not installed; Mutagen tag matrix remains available")

    path = tmp_path / f"matrix{extension}"
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=8000:cl=mono",
            "-t",
            "0.2",
            "-c:a",
            codec,
            "-y",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"ffmpeg encoder {codec!r} is unavailable: {result.stderr.strip()}")

    embed_lyrics_in_file(str(path), PLAIN_LYRICS, SYNCED_LYRICS)

    assert read_embedded_lyrics(str(path)) == (PLAIN_LYRICS, SYNCED_LYRICS)
