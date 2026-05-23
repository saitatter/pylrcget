from __future__ import annotations

import os
import re
import sqlite3

from core.models import FsTrack
from core.utils import prepare_input
from db.models import Track
from db.query_modules.common import escape_like
from db.query_modules.config_queries import get_config
from db.query_modules.entity_queries import add_album, add_artist, find_album, find_artist
from library import scan_library


def get_track_by_id(db: sqlite3.Connection, track_id: int) -> Track:
    row = db.execute(
        """
        SELECT
            tracks.id,
            file_path,
            file_name,
            title,
            artists.name AS artist_name,
            tracks.artist_id,
            albums.name AS album_name,
            albums.album_artist_name,
            album_id,
            duration,
            track_number,
            albums.image_path,
            txt_lyrics,
            lrc_lyrics,
            dirty_txt_lyrics,
            dirty_lrc_lyrics,
            dirty_lyrics_present,
            instrumental
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON tracks.artist_id = artists.id
        WHERE tracks.id = ?
        LIMIT 1
        """,
        (int(track_id),),
    ).fetchone()
    return Track.from_row(row)


def add_track(db: sqlite3.Connection, track: FsTrack, *, commit: bool = True) -> None:
    try:
        artist_id = find_artist(db, track.artist)
    except ValueError:
        artist_id = add_artist(db, track.artist, commit=False)

    try:
        album_id = find_album(db, track.album, track.album_artist)
    except ValueError:
        album_id = add_album(db, track.album, track.album_artist, commit=False)

    is_instrumental = track.instrumental or bool(
        track.lrc_lyrics and re.search(r"\[au:\s*instrumental\]", track.lrc_lyrics)
    )

    db.execute(
        """
        INSERT INTO tracks (
            file_path, file_name, title, title_lower,
            album_id, artist_id, duration, track_number,
            txt_lyrics, lrc_lyrics, instrumental, modified_time, file_size
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            track.file_path,
            track.file_name,
            track.title,
            prepare_input(track.title),
            album_id,
            artist_id,
            track.duration,
            track.track_number,
            track.txt_lyrics,
            track.lrc_lyrics,
            is_instrumental,
            track.modified_time,
            track.file_size,
        ),
    )
    if commit:
        db.commit()


def get_existing_file_paths(db: sqlite3.Connection, paths: list[str]) -> set[str]:
    result: set[str] = set()
    chunk_size = 500
    for i in range(0, len(paths), chunk_size):
        chunk = paths[i : i + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = db.execute(
            f"SELECT file_path FROM tracks WHERE file_path IN ({placeholders})",
            chunk,
        ).fetchall()
        result.update(row["file_path"] for row in rows)
    return result


def add_tracks(db: sqlite3.Connection, tracks: list[FsTrack], *, commit: bool = True) -> None:
    if not tracks:
        return

    def _do_add() -> None:
        artist_cache: dict[str, int] = {
            row[1]: row[0]
            for row in db.execute("SELECT id, name_lower FROM artists").fetchall()
        }
        album_cache: dict[tuple[str, str], int] = {
            (row[1], row[2]): row[0]
            for row in db.execute("SELECT id, name_lower, album_artist_name_lower FROM albums").fetchall()
        }
        for track in tracks:
            artist_key = prepare_input(track.artist)
            artist_id = artist_cache.get(artist_key)
            if artist_id is None:
                artist_id = add_artist(db, track.artist, commit=False)
                artist_cache[artist_key] = artist_id

            album_key = (prepare_input(track.album), prepare_input(track.album_artist))
            album_id = album_cache.get(album_key)
            if album_id is None:
                album_id = add_album(db, track.album, track.album_artist, commit=False)
                album_cache[album_key] = album_id

            is_instrumental = track.instrumental or bool(
                track.lrc_lyrics and re.search(r"\[au:\s*instrumental\]", track.lrc_lyrics)
            )
            db.execute(
                """
                INSERT OR IGNORE INTO tracks (
                    file_path, file_name, title, title_lower,
                    album_id, artist_id, duration, track_number,
                    txt_lyrics, lrc_lyrics, instrumental, modified_time, file_size
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    track.file_path,
                    track.file_name,
                    track.title,
                    prepare_input(track.title),
                    album_id,
                    artist_id,
                    track.duration,
                    track.track_number,
                    track.txt_lyrics,
                    track.lrc_lyrics,
                    is_instrumental,
                    track.modified_time,
                    track.file_size,
                ),
            )

    if commit:
        with db:
            _do_add()
    else:
        _do_add()


