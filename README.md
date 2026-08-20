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
- AI-powered auto-sync: generate synced lyrics from audio using WhisperX (see [AI Auto-Sync](#-ai-auto-sync))
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

PyLrcGet can generate synced lyrics locally. English singing uses the optional
**lyrics-aligner** backend when configured; other detected languages, or an unavailable
lyrics-aligner installation, fall back to **WhisperX**. Everything runs on your machine —
no API keys or internet connection required (after initial model downloads).

The feature lives inside the track lyrics editor. Select a track, open the lyrics pane, and use **Auto Sync**. If the track has no lyrics yet, the empty lyrics state also exposes an **Auto Sync** action.

### How it works

1. WhisperX detects the audio language
2. For English, lyrics-aligner aligns the supplied lyrics phonetically; other languages use WhisperX word-level timestamps
3. If the optional English backend fails, WhisperX is used as a safe fallback
4. The result is placed in the synced lyrics editor as an unsaved draft

### Install AI dependencies

AI sync dependencies are **not** included in the base install. Install them separately:

```bash
pip install torch torchaudio whisperx soundfile
```

Or, if installing from `pyproject.toml`:

```bash
pip install pylrcget[ai]
```

### Optional English lyrics-aligner backend

Clone `schufo/lyrics-aligner`, install its model dependencies and download
`g2p-en`, then point PyLrcGet at that checkout:

```powershell
$env:PYLRCGET_LYRICS_ALIGNER_PATH = "C:\path\to\lyrics-aligner"
pip install g2p-en
```

The checkout must contain `align.py`, `model_parameters.pth`, and
`files\phoneme2idx.pickle`. The backend is used only when Whisper detects English.

> **Python compatibility:** the current WhisperX AI dependency set supports Python
> 3.10-3.13. Python 3.14 is not supported because its required `ctranslate2`
> version does not provide compatible wheels. Use a Python 3.13 virtual environment
> for AI Auto-Sync.

> **Note:** AI dependencies add ~2 GB to the install (mostly PyTorch). The `base` Whisper model (~140 MB) is downloaded automatically on first use. GPU acceleration (CUDA) is used when available, otherwise CPU.

> **Note:** base binary releases do not include AI dependencies by default.
> **Note:** AI-enabled portable builds are published for Windows and macOS. The Linux AI build is generated in CI but is too large for GitHub release assets, so it is not published there. All AI builds include the Python AI stack, but `ffmpeg` is still a system prerequisite for Whisper/WhisperX. The Linux `.deb` release declares `ffmpeg` as a package dependency so it is installed automatically on apt-based distros.

> **Tip for packaged users:** installing packages into system Python does not patch an already packaged executable.

> **UI note:** there is no separate AI screen. The AI entrypoint is the **Auto Sync** button in the lyrics editor.

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
python -m pip install torch torchaudio whisperx soundfile
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

To build an AI-enabled portable variant (larger, includes AI deps):

```bash
python -m pip install .[ai]
pyinstaller --noconfirm pylrcget-portable.spec
```

> **Note:** The app falls back to Qt Multimedia when `mpv` is unavailable, so packaged builds remain usable without an external `mpv` binary.

---

## 🔄 Releases

Uses **semantic-release** with Conventional Commits. On every push to `main`, CI checks if a new version should be published.

- Use Conventional Commits: `feat: ...`, `fix: ...`, `chore: ...`
- Breaking changes: use `!` or a `BREAKING CHANGE:` footer
- Build artifacts for Windows, Linux, and macOS are attached to GitHub Releases
- Shared Linux packaging assets live in `packaging/linux/` so future `.deb`/`.rpm`/AppImage packaging can reuse the same launcher metadata
- Installer assets are published for automatic update/install flows: `pylrcget-windows-installer.exe`, `pylrcget-linux.deb`, and `pylrcget-macos.pkg`
- The Linux `.deb` installs a desktop launcher (`pylrcget.desktop`) and app icon under the standard XDG locations
- The macOS `.pkg` installs `PyLrcGet.app` into `/Applications` and exposes a `pylrcget` launcher in `/usr/local/bin`
- Folder-based archives are published as `pylrcget-windows.zip`, `pylrcget-linux.tar.gz`, and `pylrcget-macos.tar.gz` (`PyLrcGet.app` inside the macOS archive)
- Portable single-file executables are also published as `pylrcget-windows-portable.exe`, `pylrcget-linux-portable`, and `pylrcget-macos-portable`
- AI-enabled portable builds are published as `pylrcget-windows-portable-ai.exe` and `pylrcget-macos-portable-ai`

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
- **Auto Sync says dependencies are missing** — If you run from source, install `pip install .[ai]` in that same environment. If you use the packaged `.exe`, AI dependencies must be present in the app's bundled Python runtime.
- **Using packaged `.exe` and want AI Auto Sync** — Download and run `pylrcget-windows-portable-ai.exe` (AI-enabled portable build).
- **App closes with `QThread: Destroyed while thread is still running` after Auto Sync** — update to the latest release; shutdown handling for AI sync workers was fixed.

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

If PyLrcGet is useful to you, you can support ongoing development on Ko-fi:

[![Support me on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/saitatter)
