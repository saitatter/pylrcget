from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import List, Sequence

from core.utils import prepare_input
from db.models import Album, Artist, Config, Track
from library import scan_library
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
               download_lyrics_mode,
               show_line_count,
               save_lyrics_sidecars,
               try_embed_lyrics,
               theme_mode,
               ui_scale_percent,
               font_size_mode,
               show_album_art,
               startup_view,
               lrclib_instance,
               lyrics_output_dir,
               lyrics_file_pattern,
               lyrics_lookup_subdir,
               scan_excluded_paths,
               scan_excluded_patterns,
               reaction_delay_ms,
               playback_speed,
               playback_volume,
               last_library_route
        FROM config_data
        LIMIT 1
    """).fetchone()

    return Config(
        skip_tracks_with_synced_lyrics=bool(row["skip_tracks_with_synced_lyrics"]),
        skip_tracks_with_plain_lyrics=bool(row["skip_tracks_with_plain_lyrics"]),
        download_lyrics_mode=(row["download_lyrics_mode"] or "prefer_synced"),
        show_line_count=bool(row["show_line_count"]),
        save_lyrics_sidecars=bool(row["save_lyrics_sidecars"]),
        try_embed_lyrics=bool(row["try_embed_lyrics"]),
        theme_mode=row["theme_mode"],
        ui_scale_percent=int(row["ui_scale_percent"] or 100),
        font_size_mode=row["font_size_mode"] or "normal",
        show_album_art=bool(row["show_album_art"] if row["show_album_art"] is not None else 1),
        startup_view=row["startup_view"] or "remember_last",
        lrclib_instance=row["lrclib_instance"],
        lyrics_output_dir=row["lyrics_output_dir"] or "",
        lyrics_file_pattern=row["lyrics_file_pattern"] or "{artist} - {title}",
        lyrics_lookup_subdir=row["lyrics_lookup_subdir"] or "",
        scan_excluded_paths=row["scan_excluded_paths"] or "",
        scan_excluded_patterns=row["scan_excluded_patterns"] or "",
        reaction_delay_ms=int(row["reaction_delay_ms"] or 0),
        playback_speed=float(row["playback_speed"] or 1.0),
        playback_volume=float(row["playback_volume"] if row["playback_volume"] is not None else 0.7),
        last_library_route=row["last_library_route"] or "",
    )


def set_config(db: sqlite3.Connection, config: Config) -> None:
    db.execute("""
        UPDATE config_data
        SET skip_tracks_with_synced_lyrics = ?,
            skip_tracks_with_plain_lyrics = ?,
            download_lyrics_mode = ?,
            show_line_count = ?,
            save_lyrics_sidecars = ?,
            try_embed_lyrics = ?,
            theme_mode = ?,
            ui_scale_percent = ?,
            font_size_mode = ?,
            show_album_art = ?,
            startup_view = ?,
            lrclib_instance = ?,
            lyrics_output_dir = ?,
            lyrics_file_pattern = ?,
            lyrics_lookup_subdir = ?,
            scan_excluded_paths = ?,
            scan_excluded_patterns = ?,
            reaction_delay_ms = ?,
            playback_speed = ?,
            playback_volume = ?,
            last_library_route = ?
        WHERE 1
    """, (
        config.skip_tracks_with_synced_lyrics,
        config.skip_tracks_with_plain_lyrics,
        config.download_lyrics_mode,
        config.show_line_count,
        config.save_lyrics_sidecars,
        config.try_embed_lyrics,
        config.theme_mode,
        config.ui_scale_percent,
        config.font_size_mode,
        config.show_album_art,
        config.startup_view,
        config.lrclib_instance,
        config.lyrics_output_dir,
        config.lyrics_file_pattern,
        config.lyrics_lookup_subdir,
        config.scan_excluded_paths,
        config.scan_excluded_patterns,
        config.reaction_delay_ms,
        config.playback_speed,
        config.playback_volume,
        config.last_library_route,
    ))
    db.commit()


# -------------------------------
# ARTISTS
# -------------------------------
def find_artist(db: sqlite3.Connection, name: str) -> int:
    row = db.execute(
        "SELECT id FROM artists WHERE name_lower = ?",
        (prepare_input(name),),
    ).fetchone()
    if row:
        return int(row["id"])
    raise ValueError("Artist not found")


def add_artist(db: sqlite3.Connection, name: str, *, commit: bool = True) -> int:
    cursor = db.execute(
        "INSERT INTO artists (name, name_lower) VALUES (?, ?)",
        (name, prepare_input(name)),
    )
    if commit:
        db.commit()
    return int(cursor.lastrowid)


def get_artist_rows(
    db: sqlite3.Connection,
    search_query: str = "",
    *,
    limit: int | None = None,
    offset: int = 0,
    sort_column: int = 0,
    sort_order: str = "asc",
) -> list[dict]:
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

    order = "DESC" if str(sort_order).lower() == "desc" else "ASC"
    order_map = {
        0: f"ar.name COLLATE NOCASE {order}",
        1: f"album_count {order}, ar.name COLLATE NOCASE {order}",
        2: f"track_count {order}, ar.name COLLATE NOCASE {order}",
    }
    q += f"""
    GROUP BY ar.id, ar.name
    ORDER BY {order_map.get(int(sort_column), order_map[0])}
    """
    if limit:
        q += f" LIMIT {int(limit)} OFFSET {max(0, int(offset))}"

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
        """
        SELECT id
        FROM albums
        WHERE name_lower = ?
          AND album_artist_name_lower = ?
        """,
        (prepare_input(name), prepare_input(album_artist_name)),
    ).fetchone()
    if row:
        return int(row["id"])
    raise ValueError("Album not found")


def add_album(db: sqlite3.Connection, name: str, album_artist_name: str, *, commit: bool = True) -> int:
    cursor = db.execute(
        """
        INSERT INTO albums (name, name_lower, album_artist_name, album_artist_name_lower)
        VALUES (?, ?, ?, ?)
        """,
        (name, prepare_input(name), album_artist_name, prepare_input(album_artist_name)),
    )
    if commit:
        db.commit()
    return int(cursor.lastrowid)


def get_album_rows(
    db: sqlite3.Connection,
    search_query: str = "",
    artist_id: int | None = None,
    artist_ids: Sequence[int] | None = None,
    *,
    limit: int | None = None,
    offset: int = 0,
    sort_column: int = 0,
    sort_order: str = "asc",
) -> list[dict]:
    q = """
    SELECT
        a.id                    AS album_id,
        a.name                  AS album_name,
        COALESCE(NULLIF(a.album_artist_name, ''), ar.name, '') AS artist_name,
        COUNT(t.id)             AS track_count
    FROM albums a
    LEFT JOIN artists ar ON ar.id = a.artist_id
    LEFT JOIN tracks  t  ON t.album_id = a.id
    WHERE 1=1
    """
    params: list[object] = []

    if search_query:
        q += " AND (a.name LIKE ? OR COALESCE(NULLIF(a.album_artist_name, ''), ar.name, '') LIKE ? OR a.album_artist_name LIKE ?)"
        like = f"%{search_query}%"
        params += [like, like, like]

    if artist_ids:
        placeholders = ", ".join("?" for _ in artist_ids)
        q += f" AND t.artist_id IN ({placeholders})"
        params.extend(int(v) for v in artist_ids)
    elif artist_id is not None:
        q += " AND t.artist_id = ?"
        params.append(int(artist_id))

    order = "DESC" if str(sort_order).lower() == "desc" else "ASC"
    order_map = {
        0: f"a.name COLLATE NOCASE {order}, COALESCE(NULLIF(a.album_artist_name, ''), ar.name, '') COLLATE NOCASE {order}",
        1: f"COALESCE(NULLIF(a.album_artist_name, ''), ar.name, '') COLLATE NOCASE {order}, a.name COLLATE NOCASE {order}",
        2: f"track_count {order}, a.name COLLATE NOCASE {order}",
    }
    q += f"""
    GROUP BY a.id, a.name, a.album_artist_name, ar.name
    ORDER BY {order_map.get(int(sort_column), order_map[0])}
    """
    if limit:
        q += f" LIMIT {int(limit)} OFFSET {max(0, int(offset))}"

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
        COALESCE(NULLIF(a.album_artist_name, ''), ar.name, '') AS artist_name,
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


def add_track(db: sqlite3.Connection, track: FsTrack, *, commit: bool = True) -> None:
    # Artist
    try:
        artist_id = find_artist(db, track.artist)
    except ValueError:
        artist_id = add_artist(db, track.artist, commit=False)

    # Album
    try:
        album_id = find_album(db, track.album, track.album_artist)
    except ValueError:
        album_id = add_album(db, track.album, track.album_artist, commit=False)

    # Detect instrumental
    is_instrumental = bool(track.lrc_lyrics and re.search(r"\[au:\s*instrumental\]", track.lrc_lyrics))

    db.execute("""
        INSERT INTO tracks (
            file_path, file_name, title, title_lower,
            album_id, artist_id, duration, track_number,
            txt_lyrics, lrc_lyrics, instrumental, modified_time, file_size
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        track.modified_time,
        track.file_size,
    ))
    if commit:
        db.commit()


