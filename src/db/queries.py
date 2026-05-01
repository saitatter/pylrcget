from __future__ import annotations

import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Sequence

from core.models import FsTrack
from core.utils import prepare_input
from db.models import Config, Track
from library import scan_library


def _escape_like(value: str) -> str:
    """Escape SQL LIKE metacharacters so they match literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# -------------------------------
# DIRECTORIES
# -------------------------------
def get_directories(db: sqlite3.Connection) -> list[str]:
    cursor = db.execute("SELECT path FROM directories")
    return [row["path"] for row in cursor.fetchall()]


def set_directories(db: sqlite3.Connection, directories: list[str]) -> None:
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
    db.execute("UPDATE library_data SET init = ? WHERE id = 1", (init,))
    db.commit()


# -------------------------------
# CONFIG
# -------------------------------
_config_cache: Config | None = None
_config_cache_lock = threading.Lock()


def get_config(db: sqlite3.Connection) -> Config:
    global _config_cache
    with _config_cache_lock:
        if _config_cache is not None:
            return _config_cache
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

    config = Config(
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
    with _config_cache_lock:
        _config_cache = config
    return config


def set_config(db: sqlite3.Connection, config: Config) -> None:
    global _config_cache
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
        WHERE id = 1
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
    with _config_cache_lock:
        _config_cache = None


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
        q += " AND ar.name LIKE ? ESCAPE '\\'"
        params.append(f"%{_escape_like(search_query)}%")

    order = "DESC" if str(sort_order).lower() == "desc" else "ASC"
    order_map = {
        0: f"ar.name COLLATE NOCASE {order}",
        1: f"album_count {order}, ar.name COLLATE NOCASE {order}",
        2: f"track_count {order}, ar.name COLLATE NOCASE {order}",
    }
    col = int(sort_column) if int(sort_column) in order_map else 0
    q += f"""
    GROUP BY ar.id, ar.name
    ORDER BY {order_map[col]}
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
        q += " AND (a.name LIKE ? ESCAPE '\\' OR COALESCE(NULLIF(a.album_artist_name, ''), ar.name, '') LIKE ? ESCAPE '\\' OR a.album_artist_name LIKE ? ESCAPE '\\')"
        like = f"%{_escape_like(search_query)}%"
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
    col = int(sort_column) if int(sort_column) in order_map else 0
    q += f"""
    GROUP BY a.id, a.name, a.album_artist_name, ar.name
    ORDER BY {order_map[col]}
    """
    if limit:
        q += f" LIMIT {int(limit)} OFFSET {max(0, int(offset))}"

    cur = db.execute(q, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


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
            dirty_txt_lyrics,
            dirty_lrc_lyrics,
            dirty_lyrics_present,
            instrumental
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON tracks.artist_id = artists.id
        WHERE tracks.id = ?
        LIMIT 1
    """, (int(track_id),)).fetchone()

    return Track.from_row(row)


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

    # Detect instrumental (explicit flag from orphan reattachment, or auto-detect from LRC)
    is_instrumental = track.instrumental or bool(
        track.lrc_lyrics and re.search(r"\[au:\s*instrumental\]", track.lrc_lyrics)
    )

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


def get_existing_file_paths(db: sqlite3.Connection, paths: list[str]) -> set[str]:
    """Return the subset of *paths* that already exist in the tracks table."""
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
        # Pre-load artist and album caches to avoid per-track lookups
        artist_cache: dict[str, int] = {
            row[1]: row[0]
            for row in db.execute("SELECT id, name_lower FROM artists").fetchall()
        }
        album_cache: dict[tuple[str, str], int] = {
            (row[1], row[2]): row[0]
            for row in db.execute("SELECT id, name_lower, album_artist_name_lower FROM albums").fetchall()
        }
        for t in tracks:
            # Resolve artist
            artist_key = prepare_input(t.artist)
            artist_id = artist_cache.get(artist_key)
            if artist_id is None:
                artist_id = add_artist(db, t.artist, commit=False)
                artist_cache[artist_key] = artist_id

            # Resolve album
            album_key = (prepare_input(t.album), prepare_input(t.album_artist))
            album_id = album_cache.get(album_key)
            if album_id is None:
                album_id = add_album(db, t.album, t.album_artist, commit=False)
                album_cache[album_key] = album_id

            is_instrumental = t.instrumental or bool(
                t.lrc_lyrics and re.search(r"\[au:\s*instrumental\]", t.lrc_lyrics)
            )
            db.execute("""
                INSERT OR IGNORE INTO tracks (
                    file_path, file_name, title, title_lower,
                    album_id, artist_id, duration, track_number,
                    txt_lyrics, lrc_lyrics, instrumental, modified_time, file_size
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                t.file_path, t.file_name, t.title, prepare_input(t.title),
                album_id, artist_id, t.duration, t.track_number,
                t.txt_lyrics, t.lrc_lyrics, is_instrumental,
                t.modified_time, t.file_size,
            ))

    if commit:
        with db:
            _do_add()
    else:
        _do_add()


