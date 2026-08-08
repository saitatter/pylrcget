from __future__ import annotations

import sqlite3
from typing import Sequence

from core.utils import prepare_input

from db.query_modules.common import escape_like


def get_directories(db: sqlite3.Connection) -> list[str]:
    cursor = db.execute("SELECT path FROM directories")
    return [row["path"] for row in cursor.fetchall()]


def set_directories(db: sqlite3.Connection, directories: list[str]) -> None:
    db.execute("DELETE FROM directories")
    for path in directories:
        db.execute("INSERT INTO directories (path) VALUES (?)", (path,))
    db.commit()


def get_init(db: sqlite3.Connection) -> bool:
    row = db.execute("SELECT init FROM library_data LIMIT 1").fetchone()
    return bool(row["init"])


def set_init(db: sqlite3.Connection, init: bool) -> None:
    db.execute("UPDATE library_data SET init = ? WHERE id = 1", (init,))
    db.commit()


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
    letter_prefix: str | None = None,
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
        params.append(f"%{escape_like(search_query)}%")

    if letter_prefix is not None:
        if letter_prefix == "#":
            q += " AND UPPER(SUBSTR(ar.name, 1, 1)) NOT GLOB '[A-Z]'"
        else:
            q += " AND UPPER(SUBSTR(ar.name, 1, 1)) = ?"
            params.append(letter_prefix.upper())

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


def get_artist_letter_counts(db: sqlite3.Connection, search_query: str = "") -> dict[str, int]:
    """Return {letter: count} for building the alpha index bar.
    '#' covers all names that don't start with A-Z."""
    q = """
    SELECT
        CASE
            WHEN UPPER(SUBSTR(ar.name, 1, 1)) GLOB '[A-Z]'
                THEN UPPER(SUBSTR(ar.name, 1, 1))
            ELSE '#'
        END AS letter,
        COUNT(DISTINCT ar.id) AS cnt
    FROM artists ar
    WHERE 1=1
    """
    params: list[object] = []
    if search_query:
        q += " AND ar.name LIKE ? ESCAPE '\\'"
        params.append(f"%{escape_like(search_query)}%")
    q += " GROUP BY letter ORDER BY letter"
    cur = db.execute(q, params)
    return {row[0]: row[1] for row in cur.fetchall()}


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
    letter_prefix: str | None = None,
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
        like = f"%{escape_like(search_query)}%"
        params += [like, like, like]

    if artist_ids:
        placeholders = ", ".join("?" for _ in artist_ids)
        q += f" AND t.artist_id IN ({placeholders})"
        params.extend(int(v) for v in artist_ids)
    elif artist_id is not None:
        q += " AND t.artist_id = ?"
        params.append(int(artist_id))

    if letter_prefix is not None:
        if letter_prefix == "#":
            q += " AND UPPER(SUBSTR(a.name, 1, 1)) NOT GLOB '[A-Z]'"
        else:
            q += " AND UPPER(SUBSTR(a.name, 1, 1)) = ?"
            params.append(letter_prefix.upper())

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


def get_album_letter_counts(
    db: sqlite3.Connection,
    search_query: str = "",
    artist_id: int | None = None,
    artist_ids: Sequence[int] | None = None,
) -> dict[str, int]:
    """Return {letter: count} for albums, for building the alpha index bar."""
    q = """
    SELECT
        CASE
            WHEN UPPER(SUBSTR(a.name, 1, 1)) GLOB '[A-Z]'
                THEN UPPER(SUBSTR(a.name, 1, 1))
            ELSE '#'
        END AS letter,
        COUNT(DISTINCT a.id) AS cnt
    FROM albums a
    LEFT JOIN artists ar ON ar.id = a.artist_id
    LEFT JOIN tracks  t  ON t.album_id = a.id
    WHERE 1=1
    """
    params: list[object] = []
    if search_query:
        q += " AND (a.name LIKE ? ESCAPE '\\')"
        params.append(f"%{escape_like(search_query)}%")
    if artist_ids:
        placeholders = ", ".join("?" for _ in artist_ids)
        q += f" AND t.artist_id IN ({placeholders})"
        params.extend(int(v) for v in artist_ids)
    elif artist_id is not None:
        q += " AND t.artist_id = ?"
        params.append(int(artist_id))
    q += " GROUP BY letter ORDER BY letter"
    cur = db.execute(q, params)
    return {row[0]: row[1] for row in cur.fetchall()}


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