def get_tracks(db: sqlite3.Connection) -> list[Track]:
    cursor = db.execute(
        """
        SELECT
            tracks.id, file_path, file_name, title,
            artists.name AS artist_name, tracks.artist_id,
            albums.name AS album_name, albums.album_artist_name,
            album_id, duration, track_number, modified_time, file_size,
            albums.image_path, txt_lyrics, lrc_lyrics, dirty_txt_lyrics, dirty_lrc_lyrics, dirty_lyrics_present, instrumental
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON tracks.artist_id = artists.id
        ORDER BY title_lower ASC
        """
    )
    return [Track.from_row(row) for row in cursor.fetchall()]


def get_track_rows(
    db: sqlite3.Connection,
    search_query: str,
    synced_lyrics_tracks: bool,
    plain_lyrics_tracks: bool,
    instrumental_tracks: bool,
    no_lyrics_tracks: bool,
    unsaved_draft_only: bool = False,
    limit: int | None = None,
    offset: int = 0,
    artist_id: int | None = None,
    album_id: int | None = None,
    artist_ids: list[int] | None = None,
    album_ids: list[int] | None = None,
    sort_column: int = 0,
    sort_order: str = "asc",
) -> list[sqlite3.Row]:
    conditions: list[str] = []
    params: list[object] = []

    q = prepare_input(search_query or "")
    if q:
        conditions.append(
            "(tracks.title_lower LIKE ? ESCAPE '\\' OR artists.name_lower LIKE ? ESCAPE '\\' OR albums.name_lower LIKE ? ESCAPE '\\' OR albums.album_artist_name_lower LIKE ? ESCAPE '\\')"
        )
        like = f"%{escape_like(q)}%"
        params.extend([like, like, like, like])

    if unsaved_draft_only:
        conditions.append("tracks.dirty_lyrics_present = 1")
    else:
        if not synced_lyrics_tracks:
            conditions.append("(tracks.lrc_lyrics IS NULL OR tracks.lrc_lyrics = '[au: instrumental]')")
        if not plain_lyrics_tracks:
            conditions.append("(tracks.txt_lyrics IS NULL OR tracks.lrc_lyrics IS NOT NULL)")
        if not instrumental_tracks:
            conditions.append("tracks.instrumental = 0")
        if not no_lyrics_tracks:
            conditions.append("(tracks.txt_lyrics IS NOT NULL OR tracks.lrc_lyrics IS NOT NULL OR tracks.instrumental = 1)")

    if artist_ids:
        placeholders = ", ".join("?" for _ in artist_ids)
        conditions.append(f"tracks.artist_id IN ({placeholders})")
        params.extend(int(v) for v in artist_ids)
    elif artist_id is not None:
        conditions.append("tracks.artist_id = ?")
        params.append(int(artist_id))

    if album_ids:
        placeholders = ", ".join("?" for _ in album_ids)
        conditions.append(f"tracks.album_id IN ({placeholders})")
        params.extend(int(v) for v in album_ids)
    elif album_id is not None:
        conditions.append("tracks.album_id = ?")
        params.append(int(album_id))

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order = "DESC" if str(sort_order).lower() == "desc" else "ASC"
    order_map = {
        0: (
            f"tracks.track_number IS NULL ASC, tracks.track_number {order}, "
            f"tracks.title_lower {order}, tracks.id {order}"
        ),
        1: f"artists.name_lower {order}, tracks.title_lower {order}, tracks.id {order}",
        2: f"tracks.duration IS NULL ASC, tracks.duration {order}, tracks.id {order}",
        3: (
            "CASE "
            "WHEN tracks.lrc_lyrics IS NOT NULL AND tracks.lrc_lyrics != '[au: instrumental]' THEN 0 "
            "WHEN tracks.txt_lyrics IS NOT NULL THEN 1 "
            "WHEN tracks.instrumental = 1 THEN 2 "
            "ELSE 3 END "
            f"{order}, tracks.title_lower {order}, tracks.id {order}"
        ),
        4: f"tracks.title_lower {order}, tracks.id {order}",
    }
    col = int(sort_column) if int(sort_column) in order_map else 0
    order_clause = order_map[col]
    limit_clause = f"LIMIT {int(limit)} OFFSET {max(0, int(offset))}" if limit else ""

    query = f"""
        SELECT
            tracks.id,
            tracks.title,
            tracks.artist_id,
            tracks.album_id,
            artists.name AS artist_name,
            albums.name AS album_name,
            tracks.track_number,
            tracks.duration,
            tracks.txt_lyrics,
            tracks.lrc_lyrics,
            tracks.dirty_txt_lyrics,
            tracks.dirty_lrc_lyrics,
            tracks.dirty_lyrics_present,
            tracks.instrumental
        FROM tracks
        JOIN artists ON tracks.artist_id = artists.id
        JOIN albums ON tracks.album_id = albums.id
        {where_clause}
        ORDER BY {order_clause}
        {limit_clause}
    """
    return db.execute(query, params).fetchall()


