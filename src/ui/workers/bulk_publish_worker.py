from __future__ import annotations

import json
import logging
import re
import sqlite3
import time

from PySide6.QtCore import QThread, Signal

from db.queries import get_config, get_track_by_id
from lrclib import LrcLibAPI
from lrclib.exceptions import RateLimitError, ServerError

logger = logging.getLogger(__name__)


class BulkPublishWorker(QThread):
    """Publish lyrics for multiple tracks sequentially."""

    progress = Signal(int, int, str, str)  # current, total, label, status
    itemFinished = Signal(int, bool, str)  # track_id, ok, message
    finished = Signal(bool, str, dict)     # ok, summary, stats

    def __init__(
        self,
        db_path: str,
        track_ids: list[int],
        is_synced: bool,
        lrclib_instance: str,
        parent=None,
    ):
        super().__init__(parent)
        self.db_path = db_path
        self.track_ids = track_ids
        self.is_synced = is_synced
        self.lrclib_instance = lrclib_instance

    def run(self):
        db = None
        api = None
        ok_count = 0
        fail_count = 0
        skipped = 0
        cancelled = False
        total = len(self.track_ids)

        try:
            db = sqlite3.connect(self.db_path, timeout=15.0)
            db.row_factory = sqlite3.Row
            api = LrcLibAPI(user_agent="pylrcget", base_url=self.lrclib_instance)

            for idx, track_id in enumerate(self.track_ids, start=1):
                if self.isInterruptionRequested():
                    cancelled = True
                    break

                if idx > 1:
                    time.sleep(1.0)  # rate-limit: 1 req/s for publish

                track = get_track_by_id(db, track_id)
                title = (track.title or "").strip()
                artist = (track.artist_name or "").strip()
                album = (track.album_name or "").strip()
                label = f"{artist} - {title}".strip(" -") or f"Track {track_id}"

                self.progress.emit(idx, total, label, "Publishing...")

                lyrics_text = (track.lrc_lyrics or "") if self.is_synced else (track.txt_lyrics or "")
                if not lyrics_text.strip():
                    skipped += 1
                    self.itemFinished.emit(track_id, False, "No lyrics to publish.")
                    continue

                duration_s = int(round(track.duration or 0.0))
                if not title or not artist:
                    skipped += 1
                    self.itemFinished.emit(track_id, False, "Missing title or artist.")
                    continue

                if self.is_synced:
                    plain = "\n".join(
                        re.sub(r"\[\d{1,3}:\d{2}[.:]\d{2,3}\]", "", line).strip()
                        for line in lyrics_text.splitlines()
                    ).strip()
                    synced = lyrics_text
                else:
                    plain = lyrics_text
                    synced = None

                try:
                    self._publish_with_retry(api, title, artist, album, duration_s, plain, synced)
                    ok_count += 1
                    self.itemFinished.emit(track_id, True, "Published.")
                except Exception as exc:
                    fail_count += 1
                    self.itemFinished.emit(track_id, False, str(exc))
                    logger.warning("Failed to publish track %s: %s", track_id, exc)

        except Exception as exc:
            logger.exception("Bulk publish failed: %s", exc)
            self.finished.emit(False, f"Bulk publish failed: {exc}", {})
            return
        finally:
            if db is not None:
                db.close()

        stats = {"ok": ok_count, "failed": fail_count, "skipped": skipped, "total": total, "cancelled": cancelled}
        if cancelled:
            summary = f"Publish cancelled. {ok_count} published, {fail_count} failed, {skipped} skipped."
        else:
            summary = f"Published {ok_count} of {total} tracks. {fail_count} failed, {skipped} skipped."
        self.finished.emit(not cancelled and fail_count == 0, summary, stats)

    @staticmethod
    def _publish_with_retry(api, title, artist, album, duration_s, plain, synced):
        max_retries = 3
        backoff_s = 0.5
        for attempt in range(1, max_retries + 1):
            try:
                try:
                    api.publish_lyrics(
                        track_name=title,
                        artist_name=artist,
                        album_name=album,
                        duration=duration_s,
                        plain_lyrics=plain.strip() or None,
                        synced_lyrics=synced.strip() if synced else None,
                    )
                except json.JSONDecodeError:
                    pass  # LRCLIB returns empty 200 on success
                return
            except (RateLimitError, ServerError) as exc:
                if attempt >= max_retries:
                    raise
                logger.warning(
                    "Publish attempt %d/%d failed (%s), retrying in %.1fs...",
                    attempt, max_retries, type(exc).__name__, backoff_s,
                )
                time.sleep(backoff_s)
                backoff_s *= 2
