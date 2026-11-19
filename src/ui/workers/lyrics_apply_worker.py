from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime

from PySide6.QtCore import QObject, QThread, Signal

from core.utils import plain_text_from_lrc
from db.queries import (
    get_config,
    get_track_by_id,
    record_download_history_batch,
    update_track_plain_lyrics,
    update_track_synced_lyrics,
)
from lyrics.provenance import normalize_lyrics_source
from ui.services.download_modes import normalize_download_mode
from ui.services.lyrics_download_service import sync_track_outputs_with_result
from ui.services.lyrics_match_retry import LyricsMatchCandidate

logger = logging.getLogger(__name__)


class LyricsApplyCandidatesWorker(QThread):
    finishedApply = Signal(int, object, str)  # applied count, applied track ids, error

    def __init__(
        self,
        db_path: str,
        candidates: list[LyricsMatchCandidate],
        *,
        download_mode: str,
        lrclib_instance: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.db_path = db_path
        self.candidates = list(candidates)
        self.download_mode = download_mode
        self.lrclib_instance = lrclib_instance

    def run(self) -> None:
        applied_ids: list[int] = []
        errors: list[str] = []
        skipped = 0
        db = None
        logger.info(
            "Applying %d lyrics candidate(s) (mode=%s).",
            len(self.candidates),
            self.download_mode,
        )
        try:
            db = sqlite3.connect(self.db_path, timeout=15.0)
            db.row_factory = sqlite3.Row
            config = get_config(db)
            history_entries: list[dict[str, object]] = []

            for candidate in self.candidates:
                if self.isInterruptionRequested():
                    logger.info(
                        "Lyrics candidate apply interrupted after %d of %d candidate(s).",
                        len(applied_ids),
                        len(self.candidates),
                    )
                    break
                track_id = int(candidate.track_id)
                try:
                    updated = self._apply_candidate(db, candidate, config, errors)
                except Exception as exc:
                    # One broken track must not stop the remaining candidates in the batch.
                    logger.warning(
                        "Failed to apply lyrics candidate for track %s (%s): %s: %s",
                        track_id,
                        candidate.track_label,
                        type(exc).__name__,
                        exc,
                        exc_info=True,
                    )
                    errors.append(f"{candidate.track_label}: {exc}")
                    try:
                        db.rollback()
                    except sqlite3.Error:
                        pass
                    continue
                if updated is None:
                    skipped += 1
                    logger.info(
                        "Skipped lyrics candidate for track %s (%s): no lyrics usable in mode %s.",
                        track_id,
                        candidate.track_label,
                        self.download_mode,
                    )
                    continue
                applied_ids.append(track_id)
                history_entries.append(self._history_entry(db, candidate, bool(updated.lrc_lyrics)))

            try:
                record_download_history_batch(db, history_entries)
            except sqlite3.Error as exc:
                logger.warning("Failed to record download history for applied candidates: %s", exc)
                errors.append(f"download history: {exc}")
        except Exception as exc:
            logger.warning("Failed to apply lyrics candidates in background: %s", exc, exc_info=True)
            errors.append(str(exc))
        finally:
            if db is not None:
                db.close()

        logger.info(
            "Lyrics candidate apply finished: %d applied, %d skipped, %d error(s) of %d candidate(s).",
            len(applied_ids),
            skipped,
            len(errors),
            len(self.candidates),
        )
        self.finishedApply.emit(len(applied_ids), applied_ids, self._summarize_errors(errors))

    @staticmethod
    def _summarize_errors(errors: list[str]) -> str:
        if not errors:
            return ""
        if len(errors) == 1:
            return errors[0]
        return f"{len(errors)} problems; first: {errors[0]}"

    def _apply_candidate(
        self,
        db: sqlite3.Connection,
        candidate: LyricsMatchCandidate,
        config,
        errors: list[str],
    ):
        mode = normalize_download_mode(self.download_mode)
        synced_text = (candidate.synced_lyrics or "").strip()
        plain_text = (candidate.plain_lyrics or "").strip()
        source = normalize_lyrics_source(candidate.provider) or "lrclib"

        if mode == "plain_only":
            if not plain_text:
                plain_text = plain_text_from_lrc(synced_text)
            if not plain_text:
                return None
            update_track_plain_lyrics(db, int(candidate.track_id), plain_text, source=source)
        elif synced_text:
            existing_track = get_track_by_id(db, int(candidate.track_id))
            update_track_synced_lyrics(
                db,
                int(candidate.track_id),
                synced_text,
                existing_track.txt_lyrics or "",
                source=source,
            )
        elif plain_text and mode != "synced_only":
            update_track_plain_lyrics(db, int(candidate.track_id), plain_text, source=source)
        else:
            return None

        track = get_track_by_id(db, int(candidate.track_id))
        # Lyrics are committed at this point; output failures are reported but keep the track applied.
        outputs = sync_track_outputs_with_result(track, config)
        if outputs.sidecar_error is not None:
            errors.append(f"{candidate.track_label}: sidecar not written: {outputs.sidecar_error}")
        if outputs.embed_error is not None:
            errors.append(f"{candidate.track_label}: lyrics not embedded: {outputs.embed_error}")
        return track

    def _history_entry(self, db: sqlite3.Connection, candidate: LyricsMatchCandidate, synced: bool) -> dict[str, object]:
        try:
            track = get_track_by_id(db, int(candidate.track_id))
            title = str(track.title or "").strip()
            artist_name = str(track.artist_name or "").strip()
            album_name = str(track.album_name or "").strip()
        except (sqlite3.Error, AttributeError, TypeError):
            title = str(candidate.track_name or "").strip()
            artist_name = str(candidate.artist_name or "").strip()
            album_name = str(candidate.album_name or "").strip()

        score_note = f" Match: {int(candidate.score)}%."
        message = (
            f"Downloaded synced lyrics via reviewed match.{score_note}"
            if synced
            else f"Downloaded plain lyrics via reviewed match.{score_note}"
        )
        return {
            "track_id": int(candidate.track_id),
            "title": title,
            "artist_name": artist_name,
            "album_name": album_name,
            "download_mode": self.download_mode,
            "download_status": "synced" if synced else "plain",
            "message": message,
            "lrclib_instance": self.lrclib_instance,
            "downloaded_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
