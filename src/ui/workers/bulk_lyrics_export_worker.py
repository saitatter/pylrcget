from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from core.utils import prepare_input
from db.models import Config
from db.queries import get_track_by_id
from db.query_modules.common import escape_like
from ui.services.lyrics_download_service import sync_track_outputs_with_result

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrackExportScope:
    search_query: str = ""
    synced_lyrics_tracks: bool = True
    plain_lyrics_tracks: bool = True
    instrumental_tracks: bool = False
    no_lyrics_tracks: bool = True
    unsaved_draft_only: bool = False
    artist_id: int | None = None
    album_id: int | None = None
    artist_ids: tuple[int, ...] = ()
    album_ids: tuple[int, ...] = ()
    sort_column: int = 0
    sort_order: str = "asc"


class BulkLyricsExportWorker(QThread):
    progress = Signal(int, int, str, str, float)  # current, total, label, status, elapsed seconds
    itemFinished = Signal(int, bool, str, object)  # track_id, ok, label, payload
    finishedBatch = Signal(bool, str, dict)  # ok, summary, stats

    def __init__(
        self,
        db_path: str,
        track_ids: list[int] | None,
        export_config: Config,
        *,
        export_scope: TrackExportScope | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.track_ids = [int(track_id) for track_id in track_ids if track_id is not None] if track_ids else []
        self.export_config = export_config
        self.export_scope = export_scope
        self._started_at = 0.0

    def run(self) -> None:
        self._started_at = time.perf_counter()
        db = None
        total = len(self.track_ids)
        exported_count = 0
        skipped_count = 0
        failed_count = 0
        cancelled = False

        try:
            db = sqlite3.connect(self.db_path, timeout=15.0)
            db.row_factory = sqlite3.Row
            if not self.track_ids:
                self.track_ids = self._load_track_ids(db, self.export_scope)
                total = len(self.track_ids)

            completed = 0
            for track_id in self.track_ids:
                if self.isInterruptionRequested():
                    cancelled = True
                    break

                try:
                    track = get_track_by_id(db, int(track_id))
                except Exception as exc:  # noqa: BLE001
                    failed_count += 1
                    completed += 1
                    label = f"Track {track_id}"
                    payload = {
                        "track_id": int(track_id),
                        "status": "failed",
                        "message": f"Failed to read track metadata: {exc}",
                        "error": exc,
                    }
                    self.itemFinished.emit(int(track_id), False, label, payload)
                    self.progress.emit(completed, total, label, payload["message"], self._elapsed())
                    continue

                label = f"{(track.artist_name or '').strip()} - {(track.title or '').strip()}".strip(" -") or f"Track {track_id}"
                plain = (track.txt_lyrics or "").strip()
                synced = (track.lrc_lyrics or "").strip()
                if not plain and not synced:
                    skipped_count += 1
                    completed += 1
                    payload = {
                        "track_id": int(track_id),
                        "status": "skipped",
                        "message": "No lyrics available to export.",
                    }
                    self.itemFinished.emit(int(track_id), False, label, payload)
                    self.progress.emit(completed, total, label, payload["message"], self._elapsed())
                    continue

                try:
                    result = sync_track_outputs_with_result(track, self.export_config)
                except Exception as exc:  # noqa: BLE001
                    failed_count += 1
                    completed += 1
                    payload = {
                        "track_id": int(track_id),
                        "status": "failed",
                        "message": f"Export failed: {exc}",
                        "error": exc,
                    }
                    logger.warning("Failed to export lyrics for track %s: %s", track_id, exc)
                    self.itemFinished.emit(int(track_id), False, label, payload)
                    self.progress.emit(completed, total, label, payload["message"], self._elapsed())
                    continue

                sidecar_ok = bool(result.sidecar_paths)
                embed_ok = bool(result.embedded)
                had_error = result.sidecar_error is not None or result.embed_error is not None
                exported = sidecar_ok or embed_ok

                if exported:
                    exported_count += 1
                if had_error or not exported:
                    failed_count += 1

                completed += 1
                parts: list[str] = []
                if result.sidecar_paths:
                    parts.append(f"{len(result.sidecar_paths)} file(s)")
                if result.embedded:
                    parts.append("embedded audio")
                if result.sidecar_error is not None:
                    parts.append(f"sidecar error: {result.sidecar_error}")
                if result.embed_error is not None:
                    parts.append(f"embed error: {result.embed_error}")
                message = ", ".join(parts) if parts else "No output generated."
                status = "exported" if exported and not had_error else "partial" if exported else "failed"
                payload = {
                    "track_id": int(track_id),
                    "status": status,
                    "message": message,
                    "sidecar_paths": result.sidecar_paths,
                    "sidecar_error": result.sidecar_error,
                    "embedded": result.embedded,
                    "embed_error": result.embed_error,
                }
                self.itemFinished.emit(int(track_id), exported and not had_error, label, payload)
                self.progress.emit(completed, total, label, message, self._elapsed())

        except Exception as exc:
            logger.exception("Bulk lyrics export failed")
            stats = {
                "exported": exported_count,
                "skipped": skipped_count,
                "failed": failed_count,
                "cancelled": cancelled,
                "total": total,
            }
            self.finishedBatch.emit(False, f"Lyrics export failed: {exc}", stats)
            return
        finally:
            if db is not None:
                db.close()

        stats = {
            "exported": exported_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "cancelled": cancelled,
            "total": total,
        }
        if cancelled:
            summary = (
                f"Lyrics export cancelled. {exported_count} exported, "
                f"{skipped_count} skipped, {failed_count} failed."
            )
        else:
            summary = (
                f"Lyrics export complete. {exported_count} exported, "
                f"{skipped_count} skipped, {failed_count} failed."
            )
        self.finishedBatch.emit(not cancelled and failed_count == 0, summary, stats)

    def _elapsed(self) -> float:
        if not self._started_at:
            return 0.0
        return time.perf_counter() - self._started_at

    def _load_track_ids(self, db: sqlite3.Connection, scope: TrackExportScope | None) -> list[int]:
        if scope is None:
            return []

        conditions: list[str] = []
        params: list[object] = []

        q = prepare_input(scope.search_query or "")
        if q:
            conditions.append(
                "(tracks.title_lower LIKE ? ESCAPE '\\' OR artists.name_lower LIKE ? ESCAPE '\\' OR albums.name_lower LIKE ? ESCAPE '\\' OR albums.album_artist_name_lower LIKE ? ESCAPE '\\')"
            )
            like = f"%{escape_like(q)}%"
            params.extend([like, like, like, like])

        if scope.unsaved_draft_only:
            conditions.append("tracks.dirty_lyrics_present = 1")
        else:
            if not scope.synced_lyrics_tracks:
                conditions.append("(tracks.lrc_lyrics IS NULL OR tracks.lrc_lyrics = '[au: instrumental]')")
            if not scope.plain_lyrics_tracks:
                conditions.append("(tracks.txt_lyrics IS NULL OR tracks.lrc_lyrics IS NOT NULL)")
            if not scope.instrumental_tracks:
                conditions.append("tracks.instrumental = 0")
            if not scope.no_lyrics_tracks:
                conditions.append("(tracks.txt_lyrics IS NOT NULL OR tracks.lrc_lyrics IS NOT NULL OR tracks.instrumental = 1)")

        if scope.artist_ids:
            placeholders = ", ".join("?" for _ in scope.artist_ids)
            conditions.append(f"tracks.artist_id IN ({placeholders})")
            params.extend(int(v) for v in scope.artist_ids)
        elif scope.artist_id is not None:
            conditions.append("tracks.artist_id = ?")
            params.append(int(scope.artist_id))

        if scope.album_ids:
            placeholders = ", ".join("?" for _ in scope.album_ids)
            conditions.append(f"tracks.album_id IN ({placeholders})")
            params.extend(int(v) for v in scope.album_ids)
        elif scope.album_id is not None:
            conditions.append("tracks.album_id = ?")
            params.append(int(scope.album_id))

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order = "DESC" if str(scope.sort_order).lower() == "desc" else "ASC"
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
        col = int(scope.sort_column) if int(scope.sort_column) in order_map else 0
        order_clause = order_map[col]
        query = f"""
            SELECT tracks.id
            FROM tracks
            JOIN artists ON tracks.artist_id = artists.id
            JOIN albums ON tracks.album_id = albums.id
            {where_clause}
            ORDER BY {order_clause}
        """
        rows = db.execute(query, params).fetchall()
        return [int(row["id"]) for row in rows]