def update_track_synced_lyrics(db: sqlite3.Connection, track_id: int, synced_lyrics: str, plain_lyrics: str) -> None:
    synced_lyrics = (synced_lyrics or "").strip() or None
    plain_lyrics = (plain_lyrics or "").strip() or None

    db.execute(
        """
        UPDATE tracks
        SET lrc_lyrics = ?, txt_lyrics = ?, dirty_lrc_lyrics = NULL, dirty_txt_lyrics = NULL, dirty_lyrics_present = 0, instrumental = 0
        WHERE id = ?
        """,
        (synced_lyrics, plain_lyrics, int(track_id)),
    )
    db.commit()


def update_track_plain_lyrics(db: sqlite3.Connection, track_id: int, plain_lyrics: str) -> None:
    plain_lyrics = (plain_lyrics or "").strip() or None
    db.execute(
        """
        UPDATE tracks
        SET txt_lyrics = ?, lrc_lyrics = NULL, dirty_lrc_lyrics = NULL, dirty_txt_lyrics = NULL, dirty_lyrics_present = 0, instrumental = 0
        WHERE id = ?
        """,
        (plain_lyrics, int(track_id)),
    )
    db.commit()


def update_track_null_lyrics(db: sqlite3.Connection, track_id: int) -> None:
    db.execute(
        """
        UPDATE tracks
        SET txt_lyrics = NULL, lrc_lyrics = NULL, dirty_lrc_lyrics = NULL, dirty_txt_lyrics = NULL, dirty_lyrics_present = 0, instrumental = 0
        WHERE id = ?
        """,
        (int(track_id),),
    )
    db.commit()


def update_track_dirty_lyrics(db: sqlite3.Connection, track_id: int, synced_lyrics: str, plain_lyrics: str) -> None:
    synced_lyrics = (synced_lyrics or "").strip() or None
    plain_lyrics = (plain_lyrics or "").strip() or None
    db.execute(
        """
        UPDATE tracks
        SET dirty_lrc_lyrics = ?,
            dirty_txt_lyrics = ?,
            dirty_lyrics_present = 1
        WHERE id = ?
        """,
        (synced_lyrics, plain_lyrics, int(track_id)),
    )
    db.commit()


def clear_track_dirty_lyrics(db: sqlite3.Connection, track_id: int) -> None:
    db.execute(
        """
        UPDATE tracks
        SET dirty_lrc_lyrics = NULL,
            dirty_txt_lyrics = NULL,
            dirty_lyrics_present = 0
        WHERE id = ?
        """,
        (int(track_id),),
    )
    db.commit()


def update_track_instrumental(db: sqlite3.Connection, track_id: int) -> None:
    db.execute(
        """
        UPDATE tracks
        SET txt_lyrics = NULL, lrc_lyrics = '[au: instrumental]', dirty_lrc_lyrics = NULL, dirty_txt_lyrics = NULL, dirty_lyrics_present = 0, instrumental = 1
        WHERE id = ?
        """,
        (int(track_id),),
    )
    db.commit()


