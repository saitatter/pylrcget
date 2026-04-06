from __future__ import annotations

import re
import sqlite3
from typing import List

from core.utils import prepare_input
from db.models import Album, Artist, Config, Track
from library.fs_track import FsTrack

# -------------------------------
# DIRECTORIES
# -------------------------------
def get_directories(db: sqlite3.Connection) -> List[str]:
    cursor = db.execute("SELECT path FROM directories")
    return [row["path"] for row in cursor.fetchall()]


def set_directories(db: sqlite3.Connection, directories: List[str]) -> None:
    db.execute("DELETE FROM directories")
    for path in directories:
        db.execute("INSERT INTO directories (path) VALUES (?)", (path,))
    db.commit()


# -------------------------------
# LIBRARY INIT
# -------------------------------
def get_init(db: sqlite3.Connection) -> bool:
    row = db.execute("SELECT init FROM library_data LIMIT 1").fetchone()
    return bool(row["init"])


def set_init(db: sqlite3.Connection, init: bool) -> None:
    db.execute("UPDATE library_data SET init = ? WHERE 1", (init,))
    db.commit()


# -------------------------------
# CONFIG
# -------------------------------
def get_config(db: sqlite3.Connection) -> Config:
    row = db.execute("""
        SELECT skip_tracks_with_synced_lyrics,
               skip_tracks_with_plain_lyrics,
               show_line_count,
               try_embed_lyrics,
               theme_mode,
               lrclib_instance
        FROM config_data
        LIMIT 1
    """).fetchone()

    return Config(
        skip_tracks_with_synced_lyrics=bool(row["skip_tracks_with_synced_lyrics"]),
        skip_tracks_with_plain_lyrics=bool(row["skip_tracks_with_plain_lyrics"]),
        show_line_count=bool(row["show_line_count"]),
        try_embed_lyrics=bool(row["try_embed_lyrics"]),
        theme_mode=row["theme_mode"],
        lrclib_instance=row["lrclib_instance"],
    )


def set_config(db: sqlite3.Connection, config: Config) -> None:
    db.execute("""
        UPDATE config_data
        SET skip_tracks_with_synced_lyrics = ?,
            skip_tracks_with_plain_lyrics = ?,
            show_line_count = ?,
            try_embed_lyrics = ?,
            theme_mode = ?,
            lrclib_instance = ?
        WHERE 1
    """, (
        config.skip_tracks_with_synced_lyrics,
        config.skip_tracks_with_plain_lyrics,
        config.show_line_count,
        config.try_embed_lyrics,
        config.theme_mode,
        config.lrclib_instance,
    ))
    db.commit()


# -------------------------------
# ARTISTS
# -------------------------------
def find_artist(db: sqlite3.Connection, name: str) -> int:
    row = db.execute("SELECT id FROM artists WHERE name = ?", (name,)).fetchone()
    if row:
        return int(row["id"])
    raise ValueError("Artist not found")


def add_artist(db: sqlite3.Connection, name: str) -> int:
    cursor = db.execute(
        "INSERT INTO artists (name, name_lower) VALUES (?, ?)",
        (name, prepare_input(name)),
    )
    db.commit()
    return int(cursor.lastrowid)


