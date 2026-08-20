from __future__ import annotations

from core.tracklist_models import DownloadState, LyricsState, TrackListRow


def build_track_list_rows(
    rows,
    download_states: dict[int, DownloadState],
    duplicate_ids: set[int] | None = None,
) -> list[TrackListRow]:
    ui_rows: list[TrackListRow] = []
    for row in rows:
        keys = set(row.keys()) if hasattr(row, "keys") else set()
        instrumental = bool(row["instrumental"])
        if "has_instrumental_marker" in keys:
            instrumental = instrumental or bool(row["has_instrumental_marker"])
        lrc = row["lrc_lyrics"] if "lrc_lyrics" in keys else None
        txt = row["txt_lyrics"] if "txt_lyrics" in keys else None
        has_lrc = bool(row["has_lrc_lyrics"]) if "has_lrc_lyrics" in keys else bool(lrc)
        has_txt = bool(row["has_txt_lyrics"]) if "has_txt_lyrics" in keys else bool(txt)
        has_dirty_lyrics = bool(row["dirty_lyrics_present"] and (row["dirty_lrc_lyrics"] or row["dirty_txt_lyrics"]))

        if instrumental or lrc == "[au: instrumental]":
            state = LyricsState.INSTRUMENTAL
        elif has_lrc:
            state = LyricsState.SYNCED
        elif has_txt:
            state = LyricsState.PLAIN
        else:
            state = LyricsState.NONE

        duration = row["duration"]
        duration_s = round(duration) if duration is not None else None
        track_id = int(row["id"])

        ui_rows.append(
            TrackListRow(
                track_id=track_id,
                title=row["title"] or "",
                artist=row["artist_name"],
                artist_id=int(row["artist_id"]) if row["artist_id"] is not None else None,
                album=row["album_name"] or "",
                album_id=int(row["album_id"]) if row["album_id"] is not None else None,
                track_number=int(row["track_number"]) if row["track_number"] is not None else None,
                duration_s=duration_s,
                lyrics_state=state,
                has_dirty_lyrics=has_dirty_lyrics,
                download_state=download_states.get(track_id, DownloadState.IDLE),
                is_duplicate=bool(duplicate_ids and track_id in duplicate_ids),
            )
        )

    return ui_rows
