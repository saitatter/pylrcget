"""Scanner fast paths must return what the slower, probing paths return."""
from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path
from unittest.mock import patch

import pytest
from mutagen.flac import FLAC, Picture

from library.flac_reader import TagOnlyFLAC, open_flac_tags
from library.scan_library import (
    AudioMetadata,
    SidecarLookupCache,
    _sidecar_base_candidates,
    get_sidecar_scan_state,
    iter_audio_paths_with_signatures_and_audio_signatures,
    read_audio_metadata_for_scan,
)
from library.scan_state import TRACK_SCAN_STATE_SIGNATURE_VERSION

METADATA = AudioMetadata(
    title="Song: One",
    album="Album",
    artist="Artist",
    album_artist="Various",
    track_number=3,
    duration=10.0,
)
ARTWORK = b"\x89PNG" + bytes(range(256)) * 256


def _write_flac(path: Path, *, with_picture: bool = True) -> None:
    stream_info = (
        struct.pack(">HH", 4096, 4096)
        + b"\x00" * 6
        # 44.1 kHz, 2 channels, 16 bits per sample, 441000 samples (10 seconds).
        + ((44100 << 44) | (1 << 41) | (15 << 36) | 441000).to_bytes(8, "big")
        + b"\x00" * 16
    )
    path.write_bytes(b"fLaC" + bytes([0x80]) + len(stream_info).to_bytes(3, "big") + stream_info)
    audio = FLAC(path)
    audio["title"] = "Song"
    audio["artist"] = "Artist"
    audio["lyrics"] = "[00:01.00]line"
    if with_picture:
        picture = Picture()
        picture.type = 3
        picture.mime = "image/png"
        picture.desc = "front"
        picture.data = ARTWORK
        audio.add_picture(picture)
    audio.save()


def _legacy_sidecar_signature(audio_path: Path, subdir: str, pattern: str) -> str:
    """The per-candidate probing formula stored by earlier releases."""
    records = []
    seen: set[str] = set()
    for base in _sidecar_base_candidates(str(audio_path), subdir, metadata=METADATA, lyrics_file_pattern=pattern):
        for suffix in (".txt", ".lrc"):
            candidate = base + suffix
            normalized = os.path.normcase(os.path.abspath(candidate))
            if not os.path.isfile(candidate):
                records.append(f"{normalized}|missing")
                continue
            stat = os.stat(candidate)
            if normalized not in seen:
                seen.add(normalized)
                records.append(f"{normalized}|{normalized}|{stat.st_mtime_ns}|{stat.st_size}")
    payload = f"{TRACK_SCAN_STATE_SIGNATURE_VERSION}\n" + "\n".join(sorted(records))
    return hashlib.sha256(payload.encode()).hexdigest()


@pytest.fixture
def library(tmp_path: Path) -> Path:
    album = tmp_path / "Artist" / "Album"
    (album / "lyrics").mkdir(parents=True)
    (album / "03 Song.flac").write_bytes(b"audio")
    (album / "04 Other.flac").write_bytes(b"audio")
    (album / "03 Song.lrc").write_text("[00:01.00]synced", encoding="utf-8")
    (album / "lyrics" / "Artist - Song_ One.txt").write_text("plain", encoding="utf-8")
    (album / "Song_ One.lrc").mkdir()
    return tmp_path


def test_cached_sidecar_state_matches_probing_state_and_legacy_signature(library: Path):
    audio = library / "Artist" / "Album" / "03 Song.flac"
    kwargs = {"metadata": METADATA, "lyrics_file_pattern": "{artist} - {title}"}

    probed = get_sidecar_scan_state(str(audio), "lyrics", **kwargs)
    cached = get_sidecar_scan_state(str(audio), "lyrics", sidecar_lookup_cache=SidecarLookupCache(), **kwargs)

    assert cached == probed
    assert cached.signature == _legacy_sidecar_signature(audio, "lyrics", "{artist} - {title}")
    assert cached.lrc_path == str(audio.with_suffix(".lrc"))
    assert cached.txt_path == str(audio.parent / "lyrics" / "Artist - Song_ One.txt")


