from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from db.database import add_tracks, get_track_by_id, initialize_database
from db.queries import get_config, get_track_ids_for_download_mode
from tests import test_support as _test_support  # noqa: F401
from tests.test_support import make_fs_track, touch_text
from ui.services.lyrics_download_service import download_track_lyrics


def _lyrics(*, plain: str | None = None, synced: str | None = None, instrumental: bool = False):
    return SimpleNamespace(
        plain_lyrics=plain,
        synced_lyrics=synced,
        instrumental=instrumental,
    )


def _prepare_download(tmp_path: Path, *, existing_plain: str | None = None, existing_synced: str | None = None):
    db = initialize_database(str(tmp_path))
    audio = tmp_path / "characterization.mp3"
    touch_text(audio, "fixture")
    add_tracks(db, [make_fs_track(audio, artist="Artist", album="Album", title="Song")])
    track_id = int(db.execute("SELECT id FROM tracks LIMIT 1").fetchone()["id"])
    db.execute(
        "UPDATE tracks SET txt_lyrics = ?, lrc_lyrics = ? WHERE id = ?",
        (existing_plain, existing_synced, track_id),
    )
    db.commit()
    config = replace(get_config(db), save_lyrics_sidecars=False, try_embed_lyrics=False)
    return db, track_id, config


def _run_download(
    tmp_path: Path,
    result,
    *,
    mode: str,
    existing_plain: str | None = None,
    existing_synced: str | None = None,
    get_lyrics_side_effect=None,
):
    db, track_id, config = _prepare_download(
        tmp_path,
        existing_plain=existing_plain,
        existing_synced=existing_synced,
    )
    try:
        api = Mock()
        api.get_lyrics.return_value = result
        api.get_lyrics.side_effect = get_lyrics_side_effect
        api.search_lyrics.return_value = []
        outcome = download_track_lyrics(
            str(tmp_path / "pylrcget.db.sqlite3"),
            track_id,
            "https://lrclib.test/api",
            download_mode=mode,
            db=db,
            config=config,
            api=api,
        )
        return outcome, get_track_by_id(db, track_id), api
    finally:
        db.close()


def test_synced_only_downloads_exact_synced_result(tmp_path: Path):
    outcome, track, api = _run_download(
        tmp_path,
        _lyrics(plain="plain text", synced="[00:01.00]synced text"),
        mode="synced_only",
    )

    assert outcome[0] is True
    assert "Downloaded synced lyrics." in outcome[1]
    assert track.lrc_lyrics == "[00:01.00]synced text"
    assert track.txt_lyrics is None
    api.search_lyrics.assert_not_called()


def test_plain_only_downloads_exact_plain_result(tmp_path: Path):
    outcome, track, api = _run_download(
        tmp_path,
        _lyrics(plain="plain text"),
        mode="plain_only",
    )

    assert outcome[0] is True
    assert "Downloaded plain lyrics." in outcome[1]
    assert track.txt_lyrics == "plain text"
    assert track.lrc_lyrics is None
    api.search_lyrics.assert_not_called()


def test_instrumental_result_is_not_treated_as_lyrics(tmp_path: Path):
    outcome, track, api = _run_download(
        tmp_path,
        _lyrics(instrumental=True),
        mode="prefer_synced",
    )

    assert outcome[0] is False
    assert "No lyrics found on LRCLIB" in outcome[1]
    assert track.txt_lyrics is None
    assert track.lrc_lyrics is None
    assert api.get_lyrics.call_count == 1
    assert api.search_lyrics.call_count == 5


def test_non_retryable_network_error_fails_without_search(tmp_path: Path):
    outcome, track, api = _run_download(
        tmp_path,
        None,
        mode="prefer_synced",
        get_lyrics_side_effect=requests.exceptions.RequestException("network is unavailable"),
    )

    assert outcome[0] is False
    assert "Download failed: network is unavailable" in outcome[1]
    assert track.txt_lyrics is None
    assert track.lrc_lyrics is None
    assert api.get_lyrics.call_count == 1
    api.search_lyrics.assert_not_called()


def test_existing_synced_lyrics_are_excluded_from_prefer_synced_selection(tmp_path: Path):
    db, track_id, _config = _prepare_download(
        tmp_path,
        existing_synced="[00:01.00]already synced",
    )
    try:
        assert get_track_ids_for_download_mode(db, "prefer_synced") == []
        assert get_track_ids_for_download_mode(db, "synced_only") == []
        assert get_track_ids_for_download_mode(db, "plain_only") == [track_id]
    finally:
        db.close()


@pytest.mark.parametrize(
    ("mode", "result", "expected_plain", "expected_synced"),
    [
        ("prefer_synced", _lyrics(plain="plain fallback"), "plain fallback", None),
        ("plain_only", _lyrics(synced="[00:01.00]line one\n[00:02.00]line two"), "line one\nline two", None),
    ],
)
def test_current_download_mode_fallbacks_remain_stable(
    tmp_path: Path,
    mode: str,
    result,
    expected_plain: str,
    expected_synced: str | None,
):
    outcome, track, _api = _run_download(tmp_path, result, mode=mode)

    assert outcome[0] is True
    assert track.txt_lyrics == expected_plain
    assert track.lrc_lyrics == expected_synced
