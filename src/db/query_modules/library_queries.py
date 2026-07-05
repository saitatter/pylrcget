from __future__ import annotations

import sqlite3
from typing import Sequence

from core.utils import prepare_input
from db.models import Track
from db.query_modules.track_queries import get_track_by_id
from library import scan_library


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
    return [int(row["id"]) for row in rows]


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
    return [int(row["id"]) for row in rows]


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
    return [int(row["id"]) for row in rows]


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
    return [int(row["id"]) for row in rows]


def get_library_file_index(db: sqlite3.Connection) -> dict[str, tuple[float | None, int | None]]:
    rows = db.execute("SELECT file_path, modified_time, file_size FROM tracks").fetchall()
    return {
        row["file_path"]: (
            float(row["modified_time"]) if row["modified_time"] is not None else None,
            int(row["file_size"]) if row["file_size"] is not None else None,
        )
        for row in rows
    }


def get_library_scan_index(
    db: sqlite3.Connection,
) -> dict[str, tuple[tuple[float | None, int | None], scan_library.AudioMetadata, bool]]:
    rows = db.execute(
        """
        SELECT
            tracks.file_path,
            tracks.modified_time,
            tracks.file_size,
            tracks.title,
            tracks.duration,
            tracks.track_number,
            tracks.txt_lyrics,
            tracks.lrc_lyrics,
            tracks.instrumental,
            artists.name AS artist_name,
            albums.name AS album_name,
            COALESCE(NULLIF(albums.album_artist_name, ''), artists.name, '') AS album_artist_name
        FROM tracks
        JOIN artists ON tracks.artist_id = artists.id
        JOIN albums ON tracks.album_id = albums.id
        """
    ).fetchall()
    return {
        row["file_path"]: (
            (
                float(row["modified_time"]) if row["modified_time"] is not None else None,
                int(row["file_size"]) if row["file_size"] is not None else None,
            ),
            scan_library.AudioMetadata(
                title=str(row["title"] or ""),
                album=str(row["album_name"] or "Unknown Album"),
                artist=str(row["artist_name"] or "Unknown Artist"),
                album_artist=str(row["album_artist_name"] or row["artist_name"] or "Unknown Artist"),
                track_number=int(row["track_number"]) if row["track_number"] is not None else None,
                duration=float(row["duration"] or 0.0),
            ),
            bool(row["txt_lyrics"] or row["lrc_lyrics"] or row["instrumental"]),
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
    db: sqlite3.Connection,
    paths: list[str],
) -> dict[tuple[str, str, int], tuple[str | None, str | None, bool]]:
    if not paths:
        return {}
    chunk_size = 900
    index: dict[tuple[str, str, int], tuple[str | None, str | None, bool]] = {}
    for start in range(0, len(paths), chunk_size):
        chunk = paths[start : start + chunk_size]
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
        for row in rows:
            key = (row["title_lower"] or "", row["artist_lower"] or "", round(row["duration"] or 0))
            index[key] = (row["txt_lyrics"], row["lrc_lyrics"], bool(row["instrumental"]))
    return index


def get_duplicate_track_ids(db: sqlite3.Connection) -> set[int]:
    rows = db.execute(
        """
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
        """
    ).fetchall()
    return {int(row["id"]) for row in rows}


def get_similar_lyrics_track_rows(
    db: sqlite3.Connection,
    source_track_id: int,
    *,
    min_score: int = 55,
) -> list[dict]:
    source = get_track_by_id(db, int(source_track_id))
    source_title = prepare_input(source.title)
    source_artist = prepare_input(source.artist_name)
    source_duration = float(source.duration or 0.0)

    rows = db.execute(
        """
        SELECT
            tracks.id,
            tracks.file_path,
            tracks.file_name,
            tracks.title,
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
        WHERE tracks.id != ?
          AND tracks.title_lower = ?
          AND artists.name_lower = ?
        """,
        (int(source_track_id), source_title, source_artist),
    ).fetchall()

    matches: list[dict] = []
    for row in rows:
        candidate_title = prepare_input(row["title"] or "")
        candidate_artist = prepare_input(row["artist_name"] or "")
        candidate_duration = float(row["duration"] or 0.0)

        if candidate_title != source_title or candidate_artist != source_artist:
            continue

        duration_score = _duration_similarity_percent(source_duration, candidate_duration)
        score = round(duration_score)
        if score < int(min_score):
            continue

        matches.append(
            {
                "track": Track.from_row(row),
                "score": int(score),
                "title_score": 100,
                "artist_score": 100,
                "duration_score": int(round(duration_score)),
                "duration_delta": abs(candidate_duration - source_duration),
            }
        )

    return sorted(
        matches,
        key=lambda item: (
            -int(item["score"]),
            float(item["duration_delta"]),
            prepare_input(item["track"].album_name),
            int(item["track"].track_number or 0),
            prepare_input(item["track"].title),
        ),
    )


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


def _duration_similarity_percent(left: float, right: float) -> float:
    if left <= 0 or right <= 0:
        return 0.0
    diff = abs(float(left) - float(right))
    if diff <= 1.0:
        return 100.0
    tolerance = max(12.0, min(left, right) * 0.08)
    return max(0.0, 100.0 - (diff / tolerance * 100.0))