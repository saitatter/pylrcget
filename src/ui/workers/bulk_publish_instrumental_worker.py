from __future__ import annotations

import logging
import sqlite3
import time

from PySide6.QtCore import QThread, Signal

from db.queries import get_track_by_id
from core.lrclib_client import LrcLibAPI, RateLimitError, ServerError

logger = logging.getLogger(__name__)


class BulkPublishInstrumentalWorker(QThread):
    """Publish tracks as instrumental on LRCLIB (no lyrics, instrumental flag)."""

    finished = Signal(bool, str, dict)  # ok, summary, stats

    def __init__(
        self,
        db_path: str,
        track_ids: list[int],
        lrclib_instance: str,
        parent=None,
    ):
        super().__init__(parent)
        self.db_path = db_path
        self.track_ids = track_ids
        self.lrclib_instance = lrclib_instance

    def run(self):
        db = None
        ok_count = 0
        fail_count = 0
        total = len(self.track_ids)

        try:
            db = sqlite3.connect(self.db_path, timeout=15.0)
            db.row_factory = sqlite3.Row
            api = LrcLibAPI(self.lrclib_instance)

            for idx, track_id in enumerate(self.track_ids, start=1):
                if self.isInterruptionRequested():
                    break

                if idx > 1:
                    time.sleep(1.0)

                track = get_track_by_id(db, track_id)
                title = (track.title or "").strip()
                artist = (track.artist_name or "").strip()
                album = (track.album_name or "").strip()
                duration_s = int(round(track.duration or 0.0))

                if not title or not artist:
                    fail_count += 1
                    continue

                try:
                    self._publish_with_retry(api, title, artist, album, duration_s)
                    ok_count += 1
                except Exception as exc:
                    fail_count += 1
                    logger.warning("Failed to publish instrumental for track %s: %s", track_id, exc)

        except Exception as exc:
            logger.exception("Bulk instrumental publish failed: %s", exc)
            self.finished.emit(False, f"Bulk instrumental publish failed: {exc}", {})
            return
        finally:
            if db is not None:
                db.close()

        stats = {"ok": ok_count, "failed": fail_count, "total": total}
        summary = f"Published {ok_count} of {total} track(s) as instrumental. {fail_count} failed."
        self.finished.emit(fail_count == 0, summary, stats)

    @staticmethod
    def _publish_with_retry(api, title, artist, album, duration_s):
        max_retries = 3
        backoff_s = 0.5
        for attempt in range(1, max_retries + 1):
            try:
                api.publish_lyrics(
                    track_name=title,
                    artist_name=artist,
                    album_name=album,
                    duration=duration_s,
                    plain_lyrics=None,
                    synced_lyrics=None,
                )
                return
            except (RateLimitError, ServerError) as exc:
                if attempt >= max_retries:
                    raise
                logger.warning(
                    "Instrumental publish attempt %d/%d failed (%s), retrying in %.1fs...",
                    attempt, max_retries, type(exc).__name__, backoff_s,
                )
                time.sleep(backoff_s)
                backoff_s *= 2
