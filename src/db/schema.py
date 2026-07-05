from __future__ import annotations

SCHEMA_V1_SQL = """
CREATE TABLE directories (
    id INTEGER PRIMARY KEY,
    path TEXT
);

CREATE TABLE library_data (
    id INTEGER PRIMARY KEY,
    init BOOLEAN
);

CREATE TABLE config_data (
    id INTEGER PRIMARY KEY,
    skip_not_needed_tracks BOOLEAN DEFAULT 0,
    skip_tracks_with_synced_lyrics BOOLEAN DEFAULT 0,
    skip_tracks_with_plain_lyrics BOOLEAN DEFAULT 0,
    download_lyrics_mode TEXT DEFAULT 'prefer_synced',
    show_line_count BOOLEAN DEFAULT 1,
    save_lyrics_sidecars BOOLEAN DEFAULT 1,
    lyrics_sidecar_format TEXT DEFAULT 'both',
    try_embed_lyrics BOOLEAN DEFAULT 1,
    lyrics_embed_format TEXT DEFAULT 'both',
    theme_mode TEXT DEFAULT 'auto',
    ui_scale_percent INTEGER DEFAULT 100,
    font_size_mode TEXT DEFAULT 'normal',
    show_album_art BOOLEAN DEFAULT 1,
    startup_view TEXT DEFAULT 'remember_last',
    lrclib_instance TEXT DEFAULT 'https://lrclib.net',
    lyrics_output_dir TEXT DEFAULT '',
    lyrics_file_pattern TEXT DEFAULT '{artist} - {title}',
    lyrics_lookup_subdir TEXT DEFAULT '',
    scan_lyrics_source_mode TEXT DEFAULT 'both',
    scan_excluded_paths TEXT DEFAULT '',
    scan_excluded_patterns TEXT DEFAULT '',
    scan_worker_count INTEGER DEFAULT 4,
    logging_verbosity TEXT DEFAULT 'info',
    reaction_delay_ms INTEGER DEFAULT 0,
    playback_speed REAL DEFAULT 1.0,
    playback_volume REAL DEFAULT 0.7,
    last_library_route TEXT DEFAULT '',
    hotkey_bindings_json TEXT DEFAULT '',
    ui_state_json TEXT DEFAULT ''
);

CREATE TABLE artists (
    id INTEGER PRIMARY KEY,
    name TEXT,
    name_lower TEXT
);

CREATE TABLE albums (
    id INTEGER PRIMARY KEY,
    name TEXT,
    artist_id INTEGER,
    image_path TEXT,
    name_lower TEXT,
    album_artist_name TEXT,
    album_artist_name_lower TEXT,
    FOREIGN KEY(artist_id) REFERENCES artists(id)
);

CREATE TABLE tracks (
    id INTEGER PRIMARY KEY,
    file_path TEXT UNIQUE,
    file_name TEXT,
    title TEXT,
    title_lower TEXT,
    album_id INTEGER,
    artist_id INTEGER,
    duration FLOAT,
    lrc_lyrics TEXT,
    txt_lyrics TEXT,
    dirty_lrc_lyrics TEXT,
    dirty_txt_lyrics TEXT,
    dirty_lyrics_present BOOLEAN DEFAULT 0,
    instrumental BOOLEAN DEFAULT 0,
    track_number INTEGER,
    modified_time REAL,
    file_size INTEGER,
    FOREIGN KEY(artist_id) REFERENCES artists(id),
    FOREIGN KEY(album_id) REFERENCES albums(id)
);

CREATE TABLE publish_history (
    id INTEGER PRIMARY KEY,
    track_id INTEGER,
    title TEXT NOT NULL,
    artist_name TEXT NOT NULL,
    album_name TEXT NOT NULL,
    publish_kind TEXT NOT NULL,
    publish_status TEXT NOT NULL DEFAULT 'Published',
    lrclib_instance TEXT NOT NULL,
    published_at TEXT NOT NULL
);

CREATE TABLE download_history (
    id INTEGER PRIMARY KEY,
    track_id INTEGER,
    title TEXT NOT NULL,
    artist_name TEXT NOT NULL,
    album_name TEXT NOT NULL,
    download_mode TEXT NOT NULL,
    download_status TEXT NOT NULL,
    message TEXT NOT NULL,
    lrclib_instance TEXT NOT NULL,
    downloaded_at TEXT NOT NULL
);

CREATE TABLE search_history (
    id INTEGER PRIMARY KEY,
    artist TEXT NOT NULL,
    title TEXT NOT NULL,
    album TEXT NOT NULL DEFAULT '',
    searched_at TEXT NOT NULL
);

CREATE INDEX idx_tracks_title ON tracks(title);
CREATE INDEX idx_albums_name ON albums(name);
CREATE INDEX idx_artists_name ON artists(name);
CREATE INDEX idx_tracks_title_lower ON tracks(title_lower);
CREATE INDEX idx_albums_name_lower ON albums(name_lower);
CREATE INDEX idx_artists_name_lower ON artists(name_lower);
CREATE INDEX idx_albums_album_artist_name_lower ON albums(album_artist_name_lower);
CREATE INDEX idx_tracks_track_number ON tracks(track_number);
CREATE UNIQUE INDEX idx_tracks_file_path ON tracks(file_path);
CREATE INDEX idx_tracks_dirty ON tracks(dirty_lyrics_present);
CREATE INDEX idx_tracks_artist_id ON tracks(artist_id);
CREATE INDEX idx_tracks_album_id ON tracks(album_id);
CREATE INDEX idx_tracks_artist_album ON tracks(artist_id, album_id);
CREATE INDEX idx_tracks_album_track_number ON tracks(album_id, track_number);
CREATE INDEX idx_publish_history_published_at ON publish_history(published_at DESC, id DESC);
CREATE INDEX idx_publish_history_track_id ON publish_history(track_id);
CREATE INDEX idx_download_history_downloaded_at ON download_history(downloaded_at DESC, id DESC);
CREATE INDEX idx_download_history_track_id ON download_history(track_id);
CREATE INDEX idx_search_history_searched_at ON search_history(searched_at DESC);

INSERT INTO library_data (init) VALUES (0);
INSERT INTO config_data (
    skip_not_needed_tracks,
    skip_tracks_with_synced_lyrics,
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
) VALUES (
    0,
    0,
    0,
    'prefer_synced',
    1,
    1,
    'both',
    1,
    'both',
    'auto',
    100,
    'normal',
    1,
    'remember_last',
    'https://lrclib.net',
    '',
    '{artist} - {title}',
    '',
    'both',
    '',
    '',
    4,
    'info',
    0,
    1.0,
    0.7,
    '',
    '',
    ''
);
"""