def get_tracks(db: sqlite3.Connection) -> list[Track]:
    cursor = db.execute("""
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
    """)
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
            "(tracks.title_lower LIKE ? ESCAPE '\\' OR artists.name_lower LIKE ? ESCAPE '\\' OR albums.name_lower LIKE ? ESCAPE '\\' OR albums.album_artist_name_lower LIKE ? ESCAPE '\\')"
        )
        like = f"%{_escape_like(q)}%"
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


# -------------------------------
# UPDATES / BULK OPS
# -------------------------------
def update_track_synced_lyrics(db: sqlite3.Connection, track_id: int, synced_lyrics: str, plain_lyrics: str) -> None:
    synced_lyrics = (synced_lyrics or "").strip() or None
    plain_lyrics = (plain_lyrics or "").strip() or None

    db.execute("""
        UPDATE tracks
        SET lrc_lyrics = ?, txt_lyrics = ?, dirty_lrc_lyrics = NULL, dirty_txt_lyrics = NULL, dirty_lyrics_present = 0, instrumental = 0
        WHERE id = ?
    """, (synced_lyrics, plain_lyrics, int(track_id)))
    db.commit()


def update_track_plain_lyrics(db: sqlite3.Connection, track_id: int, plain_lyrics: str) -> None:
    plain_lyrics = (plain_lyrics or "").strip() or None
    db.execute("""
        UPDATE tracks
        SET txt_lyrics = ?, lrc_lyrics = NULL, dirty_lrc_lyrics = NULL, dirty_txt_lyrics = NULL, dirty_lyrics_present = 0, instrumental = 0
        WHERE id = ?
    """, (plain_lyrics, int(track_id)))
    db.commit()


