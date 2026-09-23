from __future__ import annotations

import sqlite3

from db.queries import get_album_lyrics_samples


def test_album_lyrics_samples_are_bounded_and_skip_instrumentals():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE tracks (
            id INTEGER PRIMARY KEY,
            album_id INTEGER,
            txt_lyrics TEXT,
            lrc_lyrics TEXT,
            txt_lyrics_source TEXT,
            lrc_lyrics_source TEXT,
            instrumental INTEGER DEFAULT 0
        );
        INSERT INTO tracks VALUES (1, 10, 'plain one', NULL, NULL, NULL, 0);
        INSERT INTO tracks VALUES (2, 10, NULL, '[00:01.00]synced two', NULL, NULL, 0);
        INSERT INTO tracks VALUES (3, 10, 'plain three', NULL, NULL, NULL, 0);
        INSERT INTO tracks VALUES (4, 10, 'instrumental marker', NULL, NULL, NULL, 1);
        INSERT INTO tracks VALUES (5, 20, 'another album', NULL, NULL, NULL, 0);
        INSERT INTO tracks VALUES (6, 30, 'provider lyrics', NULL, 'musixmatch', NULL, 0);
        INSERT INTO tracks VALUES (7, 30, 'provider lyrics', '[00:01.00]local lyrics', 'musixmatch', 'embedded', 0);
        INSERT INTO tracks VALUES (8, 40, 'local short', '[00:01.00]provider lyrics that are longer', 'embedded', 'musixmatch', 0);
        """
    )
    try:
        samples = get_album_lyrics_samples(db, [10, 20, 30, 40], per_album_limit=2, chunk_size=1)
    finally:
        db.close()

    assert [track_id for track_id, _lyrics in samples[10]] == [1, 2]
    assert samples[10][0][1] == "plain one"
    assert samples[10][1][1] == "[00:01.00]synced two"
    assert [track_id for track_id, _lyrics in samples[20]] == [5]
    assert samples[30] == [(7, "[00:01.00]local lyrics")]
    assert samples[40] == [(8, "local short")]
