# LRCGET (Python / Desktop Edition)

A modern, desktop-native reimplementation of **LRCGET**, focused on **interactive lyrics management**, **real-time playback**, and **advanced synced lyrics editing**.

This project goes beyond bulk LRC downloading and turns LRCGET into a **full lyrics-centric music companion** for local libraries.

---

## What this version adds (compared to original LRCGET)

### 🎵 Integrated Audio Player

- Native desktop audio playback (no WebView)
- Play / Pause / Seek / Volume
- Next / Previous track
- Automatic queue based on current filters
- Auto-next when track ends
- Keyboard shortcuts (`Space`, `Enter`, `Ctrl+←/→`)

### 📝 Advanced Lyrics Panel

- Side-by-side **tracklist + lyrics view**
- Supports:
  - **Synced lyrics (LRC)**
  - **Plain lyrics**
  - Instrumental detection
- Real-time **highlight of current lyric line**
- Click any lyric line → seek audio instantly

### ✏️ Real-Time Synced Lyrics Editing

- Edit timestamps and text directly in the UI
- Add / delete lyric lines
- Shift all timestamps forward/backward
- Live preview while music plays
- Save edits back to database instantly
- No external editor needed

### 🌐 LRCLIB Integration

- Download synced or plain lyrics from **LRCLIB**
- Per-track download
- Smart fallback:
  - synced → plain
  - plain → instrumental
- Lyrics stored locally (offline-first)

### 🚀 Publishing Workflow (Extended)

- Publish synced or plain lyrics to LRCLIB
- Pre-publish linting (structure ready)
- Publish progress dialog
- Designed for future challenge/verification flow

### 📚 Library Management

- Scan large music libraries
- SQLite database (fast, local)
- Filters:
  - Synced
  - Plain
  - Instrumental
  - No lyrics
- Instant search (title / artist / album)

### 🎨 Desktop-Native UI (No WebView)

- PySide6 / Qt
- Fast startup
- Low memory usage
- Keyboard-first workflow
- Dark, clean, modern layout
- No Electron / no Tauri / no browser dependency

---

## Supported Audio Formats

- MP3
- FLAC
- OGG
- OPUS
- WAV
- M4A

---

## Philosophy

The original **LRCGET** is excellent for **bulk downloading lyrics**.

This project focuses on:

- **interactivity**
- **editing**
- **verification**
- **publishing**
- **daily usage as a lyrics tool**

Think of it as:

> _LRCGET + music player + lyrics editor + LRCLIB client_

---

## Project Status

- ✅ Core features complete
- 🔧 Actively evolving
- 🧠 Designed for extensibility (themes, batch actions, embeds)

---

## Releases

This repository now includes GitHub Actions automation for:

- building standalone executables for **Windows**, **Linux**, and **macOS** via **PyInstaller**
- creating semantic versions and GitHub releases with **python-semantic-release**
- generating GitHub release notes automatically from commit history
- publishing release assets directly to the GitHub release page

### Commit format for automatic changelog

Use **Conventional Commits** so releases and changelog entries are categorized correctly:

- `feat: add lyrics export action`
- `fix: prevent slider jump while seeking`
- `chore: update workflow dependencies`

Use `!` or a `BREAKING CHANGE:` footer for breaking changes.

### Release flow

1. Merge commits into `main` using Conventional Commit messages.
2. The `Release` workflow runs `semantic-release` on every push to `main`.
3. If the commits require a new version, it creates the tag and publishes the GitHub release.
4. The same workflow builds platform-specific executables and uploads them to that release.

### Local executable build

```bash
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm pylrcget.spec
```

The generated executable is placed in `dist/`.

Note: the app already falls back to Qt multimedia when `mpv` is unavailable, so packaged builds remain usable even without an external `mpv` binary.

---

## Roadmap (Short)

- Embed lyrics into audio files
- Batch “download missing lyrics”
- Auto-snap timestamps while editing
- Karaoke / fade animations
- Theme customization

---

## Credits

- Original idea & LRCLIB ecosystem: **tranxuanthang / LRCGET**
- This project is an **independent desktop reimplementation**, not a fork of the codebase.