def get_artist_rows(db: sqlite3.Connection, search_query: str = "") -> list[dict]:
    q = """
    SELECT
        ar.id                AS artist_id,
        ar.name              AS artist_name,
        COUNT(t.id)          AS track_count,
        COUNT(DISTINCT t.album_id) AS album_count
    FROM artists ar
    LEFT JOIN tracks t ON t.artist_id = ar.id
    WHERE 1=1
    """
    params: list[object] = []

    if search_query:
        q += " AND ar.name LIKE ?"
        params.append(f"%{search_query}%")

    q += """
    GROUP BY ar.id, ar.name
    ORDER BY ar.name COLLATE NOCASE
    """

    cur = db.execute(q, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_artist_by_id(db: sqlite3.Connection, artist_id: int) -> dict:
    q = """
    SELECT
        id   AS artist_id,
        name AS artist_name
    FROM artists
    WHERE id = ?
    LIMIT 1
    """
    cur = db.execute(q, (int(artist_id),))
    row = cur.fetchone()
    if not row:
        raise KeyError(f"Artist not found: {artist_id}")
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


def get_artists(db: sqlite3.Connection) -> List[Artist]:
    query = """
        SELECT artists.id, artists.name, COUNT(tracks.id) AS tracks_count
        FROM artists
        JOIN tracks ON tracks.artist_id = artists.id
        GROUP BY artists.id, artists.name
        ORDER BY artists.name_lower ASC
    """
    rows = db.execute(query).fetchall()
    return [Artist.from_row(row) for row in rows]


# -------------------------------
# ALBUMS
# -------------------------------
def find_album(db: sqlite3.Connection, name: str, album_artist_name: str) -> int:
    row = db.execute(
        "SELECT id FROM albums WHERE name = ? AND album_artist_name = ?",
        (name, album_artist_name),
    ).fetchone()
    if row:
        return int(row["id"])
    raise ValueError("Album not found")


def add_album(db: sqlite3.Connection, name: str, album_artist_name: str) -> int:
    cursor = db.execute(
        """
        INSERT INTO albums (name, name_lower, album_artist_name, album_artist_name_lower)
        VALUES (?, ?, ?, ?)
        """,
        (name, prepare_input(name), album_artist_name, prepare_input(album_artist_name)),
    )
    db.commit()
    return int(cursor.lastrowid)


def get_album_rows(db: sqlite3.Connection, search_query: str = "") -> list[dict]:
    q = """
    SELECT
        a.id                    AS album_id,
        a.name                  AS album_name,
        COALESCE(ar.name, '')   AS artist_name,
        COUNT(t.id)             AS track_count
    FROM albums a
    LEFT JOIN artists ar ON ar.id = a.artist_id
    LEFT JOIN tracks  t  ON t.album_id = a.id
    WHERE 1=1
    """
    params: list[object] = []

    if search_query:
        q += " AND (a.name LIKE ? OR ar.name LIKE ? OR a.album_artist_name LIKE ?)"
        like = f"%{search_query}%"
        params += [like, like, like]

    q += """
    GROUP BY a.id, a.name, ar.name
    ORDER BY ar.name COLLATE NOCASE, a.name COLLATE NOCASE
    """

    cur = db.execute(q, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_albums(db: sqlite3.Connection) -> List[Album]:
    query = """
        SELECT albums.id, albums.name, albums.album_artist_name,
               COUNT(tracks.id) AS tracks_count
        FROM albums
        JOIN tracks ON tracks.album_id = albums.id
        GROUP BY albums.id, albums.name, albums.album_artist_name
        ORDER BY albums.name_lower ASC
    """
    rows = db.execute(query).fetchall()
    return [Album.from_row(row) for row in rows]


def get_album_by_id(db: sqlite3.Connection, album_id: int) -> dict:
    q = """
    SELECT
        a.id                  AS album_id,
        a.name                AS album_name,
        COALESCE(ar.name, '') AS artist_name,
        COALESCE(a.album_artist_name, '') AS album_artist_name,
        a.artist_id           AS artist_id
    FROM albums a
    LEFT JOIN artists ar ON ar.id = a.artist_id
    WHERE a.id = ?
    LIMIT 1
    """
    cur = db.execute(q, (int(album_id),))
    row = cur.fetchone()
    if not row:
        raise KeyError(f"Album not found: {album_id}")
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, row))


# -------------------------------
# TRACKS
# -------------------------------
def get_track_by_id(db: sqlite3.Connection, track_id: int) -> Track:
    row = db.execute("""
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
            instrumental
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON tracks.artist_id = artists.id
        WHERE tracks.id = ?
        LIMIT 1
    """, (int(track_id),)).fetchone()

    return Track(
        id=row["id"],
        file_path=row["file_path"],
        file_name=row["file_name"],
        title=row["title"],
        artist_name=row["artist_name"],
        artist_id=row["artist_id"],
        album_name=row["album_name"],
        album_artist_name=row["album_artist_name"],
        album_id=row["album_id"],
        duration=row["duration"],
        track_number=row["track_number"],
        txt_lyrics=row["txt_lyrics"],
        lrc_lyrics=row["lrc_lyrics"],
        image_path=row["image_path"],
        instrumental=bool(row["instrumental"]),
    )