def add_tracks(db: sqlite3.Connection, tracks: List[FsTrack], *, commit: bool = True) -> None:
    if not tracks:
        return

    def _do_add() -> None:
        for t in tracks:
            add_track(db, t, commit=False)

    if commit:
        with db:
            _do_add()
    else:
        _do_add()


def get_tracks(db: sqlite3.Connection) -> List[Track]:
    cursor = db.execute("""
        SELECT
            tracks.id, file_path, file_name, title,
            artists.name AS artist_name, tracks.artist_id,
            albums.name AS album_name, albums.album_artist_name,
            album_id, duration, track_number, modified_time, file_size,
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
    offset: int = 0,
    artist_id: int | None = None,
    album_id: int | None = None,
    artist_ids: Sequence[int] | None = None,
    album_ids: Sequence[int] | None = None,
    sort_column: int = 0,
    sort_order: str = "asc",
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
        0: f"artists.name_lower {order}, tracks.title_lower {order}, tracks.id {order}",
        1: f"tracks.duration IS NULL ASC, tracks.duration {order}, tracks.id {order}",
        2: (
            "CASE "
            "WHEN tracks.lrc_lyrics IS NOT NULL AND tracks.lrc_lyrics != '[au: instrumental]' THEN 0 "
            "WHEN tracks.txt_lyrics IS NOT NULL THEN 1 "
            "WHEN tracks.instrumental = 1 THEN 2 "
            "ELSE 3 END "
            f"{order}, tracks.title_lower {order}, tracks.id {order}"
        ),
        3: f"tracks.title_lower {order}, tracks.id {order}",
    }
    order_clause = order_map.get(int(sort_column), order_map[0])
    limit_clause = f"LIMIT {int(limit)} OFFSET {max(0, int(offset))}" if limit else ""

    query = f"""
        SELECT
            tracks.id,
            tracks.title,
            tracks.artist_id,
            tracks.album_id,
            artists.name AS artist_name,
            albums.name AS album_name,
            tracks.duration,
            tracks.txt_lyrics,
            tracks.lrc_lyrics,
            tracks.instrumental
        FROM tracks
        JOIN artists ON tracks.artist_id = artists.id
        JOIN albums ON tracks.album_id = albums.id
        {where_clause}
        ORDER BY {order_clause}
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
        db.executemany("""
            UPDATE tracks
            SET txt_lyrics = NULL,
                lrc_lyrics = '[au: instrumental]',
                instrumental = 1
            WHERE id = ?
        """, [(i,) for i in ids])
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
    except sqlite3.Error:
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


def get_track_ids_for_download_mode(db: sqlite3.Connection, download_mode: str) -> list[int]:
    mode = (download_mode or "prefer_synced").strip() or "prefer_synced"
    conditions = ["instrumental = 0"]

    if mode == "plain_only":
        conditions.append("txt_lyrics IS NULL")
    else:
        conditions.append("(lrc_lyrics IS NULL OR lrc_lyrics = '[au: instrumental]')")

    where_clause = " AND ".join(conditions)
    rows = db.execute(
        f"SELECT id FROM tracks WHERE {where_clause} ORDER BY title_lower ASC"
    ).fetchall()
    return [int(r["id"]) for r in rows]


# -------------------------------
# CLEAN LIBRARY
# -------------------------------
def clean_library(db: sqlite3.Connection) -> None:
    db.execute("DELETE FROM tracks")
    db.execute("DELETE FROM albums")
    db.execute("DELETE FROM artists")
    db.commit()


def get_library_file_index(db: sqlite3.Connection) -> dict[str, tuple[float | None, int | None]]:
    rows = db.execute("SELECT file_path, modified_time, file_size FROM tracks").fetchall()
    return {
        row["file_path"]: (
            float(row["modified_time"]) if row["modified_time"] is not None else None,
            int(row["file_size"]) if row["file_size"] is not None else None,
        )
        for row in rows
    }


def delete_tracks_by_paths(db: sqlite3.Connection, paths: list[str], *, commit: bool = True) -> None:
    if not paths:
        return
    db.executemany("DELETE FROM tracks WHERE file_path = ?", [(path,) for path in paths])
    if commit:
        db.commit()


def prune_library(db: sqlite3.Connection) -> None:
    db.execute("DELETE FROM albums WHERE NOT EXISTS (SELECT 1 FROM tracks WHERE tracks.album_id = albums.id)")
    db.execute("DELETE FROM artists WHERE NOT EXISTS (SELECT 1 FROM tracks WHERE tracks.artist_id = artists.id)")
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


# -------------------------------
# PUBLISH HISTORY
# -------------------------------
def record_publish_history(
    db: sqlite3.Connection,
    *,
    track_id: int | None,
    title: str,
    artist_name: str,
    album_name: str,
    publish_kind: str,
    lrclib_instance: str,
    publish_status: str = "Published",
) -> int:
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    cursor = db.execute(
        """
        INSERT INTO publish_history (
            track_id,
            title,
            artist_name,
            album_name,
            publish_kind,
            publish_status,
            lrclib_instance,
            published_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(track_id) if track_id is not None else None,
            (title or "").strip(),
            (artist_name or "").strip(),
            (album_name or "").strip(),
            (publish_kind or "").strip() or "plain",
            (publish_status or "").strip() or "Published",
            (lrclib_instance or "").strip(),
            published_at,
        ),
    )
    db.commit()
    return int(cursor.lastrowid)


def get_publish_history_rows(
    db: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    query = f"""
        SELECT
            h.id,
            h.track_id,
            h.title,
            h.artist_name,
            h.album_name,
            h.publish_kind,
            h.publish_status,
            h.lrclib_instance,
            h.published_at,
            CASE WHEN t.id IS NOT NULL THEN 1 ELSE 0 END AS track_exists
        FROM publish_history h
        LEFT JOIN tracks t ON t.id = h.track_id
        ORDER BY h.published_at DESC, h.id DESC
        {limit_clause}
    """
    return db.execute(query).fetchall()


def record_download_history(
    db: sqlite3.Connection,
    *,
    track_id: int | None,
    title: str,
    artist_name: str,
    album_name: str,
    download_mode: str,
    download_status: str,
    message: str,
    lrclib_instance: str,
    commit: bool = True,
) -> int:
    downloaded_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    cursor = db.execute(
        """
        INSERT INTO download_history (
            track_id,
            title,
            artist_name,
            album_name,
            download_mode,
            download_status,
            message,
            lrclib_instance,
            downloaded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(track_id) if track_id is not None else None,
            (title or "").strip(),
            (artist_name or "").strip(),
            (album_name or "").strip(),
            (download_mode or "").strip() or "prefer_synced",
            (download_status or "").strip() or "unknown",
            (message or "").strip(),
            (lrclib_instance or "").strip(),
            downloaded_at,
        ),
    )
    if commit:
        db.commit()
    return int(cursor.lastrowid)


def record_download_history_batch(
    db: sqlite3.Connection,
    entries: list[dict[str, object]],
) -> None:
    if not entries:
        return

    rows = []
    for entry in entries:
        rows.append(
            (
                int(entry["track_id"]) if entry.get("track_id") is not None else None,
                str(entry.get("title") or "").strip(),
                str(entry.get("artist_name") or "").strip(),
                str(entry.get("album_name") or "").strip(),
                str(entry.get("download_mode") or "").strip() or "prefer_synced",
                str(entry.get("download_status") or "").strip() or "unknown",
                str(entry.get("message") or "").strip(),
                str(entry.get("lrclib_instance") or "").strip(),
                str(entry.get("downloaded_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")),
            )
        )

    db.executemany(
        """
        INSERT INTO download_history (
            track_id,
            title,
            artist_name,
            album_name,
            download_mode,
            download_status,
            message,
            lrclib_instance,
            downloaded_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    db.commit()


def get_download_history_rows(
    db: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    limit_clause = f"LIMIT {int(limit)}" if limit else ""
    query = f"""
        SELECT
            h.id,
            h.track_id,
            h.title,
            h.artist_name,
            h.album_name,
            h.download_mode,
            h.download_status,
            h.message,
            h.lrclib_instance,
            h.downloaded_at,
            CASE WHEN t.id IS NOT NULL THEN 1 ELSE 0 END AS track_exists
        FROM download_history h
        LEFT JOIN tracks t ON t.id = h.track_id
        ORDER BY h.downloaded_at DESC, h.id DESC
        {limit_clause}
    """
    return db.execute(query).fetchall()
