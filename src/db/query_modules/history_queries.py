from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


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


def clear_publish_history(db: sqlite3.Connection) -> None:
    db.execute("DELETE FROM publish_history")
    db.commit()


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


def clear_download_history(db: sqlite3.Connection) -> None:
    db.execute("DELETE FROM download_history")
    db.commit()


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
    return [{"artist": row["artist"], "title": row["title"], "album": row["album"]} for row in rows]