def test_discovery_primes_sidecar_cache_so_scans_do_not_probe_again(library: Path):
    cache = SidecarLookupCache()
    paths, signatures, _ns = iter_audio_paths_with_signatures_and_audio_signatures(
        [str(library)], sidecar_lookup_cache=cache
    )
    unprimed = [
        get_sidecar_scan_state(path, "lyrics", metadata=METADATA, sidecar_lookup_cache=SidecarLookupCache())
        for path in paths
    ]

    with (
        patch("library.scan_library.os.scandir", side_effect=AssertionError("directory listed twice")),
        patch("library.scan_library.os.path.isfile", side_effect=AssertionError("candidate probed")),
        patch("library.scan_library.os.stat", side_effect=AssertionError("candidate stat")),
    ):
        primed = [
            get_sidecar_scan_state(
                path,
                "lyrics",
                metadata=METADATA,
                sidecar_lookup_cache=cache,
                audio_signature=signatures[path],
            )
            for path in paths
        ]

    assert len(paths) == 2
    assert [state.signature for state in primed] == [state.signature for state in unprimed]
    assert [state.lrc_present for state in primed] == [True, False]


def test_reserved_device_names_keep_the_absolute_path_signature(tmp_path: Path):
    audio = tmp_path / "NUL.flac"
    audio.write_bytes(b"audio")
    metadata = AudioMetadata(title="aux", album="", artist="", album_artist="", track_number=None, duration=1.0)

    state = get_sidecar_scan_state(str(audio), metadata=metadata, sidecar_lookup_cache=SidecarLookupCache())

    records = sorted(
        f"{os.path.normcase(os.path.abspath(str(tmp_path / (name + suffix))))}|missing"
        for name in ("NUL", "aux")
        for suffix in (".txt", ".lrc")
    )
    payload = f"{TRACK_SCAN_STATE_SIGNATURE_VERSION}\n" + "\n".join(records)
    assert state.signature == hashlib.sha256(payload.encode()).hexdigest()


def test_tag_only_flac_matches_mutagen_without_reading_artwork(tmp_path: Path):
    path = tmp_path / "song.flac"
    _write_flac(path)
    full = FLAC(path)

    fast = open_flac_tags(str(path))

    assert isinstance(fast, TagOnlyFLAC)
    assert dict(fast.tags) == dict(full.tags)
    assert fast.info.length == full.info.length == 10.0
    assert fast.info.bitrate == full.info.bitrate
    assert [(p.mime, p.desc, p.type) for p in fast.pictures] == [("image/png", "front", 3)]
    assert fast.pictures[0].data == b""
    assert full.pictures[0].data == ARTWORK
    with pytest.raises(RuntimeError):
        fast.save()
    assert FLAC(path).pictures[0].data == ARTWORK


def test_scan_metadata_uses_tag_only_flac_and_falls_back_for_other_content(tmp_path: Path):
    flac = tmp_path / "song.flac"
    _write_flac(flac, with_picture=False)
    mislabeled = tmp_path / "mislabeled.flac"
    mislabeled.write_bytes(b"not flac")

    audio, metadata = read_audio_metadata_for_scan(str(flac))
    assert isinstance(audio, TagOnlyFLAC)
    assert (metadata.title, metadata.artist, metadata.duration) == ("Song", "Artist", 10.0)

    sentinel = object()
    with (
        patch("library.scan_library.MutagenFile", return_value=sentinel) as generic,
        patch("library.scan_library.read_audio_metadata_from_audio", return_value=metadata),
    ):
        assert read_audio_metadata_for_scan(str(mislabeled)) == (sentinel, metadata)
    generic.assert_called_once_with(str(mislabeled), easy=False)
