from __future__ import annotations

import sqlite3
import threading

from db.models import Config


_config_cache: Config | None = None
_config_cache_lock = threading.Lock()


def get_config(db: sqlite3.Connection) -> Config:
    global _config_cache
    with _config_cache_lock:
        if _config_cache is not None:
            return _config_cache
    row = db.execute(
        """
        SELECT skip_tracks_with_synced_lyrics,
               skip_tracks_with_plain_lyrics,
               download_lyrics_mode,
               show_line_count,
               save_lyrics_sidecars,
               lyrics_sidecar_format,
               try_embed_lyrics,
               lyrics_embed_format,
               theme_mode,
               ui_scale_percent,
               font_size_mode,
               show_album_art,
               startup_view,
               lrclib_instance,
               lyrics_output_dir,
               lyrics_file_pattern,
               lyrics_lookup_subdir,
               scan_lyrics_source_mode,
               scan_excluded_paths,
               scan_excluded_patterns,
               scan_worker_count,
               logging_verbosity,
               reaction_delay_ms,
               playback_speed,
               playback_volume,
               last_library_route,
               hotkey_bindings_json,
               ui_state_json
        FROM config_data
        LIMIT 1
        """
    ).fetchone()

    config = Config(
        skip_tracks_with_synced_lyrics=bool(row["skip_tracks_with_synced_lyrics"]),
        skip_tracks_with_plain_lyrics=bool(row["skip_tracks_with_plain_lyrics"]),
        download_lyrics_mode=(row["download_lyrics_mode"] or "prefer_synced"),
        show_line_count=bool(row["show_line_count"]),
        save_lyrics_sidecars=bool(row["save_lyrics_sidecars"]),
        lyrics_sidecar_format=row["lyrics_sidecar_format"] or "both",
        try_embed_lyrics=bool(row["try_embed_lyrics"]),
        lyrics_embed_format=row["lyrics_embed_format"] or "both",
        theme_mode=row["theme_mode"],
        ui_scale_percent=int(row["ui_scale_percent"] or 100),
        font_size_mode=row["font_size_mode"] or "normal",
        show_album_art=bool(row["show_album_art"] if row["show_album_art"] is not None else 1),
        startup_view=row["startup_view"] or "remember_last",
        lrclib_instance=row["lrclib_instance"],
        lyrics_output_dir=row["lyrics_output_dir"] or "",
        lyrics_file_pattern=(
            row["lyrics_file_pattern"]
            if row["lyrics_file_pattern"] is not None
            else "{artist} - {title}"
        ),
        lyrics_lookup_subdir=row["lyrics_lookup_subdir"] or "",
        scan_lyrics_source_mode=row["scan_lyrics_source_mode"] or "both",
        scan_excluded_paths=row["scan_excluded_paths"] or "",
        scan_excluded_patterns=row["scan_excluded_patterns"] or "",
        scan_worker_count=int(row["scan_worker_count"] or 4),
        logging_verbosity=row["logging_verbosity"] or "info",
        reaction_delay_ms=int(row["reaction_delay_ms"] or 0),
        playback_speed=float(row["playback_speed"] or 1.0),
        playback_volume=float(row["playback_volume"] if row["playback_volume"] is not None else 0.7),
        last_library_route=row["last_library_route"] or "",
        hotkey_bindings_json=row["hotkey_bindings_json"] or "",
        ui_state_json=row["ui_state_json"] or "",
    )
    with _config_cache_lock:
        _config_cache = config
    return config


def set_config(db: sqlite3.Connection, config: Config) -> None:
    global _config_cache
    db.execute(
        """
        UPDATE config_data
        SET skip_tracks_with_synced_lyrics = ?,
            skip_tracks_with_plain_lyrics = ?,
            download_lyrics_mode = ?,
            show_line_count = ?,
            save_lyrics_sidecars = ?,
            lyrics_sidecar_format = ?,
            try_embed_lyrics = ?,
            lyrics_embed_format = ?,
            theme_mode = ?,
            ui_scale_percent = ?,
            font_size_mode = ?,
            show_album_art = ?,
            startup_view = ?,
            lrclib_instance = ?,
            lyrics_output_dir = ?,
            lyrics_file_pattern = ?,
            lyrics_lookup_subdir = ?,
            scan_lyrics_source_mode = ?,
            scan_excluded_paths = ?,
            scan_excluded_patterns = ?,
            scan_worker_count = ?,
            logging_verbosity = ?,
            reaction_delay_ms = ?,
            playback_speed = ?,
            playback_volume = ?,
            last_library_route = ?,
            hotkey_bindings_json = ?,
            ui_state_json = ?
        WHERE id = 1
        """,
        (
            config.skip_tracks_with_synced_lyrics,
            config.skip_tracks_with_plain_lyrics,
            config.download_lyrics_mode,
            config.show_line_count,
            config.save_lyrics_sidecars,
            config.lyrics_sidecar_format,
            config.try_embed_lyrics,
            config.lyrics_embed_format,
            config.theme_mode,
            config.ui_scale_percent,
            config.font_size_mode,
            config.show_album_art,
            config.startup_view,
            config.lrclib_instance,
            config.lyrics_output_dir,
            config.lyrics_file_pattern,
            config.lyrics_lookup_subdir,
            config.scan_lyrics_source_mode,
            config.scan_excluded_paths,
            config.scan_excluded_patterns,
            config.scan_worker_count,
            config.logging_verbosity,
            config.reaction_delay_ms,
            config.playback_speed,
            config.playback_volume,
            config.last_library_route,
            config.hotkey_bindings_json,
            config.ui_state_json,
        ),
    )
    db.commit()
    with _config_cache_lock:
        _config_cache = None