def get_album_artist_rows(
    db: sqlite3.Connection,
    search_query: str = "",
    *,
    letter_prefix: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    sort_column: int = 0,
    sort_order: str = "asc",
) -> list[dict]:
    """
    Return a list of album artists grouped by ``albums.album_artist_name``.
    This represents the TPE2 / album-artist tag, distinct from the per-track
    artist stored in the ``artists`` table.
    """
    q = """
    SELECT
        COALESCE(NULLIF(a.album_artist_name, ''), ar.name, '') AS album_artist_name,
        COUNT(DISTINCT a.id)  AS album_count,
        COUNT(t.id)           AS track_count
    FROM albums a
    LEFT JOIN artists ar ON ar.id = a.artist_id
    LEFT JOIN tracks  t  ON t.album_id = a.id
    WHERE 1=1
    """
    params: list[object] = []

    if search_query:
        q += " AND (a.album_artist_name LIKE ? ESCAPE '\\\\' OR ar.name LIKE ? ESCAPE '\\\\')"
        like = f"%{escape_like(search_query)}%"
        params += [like, like]

    if letter_prefix is not None:
        name_expr = "COALESCE(NULLIF(a.album_artist_name, ''), ar.name, '')"
        if letter_prefix == "#":
            q += f" AND UPPER(SUBSTR({name_expr}, 1, 1)) NOT GLOB '[A-Z]'"
        else:
            q += f" AND UPPER(SUBSTR({name_expr}, 1, 1)) = ?"
            params.append(letter_prefix.upper())

    order = "DESC" if str(sort_order).lower() == "desc" else "ASC"
    order_map = {
        0: f"album_artist_name COLLATE NOCASE {order}",
        1: f"album_count {order}, album_artist_name COLLATE NOCASE {order}",
        2: f"track_count {order}, album_artist_name COLLATE NOCASE {order}",
    }
    col = int(sort_column) if int(sort_column) in order_map else 0
    q += f"""
    GROUP BY LOWER(COALESCE(NULLIF(a.album_artist_name, ''), ar.name, ''))
    ORDER BY {order_map[col]}
    """
    if limit:
        q += f" LIMIT {int(limit)} OFFSET {max(0, int(offset))}"

    cur = db.execute(q, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_album_artist_letter_counts(db: sqlite3.Connection, search_query: str = "") -> dict[str, int]:
    """Return {letter: count} for album artists, for the alpha index bar."""
    q = """
    SELECT
        CASE
            WHEN UPPER(SUBSTR(COALESCE(NULLIF(a.album_artist_name, ''), ar.name, ''), 1, 1)) GLOB '[A-Z]'
                THEN UPPER(SUBSTR(COALESCE(NULLIF(a.album_artist_name, ''), ar.name, ''), 1, 1))
            ELSE '#'
        END AS letter,
        COUNT(DISTINCT LOWER(COALESCE(NULLIF(a.album_artist_name, ''), ar.name, ''))) AS cnt
    FROM albums a
    LEFT JOIN artists ar ON ar.id = a.artist_id
    WHERE 1=1
    """
    params: list[object] = []
    if search_query:
        q += " AND (a.album_artist_name LIKE ? ESCAPE '\\\\' OR ar.name LIKE ? ESCAPE '\\\\')"
        like = f"%{escape_like(search_query)}%"
        params += [like, like]
    q += " GROUP BY letter ORDER BY letter"
    cur = db.execute(q, params)
    return {row[0]: row[1] for row in cur.fetchall()}


def get_album_rows_by_album_artist(
    db: sqlite3.Connection,
    album_artist_name: str,
    search_query: str = "",
    *,
    limit: int | None = None,
    offset: int = 0,
    sort_column: int = 0,
    sort_order: str = "asc",
) -> list[dict]:
    """
    Return albums that belong to a given album artist (by album_artist_name text,
    case-insensitive). Used for the Album Artists tab drill-down.
    """
    q = """
    SELECT
        a.id                    AS album_id,
        a.name                  AS album_name,
        COALESCE(NULLIF(a.album_artist_name, ''), ar.name, '') AS artist_name,
        COUNT(t.id)             AS track_count
    FROM albums a
    LEFT JOIN artists ar ON ar.id = a.artist_id
    LEFT JOIN tracks  t  ON t.album_id = a.id
    WHERE LOWER(COALESCE(NULLIF(a.album_artist_name, ''), ar.name, '')) = LOWER(?)
    """
    params: list[object] = [album_artist_name]

    if search_query:
        q += " AND (a.name LIKE ? ESCAPE '\\\\')"
        params.append(f"%{escape_like(search_query)}%")

    order = "DESC" if str(sort_order).lower() == "desc" else "ASC"
    order_map = {
        0: f"a.name COLLATE NOCASE {order}",
        1: f"artist_name COLLATE NOCASE {order}, a.name COLLATE NOCASE {order}",
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