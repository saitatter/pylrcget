# PyLrcGet

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![GitHub Release](https://img.shields.io/github/v/release/saitatter/pylrcget)
[![Issues](https://img.shields.io/github/issues/saitatter/pylrcget)](https://github.com/saitatter/pylrcget/issues)
![Made with Python](https://img.shields.io/badge/Made%20with-Python-3776AB?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-Qt-41CD52?logo=qt&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

> Desktop-native lyrics manager and player with local library browsing, editing, playback, and **LRCLIB** integration.

PyLrcGet goes beyond bulk lyric downloads and turns the app into a full desktop workflow for scanning local music folders, downloading and editing synced or plain lyrics, saving sidecar lyric files, embedding lyrics into audio files, and publishing lyrics back to LRCLIB.

---

## ✨ Features

### 🎵 Integrated Player

- Native desktop playback with PySide6 / Qt
- Play / pause / seek / previous / next track
- Queue based on the current visible track list
- Adjustable playback speed, including custom values
- Playback volume control with mute-safe persistence across sessions
- Keyboard shortcuts: `Space`, `Enter`, `Ctrl+Left`, `Ctrl+Right`

### 📝 Lyrics Workflow

- Synced lyrics (`.lrc`) and plain lyrics support
- Toggle between synced and plain editing modes on any track
- Configurable download modes: `Prefer synced`, `Synced only`, `Plain only`
- Bulk `Download missing lyrics` action based on the active download mode
- Per-selection download overrides from the track context menu
- Real-time synced lyrics editor with per-line snapping while audio is playing
- Configurable reaction delay for timestamping
- Shift selected lines by preset or custom time offsets
- Shift the entire lyric sheet from the first line based on the current playback position
- Live lyric highlighting during playback
- Unsaved draft tracking with badge indicator and discard action
- Filter tracks by unsaved draft state
- Explicit `Export Files` action for generating sidecar lyrics from local / embedded lyrics
- Publish synced or plain lyrics to LRCLIB

### 📚 Library

- Recursive library scan into a local SQLite database
- Drag-and-drop audio files or folders into the window to import them
- Incremental refresh using per-file signature checks (`mtime` + `size`)
- Scan exclusion rules by path and regex
- Automatic re-scan after changing library folders in Settings
- Drilldown browsing for `Tracks`, `Albums`, and `Artists`
- Breadcrumb-based navigation across library views

### 💾 Export & Embedding

- Configurable lyric export directory
- Configurable filename pattern using placeholders (`{filename}`, `{artist}`, `{title}`, `{album}`, `{track}`)
- Opt-in sidecar export (`.lrc` / `.txt`)
- Opt-in embedding into supported audio formats

### 🎨 Desktop UI

- PySide6 / Qt desktop UI with multiple built-in themes
- Clickable artist / album navigation from the player bar and track list
- Native Windows file dialogs for better mapped-drive and network-share support
- Built-in log panel with live filtering, copy/save actions, and on-disk log files
- In-app update checker with release notes, download links, and installer launch support

---

## 🎧 Supported Audio Formats

| Format | Library Scan | Lyrics Read/Write | Sidecar Export |
|--------|:---:|:---:|:---:|
| MP3 | ✅ | ✅ | ✅ |
| M4A / MP4 | ✅ | ✅ | ✅ |
| FLAC | ✅ | ✅ | ✅ |
| OGG / OGA | ✅ | ✅ | ✅ |
| OPUS | ✅ | ✅ | ✅ |
| WMA / ASF | ✅ | ✅ | ✅ |
| DSF | ✅ | ✅ | ✅ |
| DFF | ✅ | ✅ | ✅ |
| MPC / Musepack | ✅ | ✅ | ✅ |
| WAV | ✅ | — | ✅ |

> **Note:** Playback support depends on the active playback backend and codecs available on the system. Lyric embedding support is broader than playback support for some formats.

---

## ⚙️ Settings

| Category | Options |
|----------|---------|
| **Library** | Music folders, excluded paths, excluded regex patterns, exclusion preview/test, auto-refresh after folder changes |
| **Lyrics** | Download mode, save lyrics files, embed lyrics, download directory, filename pattern with live preview, reaction delay, line shift presets |
| **Appearance** | Theme selection, UI scale (90–125%), font size (Small/Normal/Large), album art toggle, startup view |
| **Updates** | In-app version check, release notes preview, download/install actions |

---

## 🔄 Download Modes

| Mode | Behavior |
|------|----------|
| **Prefer synced, fallback to plain** | Tries synced first, saves plain if synced unavailable |
| **Synced only** | Saves only synced lyrics, skips plain-only matches |
| **Plain only** | Saves only plain lyrics, derives plain from synced by stripping timestamps if needed |

The track context menu supports temporary mode overrides for the current selection. The `Tracks` table color-codes lyric state: 🔴 No lyrics · 🟠 Plain · 🟢 Synced · 🔵 Instrumental.

The global `Download missing lyrics` action can also upgrade plain-only tracks to synced when synced lyrics become available on LRCLIB.

---

## 🧭 Navigation

- Route-based drilldown inside `Albums` and `Artists`
- Breadcrumb navigation with session restore
- Unknown metadata normalized as `N/A`
- `My LRCLIB` views for published lyrics and download history

---

## 🔍 Diagnostics

- Toggleable in-app `Logs` panel with level filters (`INFO`, `WARNING`, `ERROR`)
- `Copy`, `Save`, and `Open Folder` actions for logs
- Automatic log panel opening for errors
- Toast notifications for important errors
- Rotating log files stored in the app data directory
- Dedicated progress overlay for bulk downloads with per-track results, cancel support, and session summary

---

## ⚡ Performance

- Incremental library refreshes using stored file signatures
- Batched DB updates during scan
- Path and regex exclusion pruning during scan
- Debounced search input
- Incremental UI loading for large track/album/artist lists
- DB indexes for common browsing filters

---

## 🚀 Quick Start

### Run from source

```bash
python -m pip install -r requirements.txt
python main.py
```

### Build standalone executable

```bash
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm pylrcget.spec
```

The generated executable is placed in `dist/`.

> **Note:** The app falls back to Qt Multimedia when `mpv` is unavailable, so packaged builds remain usable without an external `mpv` binary.

---

## 🔄 Releases

Uses **semantic-release** with Conventional Commits. On every push to `main`, CI checks if a new version should be published.

- Use Conventional Commits: `feat: ...`, `fix: ...`, `chore: ...`
- Breaking changes: use `!` or a `BREAKING CHANGE:` footer
- Build artifacts for Windows, Linux, and macOS are attached to GitHub Releases
- Portable single-file executables are published as `pylrcget-windows-portable.exe`, `pylrcget-linux-portable`, and `pylrcget-macos-portable`

### 🛡️ Windows note

Windows release builds are currently unsigned. SmartScreen may show a warning on newly downloaded builds — continue through `More info` → `Run anyway` if you trust the release source.

### 📦 In-app updates

The `About` dialog checks GitHub Releases for newer versions:

| Platform | Supported assets |
|----------|-----------------|
| Windows | `pylrcget-windows-installer.exe` (Inno Setup) |
| macOS | `.dmg`, `.pkg` |
| Linux | `.AppImage`, `.deb`, `.rpm` |

Portable single-file builds are also attached to releases for manual download. In-app automatic install continues to prefer platform installer assets when available.

Local feed testing is supported via `PYLRCGET_UPDATE_LATEST_URL` and `PYLRCGET_UPDATE_DEBUG` environment overrides.

---

## 🛠 Troubleshooting

- **SmartScreen warning on Windows** — See [Windows note](#️-windows-note) above.
- **No lyrics found** — Verify track metadata (title, artist) matches LRCLIB entries.
- **Playback not working for a format** — Check that the required codec is available on your system.
- **Update installer not launching** — Ensure you confirm the administrator/UAC prompt when it appears.

---

## 🤝 Contributing

PRs are welcome! Please:
- Keep commits small and conventional.
- Run `python -m pytest tests/` before submitting.

---

## 📄 License

MIT © saitatter

---

## 🙏 Credits

- Original idea and LRCLIB ecosystem: **tranxuanthang / LRCGET**
- This project is an independent desktop reimplementation, not a fork of the original codebase