def refresh_track_from_file(db: sqlite3.Connection, track_id: int) -> Track | None:
    row = db.execute(
        """
        SELECT id, file_path, file_name
        FROM tracks
        WHERE id = ?
        LIMIT 1
        """,
        (int(track_id),),
    ).fetchone()
    if row is None:
        raise KeyError(f"Track not found: {track_id}")

    stored_path = str(row["file_path"] or "").strip()
    file_name = str(row["file_name"] or "").strip()
    source_path = os.path.join(stored_path, file_name) if stored_path and os.path.isdir(stored_path) else stored_path
    source_path = os.path.abspath(source_path) if source_path else ""

    if not source_path or not os.path.isfile(source_path):
        db.execute("DELETE FROM tracks WHERE id = ?", (int(track_id),))
        prune_library(db)
        db.commit()
        return None

    config = get_config(db)
    refreshed = scan_library.new_fs_track_from_path(
        source_path,
        lyrics_lookup_subdir=config.lyrics_lookup_subdir,
        lyrics_file_pattern=config.lyrics_file_pattern,
    )
    if refreshed is None:
        raise ValueError(f"Could not refresh track from file: {source_path}")

    try:
        artist_id = find_artist(db, refreshed.artist)
    except ValueError:
        artist_id = add_artist(db, refreshed.artist, commit=False)

    try:
        album_id = find_album(db, refreshed.album, refreshed.album_artist)
    except ValueError:
        album_id = add_album(db, refreshed.album, refreshed.album_artist, commit=False)

    is_instrumental = bool(refreshed.lrc_lyrics and re.search(r"\[au:\s*instrumental\]", refreshed.lrc_lyrics))

    db.execute(
        """
        UPDATE tracks
        SET file_path = ?,
            file_name = ?,
            title = ?,
            title_lower = ?,
            album_id = ?,
            artist_id = ?,
            duration = ?,
            track_number = ?,
            txt_lyrics = ?,
            lrc_lyrics = ?,
            dirty_txt_lyrics = NULL,
            dirty_lrc_lyrics = NULL,
            dirty_lyrics_present = 0,
            instrumental = ?,
            modified_time = ?,
            file_size = ?
        WHERE id = ?
        """,
        (
            refreshed.file_path,
            refreshed.file_name,
            refreshed.title,
            prepare_input(refreshed.title),
            album_id,
            artist_id,
            refreshed.duration,
            refreshed.track_number,
            refreshed.txt_lyrics,
            refreshed.lrc_lyrics,
            is_instrumental,
            refreshed.modified_time,
            refreshed.file_size,
            int(track_id),
        ),
    )
    prune_library(db)
    db.commit()
    return get_track_by_id(db, int(track_id))


def mark_tracks_instrumental(db: sqlite3.Connection, track_ids: list[int]) -> None:
    ids = [int(x) for x in track_ids if x is not None]
    if not ids:
        return

    db.execute("BEGIN")
    try:
        db.executemany(
            """
            UPDATE tracks
            SET txt_lyrics = NULL,
                lrc_lyrics = '[au: instrumental]',
                dirty_txt_lyrics = NULL,
                dirty_lrc_lyrics = NULL,
                dirty_lyrics_present = 0,
                instrumental = 1
            WHERE id = ?
            """,
            [(track_id,) for track_id in ids],
        )
        db.commit()
    except sqlite3.Error:
        db.rollback()
        raise


def unmark_tracks_instrumental(db: sqlite3.Connection, track_ids: list[int]) -> None:
    ids = [int(x) for x in track_ids if x is not None]
    if not ids:
        return

    db.execute("BEGIN")
    try:
        db.executemany(
            """
            UPDATE tracks
            SET instrumental = 0,
                lrc_lyrics = CASE
                    WHEN lrc_lyrics = '[au: instrumental]' THEN NULL
                    ELSE lrc_lyrics
                END,
                dirty_txt_lyrics = NULL,
                dirty_lrc_lyrics = NULL,
                dirty_lyrics_present = 0
            WHERE id = ?
            """,
            [(track_id,) for track_id in ids],
        )
        db.commit()
    except sqlite3.Error:
        db.rollback()
        raise


def prune_library(db: sqlite3.Connection) -> None:
    db.execute("DELETE FROM albums WHERE NOT EXISTS (SELECT 1 FROM tracks WHERE tracks.album_id = albums.id)")
    db.execute("DELETE FROM artists WHERE NOT EXISTS (SELECT 1 FROM tracks WHERE tracks.artist_id = artists.id)")
    db.commit()