# LRCGET (Python / Desktop Edition)

A desktop-native reimplementation of **LRCGET** focused on **local library browsing**, **lyrics editing**, **playback**, and **LRCLIB integration**.

This version goes beyond bulk lyric downloads and turns the app into a full desktop workflow for:

- scanning local music folders
- downloading and editing synced or plain lyrics
- saving sidecar lyric files
- embedding lyrics into audio files
- publishing lyrics back to LRCLIB

---

## Highlights

### Integrated player

- native desktop playback with PySide6 / Qt
- play / pause / seek
- previous / next track
- queue based on the current visible track list
- adjustable playback speed, including custom values
- keyboard shortcuts such as `Space`, `Enter`, `Ctrl+Left`, `Ctrl+Right`

### Lyrics workflow

- synced lyrics (`.lrc`) and plain lyrics support
- real-time synced lyrics editor
- per-line snapping while audio is playing
- configurable reaction delay for timestamping
- live lyric highlighting during playback
- publish synced or plain lyrics to LRCLIB

### Library workflow

- recursive library scan into a local SQLite database
- incremental refresh using per-file signature checks (`mtime` + `size`)
- scan exclusion rules by path and regex
- drilldown browsing for `Tracks`, `Albums`, and `Artists`
- breadcrumb navigation with back / forward history

### Export and embedding

- configurable lyric export directory
- configurable filename pattern using placeholders
- opt-in sidecar export (`.lrc` / `.txt`)
- opt-in embedding into supported audio formats

### Desktop UI

- PySide6 / Qt desktop UI
- multiple built-in themes
- clickable artist / album navigation from the player bar and track list
- fast non-native file dialogs on Windows for better browsing performance

---

## Supported Audio Formats

The library scanner currently detects these formats:

- MP3
- M4A
- FLAC
- OGG / OGA
- OPUS
- WAV
- WMA
- ASF
- DSF
- DFF

Notes:

- playback support still depends on the active playback backend and codecs available on the system
- lyric embedding support is broader than playback support for some formats

---

## Lyrics Read / Write Support

The app can read lyrics from embedded tags and sidecar files, then save them back as sidecars and, for supported formats, embed them into the audio file.

Embedded lyric handling is implemented for:

- MP3
- FLAC
- M4A / MP4
- OGG Vorbis
- OPUS
- WMA / ASF
- DSF
- DFF

Sidecar lyric export supports:

- `.lrc`
- `.txt`

Filename pattern placeholders:

- `{artist}`
- `{title}`
- `{album}`
- `{track}`

---

## Settings

The Settings dialog is organized by category and includes:

### Library

- music folders
- excluded paths
- excluded regex patterns
- exclusion preview / test

### Lyrics

- save lyrics files
- embed lyrics into audio files
- download directory
- filename pattern with live preview
- reaction delay

### Appearance

- theme selection

---

## Navigation

Library navigation is route-based and supports:

- drilldown browsing inside `Albums` and `Artists`
- breadcrumb navigation
- back / forward history
- restoring the last library route between sessions

Unknown metadata buckets are normalized as `N/A` in the UI.

---

## Performance Notes

Recent performance-focused improvements include:

- incremental library refreshes using stored file signatures
- batched DB updates during scan
- path and regex exclusion pruning during scan
- debounced search input
- incremental UI loading for large `Tracks`, `Albums`, and `Artists` lists
- DB indexes for common browsing filters

---

## Releases

This repository includes GitHub Actions automation for:

- building standalone executables for Windows, Linux, and macOS via PyInstaller
- creating semantic versions and GitHub releases with `python-semantic-release`
- generating release notes from Conventional Commits
- uploading built artifacts to GitHub Releases

### Commit format

Use Conventional Commits, for example:

- `feat: add lyrics export action`
- `fix: prevent slider jump while seeking`
- `chore: update workflow dependencies`

Use `!` or a `BREAKING CHANGE:` footer for breaking changes.

### Release flow

1. Merge Conventional Commits into `main`.
2. The release workflow runs on pushes to `main`.
3. If a version bump is needed, semantic-release creates the tag and GitHub release.
4. Build artifacts are attached to that release.

### Windows note

Windows release builds are currently unsigned.

On Windows 11, SmartScreen or Defender may show a warning before launch, especially on newly downloaded builds. If you trust the release source, you can usually continue through `More info` -> `Run anyway`.

---
## Local Build

```bash
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm pylrcget.spec
```

The generated executable is placed in `dist/`.

Note: the app falls back to Qt Multimedia when `mpv` is unavailable, so packaged builds remain usable without an external `mpv` binary.

---

## Status

- core desktop workflow is implemented
- actively evolving
- designed for extensibility around themes, navigation, scanning, and lyrics workflows

---

## Credits

- Original idea and LRCLIB ecosystem: **tranxuanthang / LRCGET**
- This project is an independent desktop reimplementation, not a fork of the original codebase