def add_track(db: sqlite3.Connection, track: FsTrack) -> None:
    # Artist
    try:
        artist_id = find_artist(db, track.artist)
    except ValueError:
        artist_id = add_artist(db, track.artist)

    # Album
    try:
        album_id = find_album(db, track.album, track.album_artist)
    except ValueError:
        album_id = add_album(db, track.album, track.album_artist)

    # Detect instrumental
    is_instrumental = bool(track.lrc_lyrics and re.search(r"\[au:\s*instrumental\]", track.lrc_lyrics))

    db.execute("""
        INSERT INTO tracks (
            file_path, file_name, title, title_lower,
            album_id, artist_id, duration, track_number,
            txt_lyrics, lrc_lyrics, instrumental
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
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
    ))
    db.commit()


def add_tracks(db: sqlite3.Connection, tracks: List[FsTrack]) -> None:
    for t in tracks:
        add_track(db, t)


def get_tracks(db: sqlite3.Connection) -> List[Track]:
    cursor = db.execute("""
        SELECT
            tracks.id, file_path, file_name, title,
            artists.name AS artist_name, tracks.artist_id,
            albums.name AS album_name, albums.album_artist_name,
            album_id, duration, track_number,
            albums.image_path, txt_lyrics, lrc_lyrics, instrumental
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON tracks.artist_id = artists.id
        ORDER BY title_lower ASC
    """)
    return [Track.from_row(row) for row in cursor.fetchall()]


def get_track_rows(
    db: sqlite3.Connection,
    search_query: str,
    synced_lyrics_tracks: bool,
    plain_lyrics_tracks: bool,
    instrumental_tracks: bool,
    no_lyrics_tracks: bool,
    limit: int | None = None,
    artist_id: int | None = None,
    album_id: int | None = None,
) -> list[sqlite3.Row]:
    conditions: list[str] = []
    params: list[object] = []

    q = prepare_input(search_query or "")
    if q:
        conditions.append(
            "(tracks.title_lower LIKE ? OR artists.name_lower LIKE ? OR albums.name_lower LIKE ? OR albums.album_artist_name_lower LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like])

    if not synced_lyrics_tracks:
        conditions.append("(tracks.lrc_lyrics IS NULL OR tracks.lrc_lyrics = '[au: instrumental]')")
    if not plain_lyrics_tracks:
        conditions.append("(tracks.txt_lyrics IS NULL OR tracks.lrc_lyrics IS NOT NULL)")
    if not instrumental_tracks:
        conditions.append("tracks.instrumental = 0")
    if not no_lyrics_tracks:
        conditions.append("(tracks.txt_lyrics IS NOT NULL OR tracks.lrc_lyrics IS NOT NULL OR tracks.instrumental = 1)")

    if artist_id is not None:
        conditions.append("tracks.artist_id = ?")
        params.append(int(artist_id))

    if album_id is not None:
        conditions.append("tracks.album_id = ?")
        params.append(int(album_id))

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit_clause = f"LIMIT {int(limit)}" if limit else ""

    query = f"""
        SELECT
            tracks.id,
            tracks.title,
            artists.name AS artist_name,
            tracks.duration,
            tracks.txt_lyrics,
            tracks.lrc_lyrics,
            tracks.instrumental
        FROM tracks
        JOIN artists ON tracks.artist_id = artists.id
        JOIN albums ON tracks.album_id = albums.id
        {where_clause}
        ORDER BY tracks.title_lower ASC
        {limit_clause}
    """
    return db.execute(query, params).fetchall()


# -------------------------------
# UPDATES / BULK OPS
# -------------------------------
def update_track_synced_lyrics(db: sqlite3.Connection, track_id: int, synced_lyrics: str, plain_lyrics: str) -> Track:
    synced_lyrics = (synced_lyrics or "").strip() or None
    plain_lyrics = (plain_lyrics or "").strip() or None

    db.execute("""
        UPDATE tracks
        SET lrc_lyrics = ?, txt_lyrics = ?, instrumental = 0
        WHERE id = ?
    """, (synced_lyrics, plain_lyrics, int(track_id)))
    db.commit()
    return get_track_by_id(db, track_id)


def update_track_plain_lyrics(db: sqlite3.Connection, track_id: int, plain_lyrics: str) -> Track:
    plain_lyrics = (plain_lyrics or "").strip() or None
    db.execute("""
        UPDATE tracks
        SET txt_lyrics = ?, lrc_lyrics = NULL, instrumental = 0
        WHERE id = ?
    """, (plain_lyrics, int(track_id)))
    db.commit()
    return get_track_by_id(db, track_id)


def update_track_null_lyrics(db: sqlite3.Connection, track_id: int) -> Track:
    db.execute("""
        UPDATE tracks
        SET txt_lyrics = NULL, lrc_lyrics = NULL, instrumental = 0
        WHERE id = ?
    """, (int(track_id),))
    db.commit()
    return get_track_by_id(db, track_id)


def update_track_instrumental(db: sqlite3.Connection, track_id: int) -> Track:
    db.execute("""
        UPDATE tracks
        SET txt_lyrics = NULL, lrc_lyrics = '[au: instrumental]', instrumental = 1
        WHERE id = ?
    """, (int(track_id),))
    db.commit()
    return get_track_by_id(db, track_id)


def mark_tracks_instrumental(db: sqlite3.Connection, track_ids: list[int]) -> None:
    ids = [int(x) for x in track_ids if x is not None]
    if not ids:
        return

    db.execute("BEGIN")
    try:
        db.executemany("""
            UPDATE tracks
            SET txt_lyrics = NULL,
                lrc_lyrics = '[au: instrumental]',
                instrumental = 1
            WHERE id = ?
        """, [(i,) for i in ids])
        db.commit()
    except Exception:
        db.rollback()
        raise


def unmark_tracks_instrumental(db: sqlite3.Connection, track_ids: list[int]) -> None:
    ids = [int(x) for x in track_ids if x is not None]
    if not ids:
        return

    db.execute("BEGIN")
    try:
        db.executemany("""
            UPDATE tracks
            SET instrumental = 0,
                lrc_lyrics = CASE
                    WHEN lrc_lyrics = '[au: instrumental]' THEN NULL
                    ELSE lrc_lyrics
                END
            WHERE id = ?
        """, [(i,) for i in ids])
        db.commit()
    except Exception:
        db.rollback()
        raise


# -------------------------------
# FILTER TRACK IDS
# -------------------------------
def get_track_ids(
    db: sqlite3.Connection,
    synced_lyrics: bool,
    plain_lyrics: bool,
    instrumental: bool,
    no_lyrics: bool,
) -> List[int]:
    conditions: list[str] = []

    if not synced_lyrics:
        conditions.append("(lrc_lyrics IS NULL OR lrc_lyrics = '[au: instrumental]')")
    if not plain_lyrics:
        conditions.append("(txt_lyrics IS NULL OR lrc_lyrics IS NOT NULL)")
    if not instrumental:
        conditions.append("instrumental = 0")
    if not no_lyrics:
        conditions.append("(txt_lyrics IS NOT NULL OR lrc_lyrics IS NOT NULL OR instrumental = 1)")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = db.execute(f"SELECT id FROM tracks {where_clause} ORDER BY title_lower ASC").fetchall()
    return [int(r["id"]) for r in rows]


def get_album_track_ids(
    db: sqlite3.Connection,
    album_id: int,
    without_plain_lyrics: bool,
    without_synced_lyrics: bool,
) -> List[int]:
    conditions: list[str] = []
    if without_plain_lyrics:
        conditions.append("txt_lyrics IS NULL")
    if without_synced_lyrics:
        conditions.append("lrc_lyrics IS NULL")
    conditions.append("instrumental = 0")

    where_clause = " AND ".join(conditions)
    query = f"SELECT id FROM tracks WHERE album_id = ? {'AND ' + where_clause if where_clause else ''} ORDER BY track_number ASC"
    rows = db.execute(query, (int(album_id),)).fetchall()
    return [int(r["id"]) for r in rows]


def get_artist_track_ids(
    db: sqlite3.Connection,
    artist_id: int,
    without_plain_lyrics: bool,
    without_synced_lyrics: bool,
) -> List[int]:
    conditions: list[str] = []
    if without_plain_lyrics:
        conditions.append("txt_lyrics IS NULL")
    if without_synced_lyrics:
        conditions.append("lrc_lyrics IS NULL")
    conditions.append("instrumental = 0")

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT tracks.id
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        WHERE tracks.artist_id = ? {'AND ' + where_clause if where_clause else ''}
        ORDER BY albums.name_lower ASC, tracks.track_number ASC
    """
    rows = db.execute(query, (int(artist_id),)).fetchall()
    return [int(r["id"]) for r in rows]


# -------------------------------
# CLEAN LIBRARY
# -------------------------------
def clean_library(db: sqlite3.Connection) -> None:
    db.execute("DELETE FROM tracks")
    db.execute("DELETE FROM albums")
    db.execute("DELETE FROM artists")
    db.commit()


# -------------------------------
# GET TRACKS BY ALBUM / ARTIST
# -------------------------------
def get_album_tracks(db: sqlite3.Connection, album_id: int) -> List[Track]:
    query = """
        SELECT
            tracks.id, file_path, file_name, title,
            artists.name AS artist_name, tracks.artist_id,
            albums.name AS album_name, albums.album_artist_name,
            album_id, duration, track_number,
            albums.image_path, txt_lyrics, lrc_lyrics, instrumental
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON tracks.artist_id = artists.id
        WHERE tracks.album_id = ?
        ORDER BY track_number ASC
    """
    rows = db.execute(query, (int(album_id),)).fetchall()
    return [Track.from_row(row) for row in rows]


def get_artist_tracks(db: sqlite3.Connection, artist_id: int) -> List[Track]:
    query = """
        SELECT
            tracks.id, file_path, file_name, title,
            artists.name AS artist_name, tracks.artist_id,
            albums.name AS album_name, albums.album_artist_name,
            album_id, duration, track_number,
            albums.image_path, txt_lyrics, lrc_lyrics, instrumental
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON tracks.artist_id = artists.id
        WHERE tracks.artist_id = ?
        ORDER BY albums.name_lower ASC, track_number ASC
    """
    rows = db.execute(query, (int(artist_id),)).fetchall()
    return [Track.from_row(row) for row in rows]
