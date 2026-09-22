from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from db.database import add_tracks, get_config, get_track_by_id, initialize_database
from lyrics.providers.contracts import LyricsProviderCapabilities, LyricsProviderResult
from tests import test_support as _test_support  # noqa: F401
from tests.test_support import make_fs_track, touch_text
from ui.services.lyrics_download_service import download_track_lyrics

ENGLISH = (
    "My heart keeps searching through the night, my footsteps fade but the light "
    "stays close and calls me home again. I run through rain and try to find the "
    "answer, while the world keeps changing every day."
)
FRENCH = (
    "Mon cœur cherche encore dans la nuit, mes pas disparaissent mais la lumière "
    "reste proche et me ramène chez moi. Je cours sous la pluie pour trouver des "
    "réponses tandis que le monde change chaque jour."
)


class _WrongLanguageProvider:
    provider_id = "musixmatch"
    display_name = "Musixmatch"

    def __init__(self) -> None:
        self.expected_languages: list[str | None] = []

    def capabilities(self):
        return LyricsProviderCapabilities(True, True, True, False, False)

    def lookup(self, track, *, requested_mode, cancel_event=None):
        self.expected_languages.append(track.expected_language)
        return LyricsProviderResult(
            provider="musixmatch",
            provider_track_id="wrong-language-track",
            plain_lyrics=FRENCH,
            synced_lyrics=None,
            instrumental=False,
            match_score=100.0,
            match_method="metadata",
            remote_title=track.title,
            remote_artist=track.artists[0],
            remote_album=track.album,
            remote_duration_seconds=track.duration_seconds,
            remote_isrc=None,
        )

    def search(self, context, *, cancel_event=None):
        return []


def test_single_track_download_rejects_language_against_album_lyrics(tmp_path: Path, monkeypatch):
    db = initialize_database(str(tmp_path))
    audio_paths = [tmp_path / f"track_{index}.mp3" for index in range(3)]
    for index, path in enumerate(audio_paths):
        touch_text(path, f"fixture {index}")
    add_tracks(
        db,
        [
            make_fs_track(path, artist="Artist", album="Album", title=f"Song {index}")
            for index, path in enumerate(audio_paths)
        ],
    )
    track_rows = db.execute("SELECT id FROM tracks ORDER BY id").fetchall()
    target_id = int(track_rows[0]["id"])
    db.executemany(
        "UPDATE tracks SET txt_lyrics = ? WHERE id = ?",
        [(ENGLISH, int(row["id"])) for row in track_rows[1:]],
    )
    db.commit()
    provider = _WrongLanguageProvider()
    monkeypatch.setattr(
        "ui.services.lyrics_download_service._build_single_track_providers",
        lambda *_args, **_kwargs: [provider],
    )
    config = replace(get_config(db), save_lyrics_sidecars=False, try_embed_lyrics=False)

    try:
        outcome = download_track_lyrics(
            str(tmp_path / "pylrcget.db.sqlite3"),
            target_id,
            "https://lrclib.test/api",
            db=db,
            config=config,
            api=Mock(),
        )

        assert outcome[0] is False
        assert "detected language fr, expected en" in outcome[1]
        assert provider.expected_languages == ["en"]
        assert get_track_by_id(db, target_id).txt_lyrics is None
    finally:
        db.close()
