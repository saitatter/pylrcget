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
- AI-powered auto-sync: generate synced lyrics from audio using Whisper + Demucs (see [AI Auto-Sync](#-ai-auto-sync))
- Configurable download modes: `Prefer synced`, `Synced only`, `Plain only`
- Bulk `Download missing lyrics` action based on the active download mode
- Per-selection download overrides from the track context menu
- Separate output format choices for sidecar files and embedded lyrics
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
- Configurable sidecar contents: synced and plain, synced only, plain only, or prefer synced with plain fallback
- Opt-in sidecar export (`.lrc` / `.txt`) with stale opposite-format cleanup
- Configurable embedded lyric contents using the same synced/plain/prefer-synced choices
- Opt-in embedding into supported audio formats

### 🎨 Desktop UI

- PySide6 / Qt desktop UI with multiple built-in themes
- Clickable artist / album navigation from the player bar and track list
- Native Windows file dialogs for better mapped-drive and network-share support
- Built-in log panel with live filtering, copy/save actions, and on-disk log files
- In-app update checker with release notes, download links, and installer launch support
- Light theme contrast tuned for readable disabled buttons and theme-aware icons

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
| **Lyrics** | Download mode, save lyrics files, file contents, embed lyrics, embedded contents, download directory, filename pattern with live preview, lyrics lookup subfolder, reaction delay, LRCLIB server URL |
| **Appearance** | Theme selection, UI scale (90–125%), font size (Small/Normal/Large), album art toggle, startup view |
| **Updates** | In-app version check, release notes preview, download/install actions |

---

## 🔄 Download Modes

| Mode | Behavior |
|------|----------|
| **Prefer synced, fallback to plain** | Treats tracks without synced lyrics as missing, then falls back to plain lyrics when synced lyrics are unavailable |
| **Synced only** | Downloads synced lyrics only and skips plain-only matches |
| **Plain only** | Downloads plain lyrics only, deriving plain text from synced lyrics by stripping timestamps when needed |

The track context menu supports temporary mode overrides for the current selection. The `Tracks` table color-codes lyric state: 🔴 No lyrics · 🟠 Plain · 🟢 Synced · 🔵 Instrumental.

The global `Download missing lyrics` action can also upgrade plain-only tracks to synced when synced lyrics become available on LRCLIB.

File export and embedded lyric format are controlled separately in Settings. For example, `Download mode` can prefer synced lyrics while `File contents` or `Embedded contents` decides whether to write synced lyrics, plain lyrics, both, or synced-with-plain-fallback.

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

## 🤖 AI Auto-Sync

PyLrcGet can generate synced lyrics locally using **OpenAI Whisper** for transcription and **Demucs** for vocal separation. Everything runs on your machine — no API keys or internet connection required (after initial model download).

The feature lives inside the track lyrics editor. Select a track, open the lyrics pane, and use **Auto Sync**. If the track has no lyrics yet, the empty lyrics state also exposes an **Auto Sync** action.

### How it works

1. **Demucs** isolates the vocal track from the audio (optional — falls back to the full mix if it is unavailable or fails)
2. **Whisper** transcribes the vocals with word-level timestamps
3. If plain lyrics are already present, they are aligned to the detected timestamps; otherwise Whisper's transcription is used directly
4. The result is placed in the synced lyrics editor as an unsaved draft

### Install AI dependencies

AI sync dependencies are **not** included in the base install. Install them separately:

```bash
pip install torch torchaudio openai-whisper demucs soundfile
```

Or, if installing from `pyproject.toml`:

```bash
pip install pylrcget[ai]
```

> **Note:** AI dependencies add ~2 GB to the install (mostly PyTorch). The `base` Whisper model (~140 MB) is downloaded automatically on first use. GPU acceleration (CUDA) is used when available, otherwise CPU.

> **Note:** AI dependencies are **not** bundled in binary releases. Users of standalone executables must install Python and the AI packages separately.

> **Tip for packaged `.exe` users:** install the AI packages into the same Python environment you use to launch PyLrcGet, then restart the app. The packaged app does not grow a separate AI screen; the AI entrypoint is the **Auto Sync** action in the lyrics editor.

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

To enable AI auto-sync (optional):

```bash
python -m pip install torch torchaudio openai-whisper demucs soundfile
```

### Build standalone app folder

```bash
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm pylrcget.spec
```

The generated app folder is placed in `dist/pylrcget/`.

To build the portable single-file variant:

```bash
pyinstaller --noconfirm pylrcget-portable.spec
```

> **Note:** The app falls back to Qt Multimedia when `mpv` is unavailable, so packaged builds remain usable without an external `mpv` binary.

---

## 🔄 Releases

Uses **semantic-release** with Conventional Commits. On every push to `main`, CI checks if a new version should be published.

- Use Conventional Commits: `feat: ...`, `fix: ...`, `chore: ...`
- Breaking changes: use `!` or a `BREAKING CHANGE:` footer
- Build artifacts for Windows, Linux, and macOS are attached to GitHub Releases
- Installer assets are published for automatic update/install flows: `pylrcget-windows-installer.exe`, `pylrcget-linux.deb`, and `pylrcget-macos.pkg`
- Folder-based archives are published as `pylrcget-windows.zip`, `pylrcget-linux.tar.gz`, and `pylrcget-macos.tar.gz`
- Portable single-file executables are also published as `pylrcget-windows-portable.exe`, `pylrcget-linux-portable`, and `pylrcget-macos-portable`

### 🛡️ Windows note

Windows release builds are currently unsigned. SmartScreen may show a warning on newly downloaded builds — continue through `More info` → `Run anyway` if you trust the release source.

### 📦 In-app updates

The `About` dialog checks GitHub Releases for newer versions:

| Platform | Supported assets |
|----------|-----------------|
| Windows | `pylrcget-windows-installer.exe` (Inno Setup) |
| macOS | `pylrcget-macos.pkg` |
| Linux | `pylrcget-linux.deb` |

Folder-based archives and portable single-file builds are also attached to releases for manual download. In-app automatic install continues to prefer platform installer assets when available.

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

---

## Support

If PyLrcGet is useful to you, you can support ongoing development on [Ko-fi](https://ko-fi.com/saitatter).
