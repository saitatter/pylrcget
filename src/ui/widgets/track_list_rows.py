from __future__ import annotations

from core.tracklist_models import DownloadState, LyricsState, TrackListRow


def build_track_list_rows(rows, download_states: dict[int, DownloadState]) -> list[TrackListRow]:
    ui_rows: list[TrackListRow] = []
    for row in rows:
        instrumental = bool(row["instrumental"])
        lrc = row["lrc_lyrics"]
        txt = row["txt_lyrics"]
        has_dirty_lyrics = bool(row["dirty_lyrics_present"] and (row["dirty_lrc_lyrics"] or row["dirty_txt_lyrics"]))

        if instrumental or lrc == "[au: instrumental]":
            state = LyricsState.INSTRUMENTAL
        elif lrc:
            state = LyricsState.SYNCED
        elif txt:
            state = LyricsState.PLAIN
        else:
            state = LyricsState.NONE

        duration = row["duration"]
        duration_s = int(round(duration)) if duration is not None else None
        track_id = int(row["id"])

        ui_rows.append(
            TrackListRow(
                track_id=track_id,
                title=row["title"] or "",
                artist=row["artist_name"],
                artist_id=int(row["artist_id"]) if row["artist_id"] is not None else None,
                album=row["album_name"] or "",
                album_id=int(row["album_id"]) if row["album_id"] is not None else None,
                duration_s=duration_s,
                lyrics_state=state,
                has_dirty_lyrics=has_dirty_lyrics,
                download_state=download_states.get(track_id, DownloadState.IDLE),
            )
        )

    return ui_rows