def update_track_null_lyrics(db: sqlite3.Connection, track_id: int) -> None:
    db.execute("""
        UPDATE tracks
        SET txt_lyrics = NULL, lrc_lyrics = NULL, dirty_lrc_lyrics = NULL, dirty_txt_lyrics = NULL, dirty_lyrics_present = 0, instrumental = 0
        WHERE id = ?
    """, (int(track_id),))
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
    db.execute("""
        UPDATE tracks
        SET txt_lyrics = NULL, lrc_lyrics = '[au: instrumental]', dirty_lrc_lyrics = NULL, dirty_txt_lyrics = NULL, dirty_lyrics_present = 0, instrumental = 1
        WHERE id = ?
    """, (int(track_id),))
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
        db.executemany("""
            UPDATE tracks
            SET txt_lyrics = NULL,
                lrc_lyrics = '[au: instrumental]',
                dirty_txt_lyrics = NULL,
                dirty_lrc_lyrics = NULL,
                dirty_lyrics_present = 0,
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
                END,
                dirty_txt_lyrics = NULL,
                dirty_lrc_lyrics = NULL,
                dirty_lyrics_present = 0
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
) -> list[int]:
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
) -> list[int]:
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
) -> list[int]:
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


def get_orphan_lyrics_index(
    db: sqlite3.Connection, paths: list[str],
) -> dict[tuple[str, str, int], tuple[str | None, str | None, bool]]:
    """Return a match-key → (txt_lyrics, lrc_lyrics, instrumental) dict
    for tracks at *paths* that carry lyrics or instrumental flag.

    Match key is (title_lower, artist_name_lower, duration_rounded_int).
    """
    if not paths:
        return {}
    _CHUNK = 900  # stay below SQLite SQLITE_MAX_VARIABLE_NUMBER (default 999)
    index: dict[tuple[str, str, int], tuple[str | None, str | None, bool]] = {}
    for start in range(0, len(paths), _CHUNK):
        chunk = paths[start:start + _CHUNK]
        placeholders = ",".join("?" for _ in chunk)
        rows = db.execute(
            f"""
            SELECT t.title_lower, a.name_lower AS artist_lower,
                   t.duration, t.txt_lyrics, t.lrc_lyrics, t.instrumental
            FROM tracks t
            JOIN artists a ON t.artist_id = a.id
            WHERE t.file_path IN ({placeholders})
              AND (t.txt_lyrics IS NOT NULL OR t.lrc_lyrics IS NOT NULL OR t.instrumental = 1)
            """,
            chunk,
        ).fetchall()
        for r in rows:
            key = (r["title_lower"] or "", r["artist_lower"] or "", round(r["duration"] or 0))
            index[key] = (r["txt_lyrics"], r["lrc_lyrics"], bool(r["instrumental"]))
    return index


def prune_library(db: sqlite3.Connection) -> None:
    db.execute("DELETE FROM albums WHERE NOT EXISTS (SELECT 1 FROM tracks WHERE tracks.album_id = albums.id)")
    db.execute("DELETE FROM artists WHERE NOT EXISTS (SELECT 1 FROM tracks WHERE tracks.artist_id = artists.id)")
    db.commit()


def get_duplicate_track_ids(db: sqlite3.Connection) -> set[int]:
    """Return track IDs that share the same title + artist + rounded duration."""
    rows = db.execute("""
        SELECT t.id
        FROM tracks t
        JOIN artists a ON t.artist_id = a.id
        WHERE EXISTS (
            SELECT 1
            FROM tracks t2
            JOIN artists a2 ON t2.artist_id = a2.id
            WHERE t2.title_lower = t.title_lower
              AND a2.name_lower = a.name_lower
              AND ROUND(t2.duration) = ROUND(t.duration)
              AND t2.id != t.id
        )
    """).fetchall()
    return {int(r["id"]) for r in rows}


# -------------------------------
# GET TRACKS BY ALBUM / ARTIST
# -------------------------------
def get_album_tracks(db: sqlite3.Connection, album_id: int) -> list[Track]:
    query = """
        SELECT
            tracks.id, file_path, file_name, title,
            artists.name AS artist_name, tracks.artist_id,
            albums.name AS album_name, albums.album_artist_name,
            album_id, duration, track_number,
            albums.image_path, txt_lyrics, lrc_lyrics, dirty_txt_lyrics, dirty_lrc_lyrics, dirty_lyrics_present, instrumental
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON tracks.artist_id = artists.id
        WHERE tracks.album_id = ?
        ORDER BY track_number ASC
    """
    rows = db.execute(query, (int(album_id),)).fetchall()
    return [Track.from_row(row) for row in rows]


def get_artist_tracks(db: sqlite3.Connection, artist_id: int) -> list[Track]:
    query = """
        SELECT
            tracks.id, file_path, file_name, title,
            artists.name AS artist_name, tracks.artist_id,
            albums.name AS album_name, albums.album_artist_name,
            album_id, duration, track_number,
            albums.image_path, txt_lyrics, lrc_lyrics, dirty_txt_lyrics, dirty_lrc_lyrics, dirty_lyrics_present, instrumental
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


# -------------------------------
# SEARCH HISTORY
# -------------------------------
def record_search_history(
    db: sqlite3.Connection,
    *,
    artist: str,
    title: str,
    album: str = "",
) -> None:
    searched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    db.execute(
        "INSERT INTO search_history (artist, title, album, searched_at) VALUES (?, ?, ?, ?)",
        (
            (artist or "").strip(),
            (title or "").strip(),
            (album or "").strip(),
            searched_at,
        ),
    )
    db.commit()


def get_recent_search_queries(
    db: sqlite3.Connection,
    *,
    limit: int = 50,
) -> list[dict]:
    """Return recent unique artist/title/album combinations, newest first."""
    rows = db.execute(
        """
        SELECT artist, title, album, MAX(searched_at) AS last_searched
        FROM search_history
        GROUP BY artist, title, album
        ORDER BY last_searched DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [{"artist": r["artist"], "title": r["title"], "album": r["album"]} for r in rows]
