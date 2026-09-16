from __future__ import annotations

import sqlite3


def get_remote_track_mapping(
    db: sqlite3.Connection,
    track_id: int,
    provider: str,
) -> sqlite3.Row | None:
    return db.execute(
        """
        SELECT
            track_id,
            provider,
            provider_track_id,
            match_method,
            match_score,
            remote_isrc,
            remote_title,
            remote_artist,
            remote_album,
            remote_duration,
            verified_at,
            local_metadata_fingerprint
        FROM remote_track_mapping
        WHERE track_id = ? AND provider = ?
        LIMIT 1
        """,
        (int(track_id), str(provider)),
    ).fetchone()


def upsert_remote_track_mapping(
    db: sqlite3.Connection,
    *,
    track_id: int,
    provider: str,
    provider_track_id: str,
    match_method: str,
    match_score: float,
    remote_isrc: str | None,
    remote_title: str | None,
    remote_artist: str | None,
    remote_album: str | None,
    remote_duration: float | None,
    verified_at: float,
    local_metadata_fingerprint: str,
    commit: bool = True,
) -> None:
    db.execute(
        """
        INSERT INTO remote_track_mapping (
            track_id,
            provider,
            provider_track_id,
            match_method,
            match_score,
            remote_isrc,
            remote_title,
            remote_artist,
            remote_album,
            remote_duration,
            verified_at,
            local_metadata_fingerprint
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(track_id, provider) DO UPDATE SET
            provider_track_id = excluded.provider_track_id,
            match_method = excluded.match_method,
            match_score = excluded.match_score,
            remote_isrc = excluded.remote_isrc,
            remote_title = excluded.remote_title,
            remote_artist = excluded.remote_artist,
            remote_album = excluded.remote_album,
            remote_duration = excluded.remote_duration,
            verified_at = excluded.verified_at,
            local_metadata_fingerprint = excluded.local_metadata_fingerprint
        """,
        (
            int(track_id),
            str(provider),
            str(provider_track_id),
            str(match_method),
            float(match_score),
            remote_isrc,
            remote_title,
            remote_artist,
            remote_album,
            remote_duration,
            float(verified_at),
            str(local_metadata_fingerprint),
        ),
    )
    if commit:
        db.commit()
