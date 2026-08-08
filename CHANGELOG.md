# Changelog
## v1.14.0 (2026-08-08)

### ✨ Features
* Expand alpha index bar & bucketed pagination to tracks view and increase letter button size ([f30ad83](https://github.com/saitatter/pylrcget/commit/f30ad839d70fbe0a187d51e45dc980d5c8595029))
  - TrackListWidget: integrated AlphaIndexWidget with letter_prefix query support and get_track_letter_counts aggregation.
- AlphaIndexWidget: enlarged letter buttons (28x28px, 13px bold font) and improved sub-page pagination controls styling for better readability and touch/click targets.
- Preferences: propagated ignore_sort_articles setting to TrackListWidget.
* Add alphabetic index bar & bucketed pagination for artists, album artists and albums ([522e9db](https://github.com/saitatter/pylrcget/commit/522e9dba90da28f9d133f7e004b08fb0e457671a))
  - AlphaIndexWidget: reusable A-Z + '#' letter picker bar with page controls.
- DB queries: letter_prefix filtering and letter count aggregation functions for artists, album artists, and albums.
- Bucketed sub-pages: when a letter contains more entries than the page size, paginated controls ('1/3', '2/3', etc.) appear.
- Ignore articles option: added 'ignore_sort_articles' setting in Settings -> Library to ignore 'The', 'A', 'An' when sorting/indexing.
- DB migration: bumped database version to v6 for new config column.
* Add album artists tab (group by tpe2/albumartist) ([b81b5cb](https://github.com/saitatter/pylrcget/commit/b81b5cbf78f8aa492779ba37efb0d61e2019ce42))
  Adds a new 'Album Artists' navigation tab that groups the library by the album-level artist tag (TPE2 / ALBUMARTIST), distinct from the existing Artists tab which groups by the per-track artist tag (TPE1 / ARTIST).
  This matters especially for:
- Various Artists compilations (album artist = 'Various Artists', track
  artists are the individual performers)
- 'Main Artist feat. Featured Artist' tracks (album artist is the main
  artist, track artist includes the feature)
- Large libraries (68k+ tracks) where track-level artist grouping
  fragments albums across many entries
  Changes:
- db/query_modules/entity_queries.py: add get_album_artist_rows() and
  get_album_rows_by_album_artist() SQL queries grouped by album_artist_name
- ui/library_routes.py: new album_artists_* route factories and breadcrumbs
- ui/controllers/navigation_controller.py: album_artists tab routing
- ui/widgets/album_list_widget.py: setAlbumArtistScope() for text-based
  album filtering; _load_rows branches on album_artist_name scope
- ui/widgets/album_artist_list_widget.py: new top-level widget (artist
  table + AlbumListWidget drill-down)
- ui/main_window.py: tab registration, splitter, lyrics view, all signals
- main_window_parts/*: propagate album_artists_tab to dirty-lyrics, search,
  download state, now-playing, UI scale, and palette methods

### 🐛 Fixes
* Maintain database current_db_version at 5 ([a3e46ad](https://github.com/saitatter/pylrcget/commit/a3e46ad68ea94b68e5572f48da27fc5ea764cedc))
  Keep database version at 5 and backfill ignore_sort_articles column within v5 migration path, ensuring database version increments strictly per official release policy.
* **ai:** Don't pass string as vad_model in newer whisperx - let whisperx use built-in vad default ([27035db](https://github.com/saitatter/pylrcget/commit/27035dbadbf4fee78bd0ee595467a30667742d26))
* **ai:** Use vad_model instead of vad_method for newer whisperx; inspect load_model signature dynamically ([5082a38](https://github.com/saitatter/pylrcget/commit/5082a38912e89f0e86f0782e809b275db20e129b))
* **ai:** Add soundfile and torchaudio audio loading fallback for whisperx when ffmpeg is not in path ([1035667](https://github.com/saitatter/pylrcget/commit/103566780a02259ef92d7893362936502417e295))
* **build:** Add omegaconf, hydra, and antlr4 to pyinstaller specs for pyannote model unpickling ([36bf85d](https://github.com/saitatter/pylrcget/commit/36bf85da293aa4a8bbca377a3b98953e976caf9b))
* **ai:** Patch faster-whisper transcriptionoptions constructor for compatibility with newer faster-whisper versions ([140f342](https://github.com/saitatter/pylrcget/commit/140f342c59a63660f470c417fc3a9f12fbb876b5))
* **build:** Add copy_metadata for ai packages to support transformers and torchcodec in pyinstaller ([85e5bf9](https://github.com/saitatter/pylrcget/commit/85e5bf9454a9c467bea9674c4ed0e9b74c6e2c26))
* **build:** Include all whisperx dependencies (pandas, scipy, transformers, pyannote.audio) in pyinstaller specs ([f48f70d](https://github.com/saitatter/pylrcget/commit/f48f70d4ab62a3ad2a7c6a6e17641622448b71fe))
* **build:** Import collect_all in pyinstaller spec files to bundle ai packages properly ([6f8a82e](https://github.com/saitatter/pylrcget/commit/6f8a82e7a8afb33e779a01bb9dd24b20a73f2323))
* **lyrics:** Wire app_state to lyricseditorwidget so editor_auto_edit_on_add_line setting works ([8577d8c](https://github.com/saitatter/pylrcget/commit/8577d8cb199e4f91c103640234703495f4dc093e))
* **lyrics:** Allow row 0 with 0:00.00 to seek in synced lyrics, ignore 0:00.00 for subsequent rows ([a7ea8b5](https://github.com/saitatter/pylrcget/commit/a7ea8b524ae78f5656d93adc341982225ec1f811))
* **lyrics:** Do not seek player when clicking unsynced lyrics with timestamp 0:00.00 ([60d4f48](https://github.com/saitatter/pylrcget/commit/60d4f48012008662e3384e8a281e7842211ee140))
* **ui:** Enable drop-down arrow and selection signals for speedcombo dropdown ([2f8ebc2](https://github.com/saitatter/pylrcget/commit/2f8ebc263e131f8a866e5a3d3e3a841f47e15b46))
* **ui:** Use neutral svg chevron asset for qcombobox down-arrow ([e278846](https://github.com/saitatter/pylrcget/commit/e278846d0a18cc3920b76ed6aabb014aeda9efbd))
* **ui:** Dynamic svg file generation for qcombobox chevron and fix popup background contrast ([b0e2977](https://github.com/saitatter/pylrcget/commit/b0e2977346d243f62671adfb366785051902c819))
* **ui:** Dynamic base64 svg chevron icon and transparent qcombobox popup window frame ([ab6dd5d](https://github.com/saitatter/pylrcget/commit/ab6dd5db52ecf74807464b8839a8e0a30d2506cd))
* **ui:** Dynamic theme colors for combobox chevron and translucent popup window filter ([e9296b6](https://github.com/saitatter/pylrcget/commit/e9296b6d2138feb4e34db5bee236679633e916d6))
* **ui:** Use svg chevron icon and transparent popup container for qcombobox ([03f2e1a](https://github.com/saitatter/pylrcget/commit/03f2e1af565254caeaa26b9382a04c0e47befb3a))
* **ui:** Apply smooth rounded corners to qcombobox widgets and popup container frames ([7b2c014](https://github.com/saitatter/pylrcget/commit/7b2c014a56c7968416f28542293a0b0b64ce1deb))
* **ui:** Eliminate rectangular container bleed on qcombobox popup list views ([95d230c](https://github.com/saitatter/pylrcget/commit/95d230c1dde0b58a90ed10c69ada6eaf762b9d8c))
* **ui:** Refine qcombobox styling to remove rectangular drop-down background artifacts ([99406e0](https://github.com/saitatter/pylrcget/commit/99406e0f1d14c5492b6bb4cf72bb8fb7f13842f3))
* **ui:** Dynamically re-apply component stylesheets when theme changes ([af271dd](https://github.com/saitatter/pylrcget/commit/af271dd3f42236b9db0318b2d9fdf4c8f641ac3a))
* **ui:** Position empty state content directly under header buttons ([594fc73](https://github.com/saitatter/pylrcget/commit/594fc736b1c9fbecd06ed18d518c3c535ed1d620))
* **ui:** Center empty state content vertically in lyrics editor panel ([dc996c0](https://github.com/saitatter/pylrcget/commit/dc996c0d1c1e2e47648a90d2c39e93ad904000f1))
* **ui:** Align right lyrics editor header vertically with left scope bar ([ce54579](https://github.com/saitatter/pylrcget/commit/ce545799931e82032e9f0b8292622b5dad426bc4))
* **ui:** Clear track selection and reset editor when tracks are removed from library ([3b59e4a](https://github.com/saitatter/pylrcget/commit/3b59e4a7d6c79de2412ecfb74fa6906d27bcd568))
* **scanner:** Expand album artist tag parsing for mp3, m4a, flac, and wma ([7c39596](https://github.com/saitatter/pylrcget/commit/7c39596e8e70d661e1267a3e940eedcb9e8172e8))
* **packaging:** Collect whisperx submodules and datas in pyinstaller specs ([4a9fd84](https://github.com/saitatter/pylrcget/commit/4a9fd84aa8391d5fd448f49c0057898f4862bb73))

### ♻️ Refactors
* **ui:** Use pure qss subcontrol arrow for qcombobox down-arrow to eliminate file i/o ([ff619d7](https://github.com/saitatter/pylrcget/commit/ff619d7860a8ca384656197abadab4a9d98ebce4))

### 🧰 CI & Build
* **deps:** Bump the github-actions group across 1 directory with 2 updates ([095009e](https://github.com/saitatter/pylrcget/commit/095009efb76f51aeda27d8953db8ce3b2187c120))
  Bumps the github-actions group with 2 updates in the / directory: [python-semantic-release/python-semantic-release](https://github.com/python-semantic-release/python-semantic-release) and [actions/setup-python](https://github.com/actions/setup-python).
  Updates `python-semantic-release/python-semantic-release` from 10.6.0 to 10.6.1
- [Release notes](https://github.com/python-semantic-release/python-semantic-release/releases)
- [Changelog](https://github.com/python-semantic-release/python-semantic-release/blob/master/CHANGELOG.rst)
- [Commits](https://github.com/python-semantic-release/python-semantic-release/compare/v10.6.0...v10.6.1)
  Updates `actions/setup-python` from 6 to 7
- [Release notes](https://github.com/actions/setup-python/releases)
- [Commits](https://github.com/actions/setup-python/compare/v6...v7)
  ---
updated-dependencies:
- dependency-name: python-semantic-release/python-semantic-release dependency-version: 10.6.1
  dependency-type: direct:production
  update-type: version-update:semver-patch
  dependency-group: github-actions
  - dependency-name: actions/setup-python dependency-version: '7'
  update-type: version-update:semver-major
  dependency-group: github-actions ...
  Signed-off-by: dependabot[bot] <support@github.com>
  Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>
* **release:** 1.14.0 ([658a028](https://github.com/saitatter/pylrcget/commit/658a028ee653b05f8c0a922272e450400a2a4e17))

### 🔧 Other Changes
* **ui:** Optimize settings dialog load speed by removing blocking i/o ([967255d](https://github.com/saitatter/pylrcget/commit/967255d73f77588f899693d20fa32d1d70b6db5e))


## v1.13.1 (2026-07-06)

### 🐛 Fixes
* Package macos app bundle in release ([72866f4](https://github.com/saitatter/pylrcget/commit/72866f4142ce57d11d9fdf8f88d3b44f25de834f))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>


## v1.13.0 (2026-07-06)

### ✨ Features
* Improve export button and behavior ([c7952e4](https://github.com/saitatter/pylrcget/commit/c7952e4069fce1e34130081de41a32727d047644))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Improve macos packaging and updates ([b2ad430](https://github.com/saitatter/pylrcget/commit/b2ad430709bd48b24ccab7466bc942fc1c88e3d4))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Add configurable logging verbosity ([2ece6bc](https://github.com/saitatter/pylrcget/commit/2ece6bc1e9031f9be0be62f19a9d7e38cac38c18))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Add scan lyrics source mode ([2eb04ba](https://github.com/saitatter/pylrcget/commit/2eb04ba9629aefa6d2db352c6f67bfcebd3acb3f))
  Let library scans choose embedded-only, sidecar-only, or both sources, and persist the setting through config and migrations.
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Tune large library scan pipeline ([c2972d1](https://github.com/saitatter/pylrcget/commit/c2972d148687823caea7e889b5f510980dae8800))
* Reuse discovered audio signatures ([185a1cf](https://github.com/saitatter/pylrcget/commit/185a1cfe979a9b652c8da99deec5ff89006a0ff0))
* Speed up audio path discovery ([281d798](https://github.com/saitatter/pylrcget/commit/281d7982137a8bdd57560e2eaf2d8e614e783505))
* Cache discovered audio signatures ([83a8b36](https://github.com/saitatter/pylrcget/commit/83a8b36946b689988a12ee02e54ca16ee63c95ca))
* Cache sidecar lookup listings ([070722b](https://github.com/saitatter/pylrcget/commit/070722b3cb7112cc7dc619618d594a91f626f01f))
* Add audio-only scan fast path ([55d3a06](https://github.com/saitatter/pylrcget/commit/55d3a066b8aee1b1d8d25d770c5dfe4d165e6f1c))
* Break out scan signature timings ([6f1618e](https://github.com/saitatter/pylrcget/commit/6f1618efa2a9286059851fbc248d10e38738c451))
* Expand library scan timing logs ([52e3506](https://github.com/saitatter/pylrcget/commit/52e3506f70c4835135912baace4e3879480be70d))
* Add library scan timing instrumentation ([81b1045](https://github.com/saitatter/pylrcget/commit/81b1045b6901495e5a1c3439a7eea7e19a7f51f5))

### 🐛 Fixes
* Restore scan throughput log ([2abfec8](https://github.com/saitatter/pylrcget/commit/2abfec817eb540cd412c7ef034591afd75107727))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Clarify scan timing logs ([3bdd1d1](https://github.com/saitatter/pylrcget/commit/3bdd1d192ce09a3f1313d5ac9483597e1ef77f79))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Propagate scan lyrics source mode through library scan ([e6b7452](https://github.com/saitatter/pylrcget/commit/e6b745222c95bff1333f948191c56edecf832810))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Honor scan lyrics source mode in fallback signature lookup ([da688de](https://github.com/saitatter/pylrcget/commit/da688def4e5bda81856e85d12a285efc9ab2547f))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Keep database version at 5 ([f96dc40](https://github.com/saitatter/pylrcget/commit/f96dc40f01e97b7596c10420e2e7f5866ae45bee))
  Move the scan lyrics source mode column into the v5 upgrade path instead of introducing a new database version.
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Tolerate easyid3 during mp3 lyric scan ([06e7970](https://github.com/saitatter/pylrcget/commit/06e7970eeb9588f32e9c143bf7bd243ca0a5e1dc))
  Guard embedded-lyrics reads against EasyID3 objects and fall back to raw ID3 frames when needed.
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Keep lyrics export sidecar-only ([1b412f7](https://github.com/saitatter/pylrcget/commit/1b412f7d4b33e186dfbddb836467b69f8aba8f7d))
  Disable audio embedding for bulk and selected exports, and forward worker progress to the export overlay.
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Move bulk lyrics export off the gui thread ([46167d8](https://github.com/saitatter/pylrcget/commit/46167d8db88d8ef6755b52c3d7f549340c6dac5d))
  Add a cancellable export worker with progress and summaries, wire a Global Actions export button, and reuse the same worker for selected exports.
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Protect lyrics export semantics ([b76c8c0](https://github.com/saitatter/pylrcget/commit/b76c8c0fc16f121d491dbafb7102bb75f8bccf24))
  - preserve foreign MP3 USLT frames while managing our own lyrics tags
- make explicit sidecar export sidecar-only and atomic
- add regression coverage for write/read/export behavior
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* **release:** Skip oversized linux ai asset upload\n\nlinux ai portable exceeds github's 2gb asset limit, so keep building it as a\nworkflow artifact but skip publishing it as a release asset. update the readme\nto reflect the actual published ai portable set.\n\nco-authored-by: copilot <223556219+copilot@users.noreply.github.com> ([6d96c76](https://github.com/saitatter/pylrcget/commit/6d96c76db1b2788419d98a18b0003ccab03a2195))

### ♻️ Refactors
* Move lyrics outputs off ui thread ([22b8c60](https://github.com/saitatter/pylrcget/commit/22b8c605c0bd83a5d3b4e20981cf0bdd062fb93d))
  - add a controller and worker for lyrics output sync
- route save, propagate, and search flows through async output sync
- isolate instrumental maintenance into its own controller
- keep main window wrappers compatible for older call sites and tests
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Split refresh and light track queries ([cdf1d5b](https://github.com/saitatter/pylrcget/commit/cdf1d5b2a1acd4ed66b767ccd3982f3ec9848ba2))
  - move selected track refresh into a worker-backed library action
- add a lightweight track list query and accept summary rows in the renderer
- prefilter similar-lyrics candidates by normalized title and artist
- add regression coverage for the new query shapes and worker path
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

### 🧰 CI & Build
* **deps:** Bump python-semantic-release/python-semantic-release ([90c5ddc](https://github.com/saitatter/pylrcget/commit/90c5ddc66ec6a784fc6fea728fbf214c6ad716b5))
  Bumps the github-actions group with 1 update: [python-semantic-release/python-semantic-release](https://github.com/python-semantic-release/python-semantic-release).
  Updates `python-semantic-release/python-semantic-release` from 10.5.3 to 10.6.0
- [Release notes](https://github.com/python-semantic-release/python-semantic-release/releases)
- [Changelog](https://github.com/python-semantic-release/python-semantic-release/blob/master/CHANGELOG.rst)
- [Commits](https://github.com/python-semantic-release/python-semantic-release/compare/v10.5.3...v10.6.0)
  ---
updated-dependencies:
- dependency-name: python-semantic-release/python-semantic-release dependency-version: 10.6.0
  dependency-type: direct:production
  update-type: version-update:semver-minor
  dependency-group: github-actions ...
  Signed-off-by: dependabot[bot] <support@github.com>

### 📚 Docs
* Update ai sync readme for whisperx\n\nremove outdated demucs references and describe the current whisperx-based\nai sync workflow and install instructions.\n\nco-authored-by: copilot <223556219+copilot@users.noreply.github.com> ([87a6c89](https://github.com/saitatter/pylrcget/commit/87a6c890f648298bd8f35e8716532030100fcc40))

### 🔧 Other Changes
* Reduce first scan i/o ([ec092a1](https://github.com/saitatter/pylrcget/commit/ec092a1312dc98ce4ee8d22f8a5c5ce0f4ba1c83))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>


## v1.12.0 (2026-07-01)

### ✨ Features
* **release:** Add ai portable assets for linux and macos\n\nbuild ai-enabled portable variants for windows, linux, and macos, and\nupdate the release notes to describe the remaining ffmpeg prerequisite.\n\nco-authored-by: copilot <223556219+copilot@users.noreply.github.com> ([c81966b](https://github.com/saitatter/pylrcget/commit/c81966bafe3cc7beadeaf3b2a3ecccd6530421bd))
* **ai-sync:** Multi-onset relaxed vad with vocab-weighted selection ([1a5bba3](https://github.com/saitatter/pylrcget/commit/1a5bba3e687152ba859101f89079dc67ec68aa93))
  Run three relaxed VAD onsets (0.15/0.10/0.02) when the coverage retry gate fires and keep the best candidate by alignment quality. Raise the vocab_ratio weight in the quality proxy so an over-detecting aggressive onset (diluted with out-of-vocabulary instrumental noise) is rejected while an aggressive onset that recovers genuine softly-sung lyrics is accepted.
  Positional mean-of-means across the 5-track suite improves 9.78s -> 7.32s; See You in Hell (acoustic) worst case 15.87s -> 9.70s with no regressions.
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* **ai-sync:** Persist settings, staged progress, and alignment hardening ([9588fde](https://github.com/saitatter/pylrcget/commit/9588fdea79273e732d403d4b3ab57536ac777c0a))
  - Persist AI Sync execution device and transcription language across runs
  - Report staged progress (load/transcribe/align/select/build) to the UI
  - Cache WhisperX + alignment models; add relaxed-VAD retry and pass selection
  - Add tail-rescue for late repeated lines collapsing onto earlier clusters
  - Document detection/alignment methods (AI_SYNC_WORKER_METHODS.md) and add tests
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* Harden ai sync alignment and document scoring pipeline ([55b413d](https://github.com/saitatter/pylrcget/commit/55b413dc849fdd2ca2d55e4becac4cc965dd6134))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* **ai-sync:** Add repeat-aware transition penalty for rewind collapse ([4bb99b5](https://github.com/saitatter/pylrcget/commit/4bb99b5ee479b25203ebc1e6ed519b68e5cd20ea))
  Introduce a transition-level penalty for duplicate phrases that remain in an earlier repeated cluster across consecutive lines.
  This reduces repeat-block collapse on hard tracks while keeping runtime stable.
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* **ai-sync:** Penalize same-phrase rewind in viterbi alignment ([83851a8](https://github.com/saitatter/pylrcget/commit/83851a861997e72181f489527a5ab76f03506ccf))
  Add an explicit rewind penalty for duplicated lyric phrases so later occurrences are less likely to snap to earlier temporal clusters.
  This improves repeat-heavy tracks while keeping alignment/runtime stable.
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* **ai-sync:** Implement viterbi dp for global alignment optimization ([9633c5a](https://github.com/saitatter/pylrcget/commit/9633c5ae95be070180b9123a7b134de76f057ac1))
  - Replace greedy local matching with Viterbi dynamic programming
- Global optimization finds globally optimal alignment path, not greedy left-to-right
- Reduces systematic drift by considering full lyric context
- Emission scoring: word overlap detection with sequence matching
- Transition costs: penalize backwards movement and large jumps
- Fallback to greedy if Viterbi fails (safety mechanism)
- Expected improvement: 50s error -> 5-10s error on well-transcribed audio
  Algorithm: O(n_lines × n_words × window_size) ≈ 60 × 500 × 100 = 3M ops (tractable)
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

### 🐛 Fixes
* **ui:** Polish lyrics editor navigation and autofix\n\ntrim and capitalize lines during autofix, stop unsynced zero-timestamp clicks\nfrom seeking to the start, make up/down move lyric selection from toolbar and\nseekbar focus, and stop add/delete from causing lyric-view scroll jumps.\n\nco-authored-by: copilot <223556219+copilot@users.noreply.github.com> ([f8c2ea3](https://github.com/saitatter/pylrcget/commit/f8c2ea3328f819d1cdef7f3b524c7ab13f13d885))
* **packaging:** Add linux launcher assets and ffmpeg dep\n\nadd shared linux desktop-entry and icon assets, install them from the .deb\nworkflow, and declare ffmpeg as a package dependency so whisper/whisperx\ncan decode audio on apt-based distros without extra manual setup.\n\nco-authored-by: copilot <223556219+copilot@users.noreply.github.com> ([58e0830](https://github.com/saitatter/pylrcget/commit/58e08303457a5620a1eb5e9ed2ceda44fc10a6e7))
* **ai-sync:** Add cpu fallback for alignment on cuda errors ([5d8621e](https://github.com/saitatter/pylrcget/commit/5d8621eac473c5fc0f87d0da40cf4bb47d6a1cd8))
  WhisperX alignment with Pyannote VAD can hang on Windows when using CUDA (Triton kernel initialization issue). Add try/except with automatic CPU fallback.
  Also fixes edge case where alignment fails silently - now logs warnings and continues with raw segment timestamps.

### 🧰 CI & Build
* Remove tools from repository tracking ([4a557fd](https://github.com/saitatter/pylrcget/commit/4a557fd2d9923cac3dd77bb64f76dae6cd993901))
  - keep tools/ ignored via .gitignore
- remove tracked tools scripts and benchmark artifacts
- keep AI sync on global anchors variant
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>


## v1.11.0 (2026-06-22)

### ✨ Features
* **ai-sync:** Replace whisper with whisperx and add cuda device toggle ([cecf900](https://github.com/saitatter/pylrcget/commit/cecf9008b1762526685a863da8ee95789518bb85))
  - Replace Whisper base model with WhisperX for consistent forced alignment
- Remove vocal separation (Demucs) integration entirely
- Add GPU (CUDA) device option in settings (Auto/CPU/GPU)
- WhisperX provides better word-level timestamp accuracy via forced alignment
- Benchmark results: ~24% faster (6.1s -> 4.7s), equivalent accuracy (49.4s error)
- Device selection is now configurable: auto-detect, CPU-only, or CUDA
- Remove use_vocal_separation parameter from worker instantiation
- Update dependencies: whisperx replaces openai-whisper
  Measurements from investigation 5 (WhisperX vs Whisper base):
- Load time: WhisperX faster on longer tracks (-27% to -55%)
- Transcribe: WhisperX -24% faster on average (-43% to -74%)
- Alignment accuracy: equivalent (49.4s vs 49.4s mean error)
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* **ai-sync:** Remove demucs vocal separation - degraded alignment accuracy ([825f67d](https://github.com/saitatter/pylrcget/commit/825f67de4972f401d34ba71dd7b2b4bf13b31637))
  Investigation results (4 benchmarks on 5 test tracks):
  1. Demucs vocal separation reduced alignment accuracy by ~20% on average
   - Full mix baseline: 48.2s mean error
   - Separated vocals: 47.5s (-1.4%, inconsistent improvement)
   - Latency compensation: Made it worse (-8.2%)
  2. Latency analysis showed variable delay (+67s to -0.3s) per track
   - No fixed latency to compensate
   - Compensation attempts made results worse (-14.7% average)
  3. Whisper large-v3 model (CUDA) showed no consistent improvement
   - Average -5.4% vs base model
   - 30+ second load time not justified
   - Kept base model as default
  Decision: Simplify to greedy baseline
- Remove Demucs from optional dependencies
- Use full audio mix (no vocal separation)
- Faster processing, more predictable results
- Keep greedy alignment as stable workhorse
  Remaining improvements for future investigation:
- Confidence-based word filtering (helps some songs, hurts others)
- Segment boundary edge cases
- Post-processing smoothing refinements
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* **ai-sync:** Add postprocessing smoothing for aligned timestamps; apply same postprocess in benchmark ([c0fe9ac](https://github.com/saitatter/pylrcget/commit/c0fe9ac47b94f59d3c914211c958708736ed7137))
* **ai-sync:** Add fuzzy matching support and ui settings for ai auto-sync\n\nadd configurable fuzzy matching (rapidfuzz) to improve alignment robustness. expose enable_fuzzy and fuzzy_threshold in ai sync settings and pass settings to the worker.\n\nco-authored-by: copilot <223556219+copilot@users.noreply.github.com> ([b644141](https://github.com/saitatter/pylrcget/commit/b64414161c5b5f87e6e1b4e27ed4818221e5ba5b))
* **ai:** Add guided packaged flow and ai-enabled portable release ([d5bc85a](https://github.com/saitatter/pylrcget/commit/d5bc85af7340d6c1625f6ba28e4de2f28ce9065d))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

### 🐛 Fixes
* **ui:** Avoid ai sync settings layout break; add watchdog for long 'building lrc' progress ([637691c](https://github.com/saitatter/pylrcget/commit/637691c60b07addc48087f209568232f37706b5f))


## v1.10.1 (2026-06-22)

### 🐛 Fixes
* **ai-sync:** Harden worker shutdown and dependency guidance ([142d2ba](https://github.com/saitatter/pylrcget/commit/142d2ba7945664fce5dbb5aaa17df7bc3d911cc8))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* **lrclib:** Send instrumental flag on publish ([46e6b70](https://github.com/saitatter/pylrcget/commit/46e6b706cb97f21cb3b43de7019ea984305fcd42))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
* **settings:** Persist empty lyrics filename pattern ([47221c1](https://github.com/saitatter/pylrcget/commit/47221c1b17a20c0144a333db229cf430c7194ec0))
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

### 🧰 CI & Build
* **deps:** Bump actions/checkout in the github-actions group ([d366e8f](https://github.com/saitatter/pylrcget/commit/d366e8f966436bd1ca65d8832e387547d59b294a))
  Bumps the github-actions group with 1 update: [actions/checkout](https://github.com/actions/checkout).
  Updates `actions/checkout` from 6 to 7
- [Release notes](https://github.com/actions/checkout/releases)
- [Changelog](https://github.com/actions/checkout/blob/main/CHANGELOG.md)
- [Commits](https://github.com/actions/checkout/compare/v6...v7)
  ---
updated-dependencies:
- dependency-name: actions/checkout dependency-version: '7'
  dependency-type: direct:production
  update-type: version-update:semver-major
  dependency-group: github-actions ...
  Signed-off-by: dependabot[bot] <support@github.com>
* Add copilot instructions ([b5adcab](https://github.com/saitatter/pylrcget/commit/b5adcab3e195ab82cbe3c7591fbd7e6949713b36))

### 📚 Docs
* Add ko-fi support badge ([0ff0c5f](https://github.com/saitatter/pylrcget/commit/0ff0c5f4f6ac7df668677205e2369a589bb064d0))
* Add ko-fi support footer ([6ec470c](https://github.com/saitatter/pylrcget/commit/6ec470c31344d06f09f5ffa2367618fb56899ded))


## v1.10.0 (2026-05-23)

### ✨ Features
* Streamline settings and selection actions ([bfaf60c](https://github.com/saitatter/pylrcget/commit/bfaf60cf0e5a52a1176e0b15bdb558b8ec89ddc5))
* Improve ai auto-sync workflow ([17b0d34](https://github.com/saitatter/pylrcget/commit/17b0d34c4d1c6de98fe21b5330dabb7ae95203cf))
* Persist ui state and customizable shortcuts ([ae4945b](https://github.com/saitatter/pylrcget/commit/ae4945b7653e5230d14721b59d9b34f7fab40f3f))

### 🐛 Fixes
* Refresh lyrics layout on tab change ([419133f](https://github.com/saitatter/pylrcget/commit/419133f018d63b9c5c662655af4e392d6d29d643))
* Prevent clipped lyrics toolbar on tab switch ([881f2ce](https://github.com/saitatter/pylrcget/commit/881f2ce83a117756b77d9819c5a311c54ef26b08))
* Sync library splitter sizes ([773bc79](https://github.com/saitatter/pylrcget/commit/773bc79781551e83654e799d48ea469a073d9970))
* Normalize startup window sizing ([ef44bdf](https://github.com/saitatter/pylrcget/commit/ef44bdfb03ab778104b93213bd9a67ef371ce406))
* Stabilize startup window defaults ([d47331c](https://github.com/saitatter/pylrcget/commit/d47331c86a1dc5901ccdffe16c60586039c04529))
* Avoid narrow startup window restore ([c8cf5e7](https://github.com/saitatter/pylrcget/commit/c8cf5e7f49393ead246bcf9a9e75306d2ffab1ac))
* Avoid clipping wrapped lyrics toolbar ([7c6793b](https://github.com/saitatter/pylrcget/commit/7c6793b087a143204ca45c83adf70d78f791c18a))
* Wrap empty state actions ([98b7d70](https://github.com/saitatter/pylrcget/commit/98b7d70d2a5fa73827a9872acca8437f1b838749))
* Simplify selection action menus ([2c2665a](https://github.com/saitatter/pylrcget/commit/2c2665a55ec7aa2b19a56f3b66b28dd2b9c959ee))
* Restore startup appearance hooks ([03f65f3](https://github.com/saitatter/pylrcget/commit/03f65f39fe4c5d94e494324778f06304a75d1eda))

### ♻️ Refactors
* Modularize query and main window helpers ([abcff41](https://github.com/saitatter/pylrcget/commit/abcff41be860ea96c2505a2deb5b1f723fe86634))

### 🧰 CI & Build
* Run tests with pytest ([cdd3744](https://github.com/saitatter/pylrcget/commit/cdd37444b6c98fb70392db6098940fabb7b71b31))

### 🧪 Tests
* Organize top-level test suites ([2e1a770](https://github.com/saitatter/pylrcget/commit/2e1a770d8e3c9985971f55b14db94a513b695e39))
* Reorganize widget navigation suites ([e506877](https://github.com/saitatter/pylrcget/commit/e5068773295a9a3ae1c2016e0ab8d114538a1ac5))


## v1.9.0 (2026-05-11)

### ✨ Features
* Improve lyrics editor validation ux ([15b2895](https://github.com/saitatter/pylrcget/commit/15b28952855318dfbb54ceb1f031f50d68199ce7))
  Improve synced lyrics validation and editor UX.
  - Detect duplicate timestamps and make them autofixable
- Add row-level validation tooltips and click-to-jump validation hints
- Add right-side line numbers and a validation status badge
- Disable publish actions for invalid lyrics or unsaved drafts
- Normalize compact header button and badge styling


## v1.8.0 (2026-05-10)

### ✨ Features
* Add lyric diff to sync dialog ([de8215f](https://github.com/saitatter/pylrcget/commit/de8215f5f1cd7be076bcdb63be9d3078ebdaebda))
* Sync lyrics to similar tracks ([4aa2666](https://github.com/saitatter/pylrcget/commit/4aa26660a883d40927a29a2cd927480333e40d29))

### 🐛 Fixes
* Match sync dialog table styling ([ad157a2](https://github.com/saitatter/pylrcget/commit/ad157a27dbc9e073d0d1bd0fc0cf283f94571b27))
* Improve selected sync diff button contrast ([200dea7](https://github.com/saitatter/pylrcget/commit/200dea70e3d20f0e32d1060c533ddff39efe6c6c))
* Render sync diff action with delegate ([0ad29b6](https://github.com/saitatter/pylrcget/commit/0ad29b6385dfc4a3fb842039729770fdadb6729a))
* Center diff button in sync table ([115d267](https://github.com/saitatter/pylrcget/commit/115d267695f61e52727c30c0754901b8a89147ca))
* Polish sync dialog diff action ([1cdffc0](https://github.com/saitatter/pylrcget/commit/1cdffc040023558d4e1b308be1bd4528134c2938))
* Require exact metadata for lyric sync matches ([5bea010](https://github.com/saitatter/pylrcget/commit/5bea010b0185abf08125f5bcce3f1572a4492439))


## v1.7.0 (2026-05-10)

### ✨ Features
* Add easier synced lyric line insertion ([b6af4ae](https://github.com/saitatter/pylrcget/commit/b6af4ae78ade7b1908f4521279ecf90c24457bb0))
* Show sortable track numbers in library ([5f84620](https://github.com/saitatter/pylrcget/commit/5f846206a886326d7ba2afe22128897d9a1d5ee7))

### 🐛 Fixes
* Scope enter playback shortcut to track lists ([048d7a9](https://github.com/saitatter/pylrcget/commit/048d7a9cdc68541877b6b3dad238d57414f42d3e))
* Reset download success state ([9c73dae](https://github.com/saitatter/pylrcget/commit/9c73dae43eb551fbd130997bd6e88e07ee304243))
* Add synced lyrics editor context menu ([ff99a04](https://github.com/saitatter/pylrcget/commit/ff99a049608cd3a0ee286ea9f1d690dd0dc4b5a1))
* Improve player cover alignment ([3cfe5f6](https://github.com/saitatter/pylrcget/commit/3cfe5f6c7d63103abd32d9e220cdec0ff95ec8dc))


## v1.6.0 (2026-05-10)

### ✨ Features
* Configure lyrics file and embed output formats ([64b986f](https://github.com/saitatter/pylrcget/commit/64b986f0d8409f4d5c9704a54ee25500c6251630))

### 🐛 Fixes
* Improve light theme button contrast ([447740e](https://github.com/saitatter/pylrcget/commit/447740e3b4d6ebe5aa0c160c22e6c8d27c806ea3))
* Reposition hotkey badges after log panel toggle ([61f4bf3](https://github.com/saitatter/pylrcget/commit/61f4bf3361ca88a42eed7ceca12983c3dfe10f5e))
* Clarify lyrics download settings layout ([71fccb0](https://github.com/saitatter/pylrcget/commit/71fccb0bcdcdcd6ce55b74ee8103d169b029891c))
* Retry publish requests on network timeouts ([a420d32](https://github.com/saitatter/pylrcget/commit/a420d3224ad33e747978ef0d98c48cf39014b9db))

### 🧰 CI & Build
* **deps:** Bump the github-actions group with 4 updates ([dc174cc](https://github.com/saitatter/pylrcget/commit/dc174ccbbbf457c1cabbc3e69125c8c09312e2d9))
  Bumps the github-actions group with 4 updates: [amannn/action-semantic-pull-request](https://github.com/amannn/action-semantic-pull-request), [actions/checkout](https://github.com/actions/checkout), [actions/setup-python](https://github.com/actions/setup-python) and [actions/upload-artifact](https://github.com/actions/upload-artifact).
  Updates `amannn/action-semantic-pull-request` from 5 to 6
- [Release notes](https://github.com/amannn/action-semantic-pull-request/releases)
- [Changelog](https://github.com/amannn/action-semantic-pull-request/blob/main/CHANGELOG.md)
- [Commits](https://github.com/amannn/action-semantic-pull-request/compare/v5...v6)
  Updates `actions/checkout` from 4 to 6
- [Release notes](https://github.com/actions/checkout/releases)
- [Changelog](https://github.com/actions/checkout/blob/main/CHANGELOG.md)
- [Commits](https://github.com/actions/checkout/compare/v4...v6)
  Updates `actions/setup-python` from 5 to 6
- [Release notes](https://github.com/actions/setup-python/releases)
- [Commits](https://github.com/actions/setup-python/compare/v5...v6)
  Updates `actions/upload-artifact` from 4 to 7
- [Release notes](https://github.com/actions/upload-artifact/releases)
- [Commits](https://github.com/actions/upload-artifact/compare/v4...v7)
  ---
updated-dependencies:
- dependency-name: amannn/action-semantic-pull-request dependency-version: '6'
  dependency-type: direct:production
  update-type: version-update:semver-major
  dependency-group: github-actions
  - dependency-name: actions/checkout dependency-version: '6'
  - dependency-name: actions/setup-python dependency-version: '6'
  - dependency-name: actions/upload-artifact dependency-version: '7'
  dependency-group: github-actions ...
  Signed-off-by: dependabot[bot] <support@github.com>
  Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>
* Restore release metadata after accidental dependabot release ([c504fcc](https://github.com/saitatter/pylrcget/commit/c504fcc9cc36a324f4c185c841e1fe2d6861cab5))
* Make release workflow manual ([fcda2ed](https://github.com/saitatter/pylrcget/commit/fcda2ed5592c37e142b28ccb56ead10ba40af00f))
* Add dependabot updates ([e971215](https://github.com/saitatter/pylrcget/commit/e971215a7fe2216d106edd8478c3ba7ee1c3fbcc))

### 📚 Docs
* Update feature and release documentation ([3bbf48d](https://github.com/saitatter/pylrcget/commit/3bbf48dc1a855c18b3a6c4f6cf81b8f9055a66bb))

### 🧪 Tests
* Cover lyrics embedding formats ([be45daa](https://github.com/saitatter/pylrcget/commit/be45daa29977639deef81737ee3d0c5969711e43))


## v1.5.0 (2026-05-06)

### ✨ Features
* Improve player controls and library scans ([f10e70f](https://github.com/saitatter/pylrcget/commit/f10e70fa862e6aa0aed474bed1cba7a621670f8f))
* Add lyrics validation autofix ([f10e70f](https://github.com/saitatter/pylrcget/commit/f10e70fa862e6aa0aed474bed1cba7a621670f8f))
* Show library scan progress overlay ([f10e70f](https://github.com/saitatter/pylrcget/commit/f10e70fa862e6aa0aed474bed1cba7a621670f8f))

### 🐛 Fixes
* Refine player and overlay ux ([f10e70f](https://github.com/saitatter/pylrcget/commit/f10e70fa862e6aa0aed474bed1cba7a621670f8f))
* Refine track action hover states ([f10e70f](https://github.com/saitatter/pylrcget/commit/f10e70fa862e6aa0aed474bed1cba7a621670f8f))
* Refine speed control alignment ([f10e70f](https://github.com/saitatter/pylrcget/commit/f10e70fa862e6aa0aed474bed1cba7a621670f8f))
* Align player volume controls ([f10e70f](https://github.com/saitatter/pylrcget/commit/f10e70fa862e6aa0aed474bed1cba7a621670f8f))
* Blend track action buttons on selection ([f10e70f](https://github.com/saitatter/pylrcget/commit/f10e70fa862e6aa0aed474bed1cba7a621670f8f))
* Keep track action hover isolated ([f10e70f](https://github.com/saitatter/pylrcget/commit/f10e70fa862e6aa0aed474bed1cba7a621670f8f))
* Unify status and toast overlays ([f10e70f](https://github.com/saitatter/pylrcget/commit/f10e70fa862e6aa0aed474bed1cba7a621670f8f))


## v1.4.0 (2026-05-01)

### ✨ Features
* **lyrics:** Improve download and sidecar workflows ([4034293](https://github.com/saitatter/pylrcget/commit/403429397f715fa8290f7e91b2a5363650922177))
* **lyrics:** Import lyric files as drafts ([4034293](https://github.com/saitatter/pylrcget/commit/403429397f715fa8290f7e91b2a5363650922177))
* **ui:** Polish navigation and history controls ([4034293](https://github.com/saitatter/pylrcget/commit/403429397f715fa8290f7e91b2a5363650922177))

### 🐛 Fixes
* **lyrics:** Save only selected download format ([4034293](https://github.com/saitatter/pylrcget/commit/403429397f715fa8290f7e91b2a5363650922177))
* **scanner:** Detect metadata-named lrc sidecars ([4034293](https://github.com/saitatter/pylrcget/commit/403429397f715fa8290f7e91b2a5363650922177))
* **scanner:** Avoid duplicate metadata reads ([4034293](https://github.com/saitatter/pylrcget/commit/403429397f715fa8290f7e91b2a5363650922177))
* **ui:** Keep download tooltip out of status bar ([4034293](https://github.com/saitatter/pylrcget/commit/403429397f715fa8290f7e91b2a5363650922177))
* **lyrics:** Address review regressions ([4034293](https://github.com/saitatter/pylrcget/commit/403429397f715fa8290f7e91b2a5363650922177))

### ♻️ Refactors
* **ui:** Simplify review cleanup paths ([4034293](https://github.com/saitatter/pylrcget/commit/403429397f715fa8290f7e91b2a5363650922177))


## v1.3.0 (2026-04-27)

### ✨ Features
* Lyrics draft management, editor mode toggle, and drag-and-drop file import ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  * Add open containing folder action
  * Move selection actions to toolbar
  * Add dirty lyrics drafts and track preview
* Add discard draft button and unsaved filter ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  - Fix false 'Unsaved draft' badge by blocking table signals during row style refresh
- Feed back correct dirty state from main window handler to editor badge
- Add 'Discard' button next to the unsaved draft badge to revert to saved lyrics
- Add 'Unsaved' filter checkbox in top bar to show only tracks with dirty drafts
- When 'Unsaved' filter is active, lyrics type filters are bypassed
* Add synced/plain editor mode toggle ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  - Add 'Switch to Synced' / 'Switch to Plain' button in lyrics editor title bar
- Plain to Synced: converts text lines into timestamped rows at [00:00.00]
- Synced to Plain: extracts text from table, discarding timestamps
- Button hidden on empty state / instrumental tracks
* Support drag-and-drop of individual audio files ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  - Extend drag-and-drop to accept audio files in addition to folders
- Import dropped files directly into library with metadata extraction
- Skip files already present in the database
- Support all audio formats: mp3, m4a, flac, ogg, opus, wav, wma, etc.
* Add ai auto-sync with whisper + demucs ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  - Add AiSyncWorker using openai-whisper for transcription with word timestamps
- Add Demucs vocal separation for improved accuracy
- Use soundfile for audio I/O (no ffmpeg dependency)
- Align existing plain lyrics to detected timestamps when available
- Add Auto Sync button to lyrics editor (hidden when AI deps missing)
- Add optional [ai] extras group in pyproject.toml
- Update README with AI Auto-Sync section and install instructions
* Load ai sync result as dirty draft instead of saving directly ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  AI-synced lyrics are now stored as dirty draft (update_track_dirty_lyrics) so the user can review and manually save. Shows '(loaded as draft)' message.
* Escape key clears search box and returns focus ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  When the search box is focused, pressing Escape clears its text and returns focus to the main content area.
* Show toast notification when lyrics are saved ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Adds a success toast on Ctrl+S save in addition to the existing status bar message for better visibility.
* Add mute toggle button to player bar ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Replace the Volume text label with a clickable speaker icon that toggles mute/unmute. Remembers the previous volume level when unmuting. Icon changes to show muted state.
  * Translate all Romanian comments and docstrings to English
  * Fix WHERE 1 anti-pattern in set_init and set_config queries
  * Extract magic numbers to ui/constants.py
  * Fix player EOF race condition with threading lock
  * Reject zero/negative duration tracks before LRCLIB request
  * Add logging to mutagen embed operations
  * Add duplicate track detection with visual indicator
  * Add LRCLIB search history with recent queries in search dialog
  * Add lyrics diff viewer dialog for saved vs. draft comparison
  * Fix PlayerBar crash: move lbl_volume icon assignment after widget creation
  * Fix on_refresh_tracks: continue on error instead of aborting batch
  * Skip test_lrclib_client under unittest discover when pytest is missing
  * Address Gemini review: log fallback embed errors, fix tooltip, add MPS support, preserve timestamps in editor toggle
  * Fix dirty badge comparison, restore smart apostrophe regex, fix config cache race
  * Fix QApplication import in toggle_play_pause, make Config frozen
  * Add title_lower index to migration, batch dropped file imports via add_tracks
  * Use QAbstractSpinBox in focus check, add soundfile/torchaudio to AI sync dep check
  * Cache saved lyrics baseline to avoid DB query on every dirty flush
  * Move file-path query to queries.py, add AI sync cancellation checks

### 🐛 Fixes
* Address code review feedback ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  - Batch commit dropped files instead of per-file commits
- Debounce dirty lyrics DB writes with 500ms QTimer
- Flush pending draft on track switch and app close
- Use CURRENT_DB_VERSION constant in migrations instead of hardcoded value
* Escape sql like wildcards in search queries ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Add _escape_like helper to prevent % and _ in user search input from acting as SQL LIKE metacharacters. Applied to get_artist_rows, get_album_rows, and get_track_rows.
* Prevent path traversal in lyrics sidecar export ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  - Reject '..' as a safe component in _safe_component
- Add is_relative_to check in _resolve_output_base to prevent
  traversal outside configured output directory
* Add unique constraint on tracks.file_path and index on dirty_lyrics_present ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  - Add UNIQUE on tracks.file_path to prevent duplicate track entries
- Add index on dirty_lyrics_present for unsaved draft filter queries
- Migration v2->v3: deduplicates existing rows, upgrades index
- Refactor migration to use sequential version checks instead of if/return
* Skip space play/pause shortcut when text input has focus ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Check if focus is on QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, or QComboBox before triggering play/pause toggle.
* Use theme tokens for lyrics editor row colors ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Replace hardcoded hex colors in _refresh_row_styles with STYLE_TOKENS lookups so colors adapt to the active theme.
* Notify user when player backend fails to initialize ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Log warning and show user notification when mpv backend is unavailable.
* Add threading lock to _config_cache ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Protect global _config_cache with threading.Lock to prevent race conditions when accessed from multiple threads (UI, download workers, player).
* Cancel all workers on application close ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Cancel download controller workers and library scanner in closeEvent, not just the AI sync worker. Request interruption before waiting.
* Validate sort_column against whitelist in query functions ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Replace dict.get fallback with explicit whitelist check to ensure sort_column is always a known valid key before SQL interpolation.
* Clean up temp file if sf.write fails in _separate_vocals ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  If writing the vocals WAV fails after temp file creation, the file would leak. Now caught and unlinked before re-raising.
* Wrap embed_lyrics fallback in try/except ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  The generic mutagen fallback could raise for unsupported formats. Silently ignore errors since this is a best-effort path.
* Surface sidecar/embed errors via notify callback ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  sync_track_outputs now reports sidecar and embed failures through the progress callback so the user sees warnings in the UI.
* Reject timestamps with seconds >= 60 in parse_ts_str ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Previously '01:75.00' was accepted as valid. Now returns None for out-of-range seconds values.

### ♻️ Refactors
* Move lrc parsing functions to core/utils ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Move parse_lrc, ms_to_ts, parse_ts_str, and _ts_to_ms from lyrics_editor_widget to core/utils for reuse across modules.
* Extract _read_vorbis_lyrics helper in scan_library ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Deduplicate FLAC/OGG/OPUS lyrics reading into a single helper.
* Extract _wire_lyrics_view helper for signal wiring ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Deduplicate repeated signal.connect calls for all 3 lyrics editor views into a single _wire_lyrics_view method.
* Use threading.event for coordinated nonce search shutdown ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Replace polling on result[0] with Event.is_set() for immediate thread exit once a nonce is found. Avoids busy-wait teardown.
* Remove unused get_artists, get_albums, clean_library ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  These functions were defined but never imported or called anywhere. Also removes the now-unused Album and Artist imports.
* Remove unused trackrow and trackfilters dataclasses ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  These classes in core/models.py were never imported or used.
* Replace typing.optional/list/tuple with native syntax ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  All files already use 'from __future__ import annotations', so Optional[X] -> X | None, List[X] -> list[X], Tuple[X] -> tuple[X]. Remove unnecessary typing imports from 11 files.
* Deduplicate lrc timestamp regex ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Export LRC_TS_RE from core/utils.py and reuse it in lyrics_editor_widget.py instead of defining an identical regex.

### 📚 Docs
* Update readme with new features ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  - Add synced/plain editor toggle, draft management, unsaved filter
- Add drag-and-drop audio files support

### 🧪 Tests
* Add tests for lrclib_client, scan exclusions, lrc parsing, ai sync ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  - test_lrclib_client: _raise_for_status, model helpers, challenge solver, API methods
- test_scan_exclusions: path/pattern exclusion helpers
- test_lrc_parsing: parse_lrc, ms_to_ts, parse_ts_str, _ts_to_ms
- test_ai_sync_worker: _format_ts, _build_lrc_from_segments
* Add path traversal tests for lyrics sidecar export ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Verify that patterns containing '../' and malicious track metadata cannot write files outside the configured output directory.

### 🔧 Other Changes
* Cache artist/album lookups in add_tracks ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Pre-load artist and album ID caches before bulk insert loop, eliminating per-track find_artist/find_album database queries. New entries are added to the cache as they're created.
* Cache get_config result at module level ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Cache Config object after first DB read. Invalidate cache at the start of set_config so subsequent get_config calls re-read.
* Single-row update instead of full view refresh after lyrics save ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  Replace _refresh_visible_library_view_after_downloads with targeted update_track_lyrics_state for single-track save and AI sync operations. Full refresh still used for bulk operations (batch download, rescan).
* Remove redundant get_track_by_id from update_track_* functions ([fbb94b7](https://github.com/saitatter/pylrcget/commit/fbb94b7e8bc2ec0177cc6b529405f2bfba188e73))
  All update/clear functions now return None. Callers that need the updated Track explicitly call get_track_by_id, eliminating the double-SELECT that occurred on every lyrics save.


## v1.2.0 (2026-04-24)

### ✨ Features
* **ui:** Improve responsive layout and retry workflow ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Add hotkey hint badges ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **lyrics:** Parallelize batch download matching ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **lyrics:** Require review before applying batch matches ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **lyrics:** Auto-apply exact batch matches ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))

### 🐛 Fixes
* **ui:** Improve responsive resizing ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Keep top bar groups compact vertically ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Protect lyrics panel minimum width ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Prevent lyrics toolbar from being squeezed ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Wrap lyrics toolbar responsively ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Style lyrics shift control ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **release:** Group changelog sections by parsed type ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **release:** Dedupe squash commit changelog entries ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **update:** Define logger for asset downloads ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **lyrics:** Stop relaxed retry after strong match ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Address batch review feedback ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **lyrics:** Keep batch progress monotonic ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **lyrics:** Cancel batch downloads immediately ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **lyrics:** Skip invalid lrclib durations ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **lyrics:** Fallback immediately on not found ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Keep lyrics status column visible ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Widen duration column ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Center track table status headers ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Visually center table headers ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **lyrics:** Reduce redundant relaxed search calls ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Tidy player speed controls layout ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Compact player speed and volume controls ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **lyrics:** Handle reviewed and perfect matches ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Make speed prefix non-editable ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Right-align player volume controls ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **lyrics:** Apply matches off the ui thread ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Restore toolbar button justification ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Clarify track context menu groups ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **ui:** Import context menu spacing helper ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **lyrics:** Track concurrent apply workers ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))

### ♻️ Refactors
* **ui:** Name responsive layout dimensions ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))

### 🔧 Other Changes
* **lyrics:** Parallelize relaxed retry queries ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))
* **lyrics:** Parallelize retry search across tracks ([45a80d1](https://github.com/saitatter/pylrcget/commit/45a80d1129b2cd3b5c1a594bb90fd155b91b68c0))


## v1.1.0 (2026-04-24)

### ✨ Features
* **lyrics:** Batch retry failed downloads with relaxed search ([bc7ecde](https://github.com/saitatter/pylrcget/commit/bc7ecded7cc662793768c170eaf3aa92f5ce8e71))
* **release:** Add portable single-file build assets ([bc7ecde](https://github.com/saitatter/pylrcget/commit/bc7ecded7cc662793768c170eaf3aa92f5ce8e71))
* **release:** Include extended commit descriptions ([bc7ecde](https://github.com/saitatter/pylrcget/commit/bc7ecded7cc662793768c170eaf3aa92f5ce8e71))

### 🐛 Fixes
* Don't quit app before installer starts — let inno setup handle it ([bc7ecde](https://github.com/saitatter/pylrcget/commit/bc7ecded7cc662793768c170eaf3aa92f5ce8e71))
  Remove QApplication.quit() after launching the installer. The Inno Setup /CLOSEAPPLICATIONS and /FORCECLOSEAPPLICATIONS flags tell the installer to close the running app via Windows Restart Manager, which then knows to reopen it after the update via /RESTARTAPPLICATIONS.
  Previously the app quit immediately after os.startfile() returned (which is non-blocking), causing two issues: 1. Installer window appeared behind other windows (lost focus context) 2. Restart Manager had nothing to restart (app already exited on its own)
* **release:** Parse squash commits for changelog ([bc7ecde](https://github.com/saitatter/pylrcget/commit/bc7ecded7cc662793768c170eaf3aa92f5ce8e71))
* **lyrics:** Keep retry search resilient per track ([bc7ecde](https://github.com/saitatter/pylrcget/commit/bc7ecded7cc662793768c170eaf3aa92f5ce8e71))

### ♻️ Refactors
* **lyrics:** Tidy retry match review internals ([bc7ecde](https://github.com/saitatter/pylrcget/commit/bc7ecded7cc662793768c170eaf3aa92f5ce8e71))


## v1.0.3 (2026-04-23)

### ✨ Features
* Implement real lrclib lyrics publishing ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  - replace stub PublishWorker with actual lrclib API integration
- use lrclib.LrcLibAPI for challenge request, nonce solving, and publish
- handle IncorrectPublishTokenError, RateLimitError, and APIError with user feedback
- pass lrclib_instance from config through dialog to worker
- add proper logging for publish errors
* Expose lrclib server url in settings ui ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Add manual lrclib lyrics search with search dialog ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Add lrc lint validation before publishing lyrics ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Add batch publish to lrclib from track list context menu ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Add retry with exponential backoff to publish operations ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Publish instrumental marking to lrclib when marking tracks locally ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Add separate artist/title/album fields to lrclib search dialog ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Color-code search result types and sort by best match ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Add progress overlay for bulk publish operations ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Add lrclib browser tab for searching and publishing any lyrics ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Reattach orphan lyrics when audio files are moved or renamed ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Add 'write lyrics' button for tracks with no lyrics ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Add undo/redo support in lyrics editor (ctrl+z / ctrl+y) ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Persist window geometry, splitter sizes, and tab selection across sessions ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Add drag-and-drop support for adding music folders ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Add ctrl+s (save lyrics) and ctrl+f (focus search) keyboard shortcuts ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Show selection count in status bar when multiple tracks are selected ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Add tooltips to lyrics editor buttons and track table columns ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Show result count in status bar when searching tracks ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Allow minimizing bulk download/publish overlays to background ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  The close button (×) now hides the overlay instead of cancelling the operation. A progress button appears in the top bar while a background operation is running — click it to reopen the overlay and check progress. STOP button still cancels the operation as before.

### 🐛 Fixes
* Update flow, cleanup, and lrclib integration features ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Resolve update installer not launching from smoke test ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  - bump default smoke test version tag from v0.9.99 to v99.0.0 so updates are always detected
- allow install from non-frozen builds when PYLRCGET_UPDATE_DEBUG is enabled
- show confirmation dialog before launching installer to prevent UAC prompt from being lost in background
- update dialog message to be platform-agnostic
* Add sha-256 integrity hashing during update asset download ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  - compute SHA-256 hash incrementally during download for integrity verification
- add hashlib import for future checksum validation support
* Remove dead challenge-solving code from publish, fix silent error swallowing, unify user-agent ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Address review — lint warnings, timestamp regex, sha-256 logging ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Strip leading spaces per line when deriving plain from synced lyrics ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Handle empty json response from lrclib publish endpoint ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Show 'publishing/published' instead of 'downloading' in publish overlay ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Stabilize splitter layout — stop resetting sizes on every resize ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Remove duplicate appdata subfolder (pylrcget/pylrcget -> pylrcget) ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  setOrganizationName was creating an extra nesting level. Clear it and auto-migrate existing data from the old nested path.
* Address gemini review — narrow except clause, centralize plain-from-lrc ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  - Replace bare 'except Exception' with (sqlite3.Error, AttributeError)
  in publish_history_controller bulk item callback.
- Extract plain_text_from_lrc() to core/utils.py, replacing the naive
  regex in bulk_publish_worker and the parse_lrc import in main_window.
  The new function properly skips LRC metadata tags ([ar:], [ti:], etc.).
* Apply gemini review fixes (lyrics save, migration safety, lint) ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  - Critical: _on_lyrics_selected was calling update_track_synced_lyrics
  with 3 args instead of 4 (missing plain_lyrics), and
  update_track_plain_lyrics was nullifying synced lyrics when both
  were present. Rewrote to single update path.
- Medium: os.rename in AppData migration now wrapped in try/except
  to prevent startup crash on locked files.
- Medium: LRCLIB browser publish dialog now runs lint_lyrics
  validation before submitting, matching PublishLyricsDialog.
* Orphan lyrics reattachment (frozen dataclass, chunking, instrumental) ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  - Critical: reattachment was setting attributes on frozen FsTrack, which
  would crash with FrozenInstanceError at runtime. Use dataclasses.replace()
  instead.
- High: get_orphan_lyrics_index now processes paths in chunks of 900 to
  stay below SQLite's SQLITE_MAX_VARIABLE_NUMBER limit (default 999).
- Medium: instrumental flag is now reattached from orphan data and
  respected by add_track alongside auto-detection from LRC tags.
* Daemon threads for pow solver, multi-row delete in lyrics editor ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  - PoW solver threads now marked daemon=True so they don't block
  app exit if a challenge is being solved when the user closes.
- Lyrics editor delete now removes all selected rows (extended
  selection was enabled but only currentRow was deleted).
* Invalid rows rebuild, narrow 400 error, case-insensitive dir dedup ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  - Lyrics editor: rebuild _invalid_rows from TIMESTAMP_VALID_ROLE data
  after multi-row delete instead of clearing (could enable Save with
  invalid timestamps remaining).
- LRCLIB client: only raise IncorrectPublishTokenError for 400 responses
  containing 'token' in the message; other 400s raise generic LrcLibError.
- Drag-drop folders: use os.path.normcase for case-insensitive dedup
  on Windows (prevents adding same folder with different casing).
* Log migration errors, granular publish progress steps ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  - AppData migration: os.rename and os.rmdir failures now logged with
  logging.warning instead of silently swallowed.
- Publish dialog: progress now accurately reflects request_challenge
  and solve_challenge as separate steps instead of lumping both under
  the solve step.

### ♻️ Refactors
* Remove dead code ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  - delete unused LrcLibClient class and LyricsResult dataclass (lrclib_client.py)
- remove 12 unused accessor methods from FsTrack in core/models.py
- remove unused strip_timestamp() from core/utils.py
* Replace debug print statements with proper logging ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  - replace 4 print() calls in db/migrations.py with logger.info/warning
- replace 3 print() calls in library/fs_track.py with logger.debug
* Replace bare except handlers with specific exception types ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Replace lrclibapi package with custom lrclib client ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  - New src/core/lrclib_client.py with proper User-Agent (versioned),
  10s request timeout, correct 201 empty-body handling, and
  challenge solver.
- Expose get_lyrics(cached=True) for /api/get-cached endpoint.
- Expose get_lyrics_by_id() for /api/get/{id} endpoint.
- Remove all json.JSONDecodeError workarounds from publish paths.
- Remove lrclibapi from requirements.txt.
- Fix IncorrectPublishTokenError to only apply to 400 on /publish,
  not to all 400 responses.

### 🧰 CI & Build
* Update release note and changelog templates ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
* Remove legacy library/fs_track.py (dead code) ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  All code uses core.models.FsTrack (frozen dataclass with modified_time, file_size, instrumental). The legacy FsTrack class, ScanProgress, load_tracks_from_entry_batch, load_tracks_from_directories, and count_files_from_directories were unused dead code.

### 📚 Docs
* Rewrite readme with badges, tables, and structured sections ([c7c0bd3](https://github.com/saitatter/pylrcget/commit/c7c0bd36b3b8e19fbefa3280c613aef968da22ba))
  - add shield.io badges for license, release, issues, tech stack, and platform
- reorganize features into emoji-prefixed sections
- consolidate audio format support into a comparison table
- add Troubleshooting and Contributing sections
- condense settings and download modes into tables


## v1.0.2 (2026-04-23)

### 🐛 Fixes
* **release:** Enforce semantic pr titles for squash merges ([25cdb77](https://github.com/saitatter/pylrcget/commit/25cdb770c17c20ab49d1b8a5dd92feeb5a38685b))


## v1.0.1 (2026-04-23)

### 🐛 Fixes
* **release:** Treat ci and chore commits as patch ([cb217e7](https://github.com/saitatter/pylrcget/commit/cb217e7dd5d25a5c13a8251ddbe5f7b6b2772e98))

### 🧰 CI & Build
* Add codeowners to require owner approval ([05e0c5d](https://github.com/saitatter/pylrcget/commit/05e0c5d6c3d5c0e1f54de2b76b4877cda8783f74))


## v1.0.0 (2026-04-23)

### ✨ Features
* Switch release notes to semantic templates and fix installer assets ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Add per-track refresh from disk in the library view ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Support configurable lyrics lookup subfolders with embedded-first priority ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Add appearance settings for ui scale, font size, album art, and startup view ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Add installer-based update install flow for macos and linux ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Enable major bump from 0.x for v1 release ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Switch release notes generation to semantic-release templates ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
  Use semantic-release changelog templates for both release notes and CHANGELOG output with ordered emoji categories.
* Improve updater flow, release assets, and migration baseline ([671106e](https://github.com/saitatter/pylrcget/commit/671106e53fc87fdd647088a43d4f5e98f7e2b2dc))

### 🐛 Fixes
* Add track restart logic and improve file picker dialog ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Add windows exe icon and improve playback/settings behavior ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Harden windows self-update flow with backup, hash check, and logging ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Refine top bar alignment and clean up input backgrounds ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Scale track action buttons and columns with ui scale ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Correct border-sradius typo in volume slider styling ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Preserve app version in frozen update builds ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Harden self-update relaunch flow for packaged builds ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Avoid player bar signal disconnect warnings on startup ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Refine top bar filter checkbox focus and hover states ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Support {filename}/empty export patterns and allow saving settings without music folders ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Harden unix updater and disable row refresh during active downloads ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Improve updater launch reliability and avoid redundant startup navigation ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Harden startup timer lifetime and add updater log dir fallback on windows ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Prepare db versioning path, persist track refresh updates, and polish updater ui/hover behavior ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))

### ♻️ Refactors
* Simplify track context menu and group actions by selection ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Rename app to pylrcget and drop legacy data path fallback ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Reset database schema to v1 for clean release ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Switch windows updates to installer flow and add local update feed tools ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Rename app database file to pylrcget.db.sqlite3 ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Centralize updater app path name and document inno setup flags ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Remove redundant player position signal wiring from main window init ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))

### 🧰 CI & Build
* Switch pyinstaller packaging to onedir for installer workflows ([205d4d7](https://github.com/saitatter/pylrcget/commit/205d4d77860a65322abb713399a92e91950ab777))
* Switch to github categorized release notes and dedupe squash parsing ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))
* Stabilize release pipeline, installers, and github notes ([347abde](https://github.com/saitatter/pylrcget/commit/347abde20e169fecea8d1ecf879fd7ec7cf2ab81))
* Add cross-platform installer assets to release workflow while keeping archive fallbacks ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))

### 📚 Docs
* Update readme ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))

### 🧪 Tests
* Remove obsolete legacy migration tests after clean v1 reset ([657dade](https://github.com/saitatter/pylrcget/commit/657dadeb21bb4cc16808627e35c357962c620a4e))


## v0.9.0 (2026-04-12)

### ✨ Features
* Playback, library refresh, lyrics lookup, and appearance settings ([4d16e86](https://github.com/saitatter/pylrcget/commit/4d16e863444270e6b59467bbd214a0e3be7227a1))
* Add per-track refresh from disk in the library view ([4d16e86](https://github.com/saitatter/pylrcget/commit/4d16e863444270e6b59467bbd214a0e3be7227a1))
* Support configurable lyrics lookup subfolders with embedded-first priority ([4d16e86](https://github.com/saitatter/pylrcget/commit/4d16e863444270e6b59467bbd214a0e3be7227a1))
* Add appearance settings for ui scale, font size, album art, and startup view ([4d16e86](https://github.com/saitatter/pylrcget/commit/4d16e863444270e6b59467bbd214a0e3be7227a1))

### 🐛 Fixes
* Add track restart logic and improve file picker dialog ([4d16e86](https://github.com/saitatter/pylrcget/commit/4d16e863444270e6b59467bbd214a0e3be7227a1))
* Add windows exe icon and improve playback/settings behavior ([4d16e86](https://github.com/saitatter/pylrcget/commit/4d16e863444270e6b59467bbd214a0e3be7227a1))
* Harden windows self-update flow with backup, hash check, and logging ([4d16e86](https://github.com/saitatter/pylrcget/commit/4d16e863444270e6b59467bbd214a0e3be7227a1))
* Refine top bar alignment and clean up input backgrounds ([4d16e86](https://github.com/saitatter/pylrcget/commit/4d16e863444270e6b59467bbd214a0e3be7227a1))
* Scale track action buttons and columns with ui scale ([4d16e86](https://github.com/saitatter/pylrcget/commit/4d16e863444270e6b59467bbd214a0e3be7227a1))
* Correct border-sradius typo in volume slider styling ([4d16e86](https://github.com/saitatter/pylrcget/commit/4d16e863444270e6b59467bbd214a0e3be7227a1))

### ♻️ Refactors
* Simplify track context menu and group actions by selection ([4d16e86](https://github.com/saitatter/pylrcget/commit/4d16e863444270e6b59467bbd214a0e3be7227a1))


## v0.8.0 (2026-04-11)

### ✨ Features
* Expand lrclib download workflows and tooling ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Add support for musepack audio format in lyrics embedding and scanning ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Add export functionality for lyrics files across various views ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Implement publish history tracking and ui integration ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Add download synced lyrics only option and update database schema ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Add configurable lyrics download modes ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Add bulk lyrics downloads with progress tracking ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Color-code lyrics states in track list ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Update database schema to version 21 with new column for download lyrics mode ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Update download button icon and add new download svg asset ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Enhance database migration for download lyrics mode and improve download state management ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Refactor lyrics download workflow to include database connection handling and sync outputs ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Implement download progress overlay and integrate with lyrics download workflow ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Remove deprecated download ui elements and integrate download progress overlay ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Enhance bulk lyrics download worker to include track title and artist in progress updates ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Integrate theme tokens for color management in ui components ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Add retry backoff for lrclib downloads ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Persist and surface lyrics download history ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Polish my lrclib history workspace ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Clarify missing lyrics semantics across download modes ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Enhance lyrics download functionality and improve widget sorting behavior ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Implement update service and about dialog for application updates ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Add batch download history recording and enhance download history management ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Enhance lyrics download service and update management features ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Add application icon loading functionality and set window icon ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Streamline download state management in album and artist widgets ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))

### 🐛 Fixes
* Ensure database connection is properly managed in bulk lyrics download worker ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))

### ♻️ Refactors
* Streamline plain lyrics update logic in download_track_lyrics function ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Centralize lyrics download workflow orchestration ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Extract publish history workflow from main window ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Tighten typing across lyrics download flow ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Model lyrics and download states with enums ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Extract shared lyrics download service ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Extract cover art loading into shared helper ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Share post-download output handling ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Extract top bar controller from main window ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Extract library navigation controller ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Tighten ui typing for models delegates and workers ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Reduce ui reliance on database compatibility imports ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Standardize ui feedback and notification flow ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Align ui accents and overlay styling with theme tokens ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Improve download overlay dismissal behavior ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Split shared helpers from large library widgets ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Streamline cover extraction and normalize download mode in lyrics service ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))

### 📚 Docs
* Enhance readme with new features and diagnostics information ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Describe lyrics download modes and missing behavior ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))

### 🧪 Tests
* Cover bulk lyrics download controller flows ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Cover migration from v20 to v21 ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))
* Cover musepack scan embed and artwork flows ([87118cd](https://github.com/saitatter/pylrcget/commit/87118cd4c326905d3fca1bf87b029910978e4246))


## v0.7.0 (2026-04-11)

### ✨ Features
* Add sync quality-of-life controls ([074896d](https://github.com/saitatter/pylrcget/commit/074896d1329a5c33294a2d6691abbc91e7b0c174))
* Add sync qol controls and auto-scan folders ([074896d](https://github.com/saitatter/pylrcget/commit/074896d1329a5c33294a2d6691abbc91e7b0c174))
* Update volume control layout and styling in player bar ([074896d](https://github.com/saitatter/pylrcget/commit/074896d1329a5c33294a2d6691abbc91e7b0c174))
* Enhance lyrics editor with current playback position handling ([074896d](https://github.com/saitatter/pylrcget/commit/074896d1329a5c33294a2d6691abbc91e7b0c174))
* Implement logging functionality and add log panel to ui ([074896d](https://github.com/saitatter/pylrcget/commit/074896d1329a5c33294a2d6691abbc91e7b0c174))
* Add logging functionality with log panel and controls ([074896d](https://github.com/saitatter/pylrcget/commit/074896d1329a5c33294a2d6691abbc91e7b0c174))
* Enhance log panel with entry limit and filtering functionality ([074896d](https://github.com/saitatter/pylrcget/commit/074896d1329a5c33294a2d6691abbc91e7b0c174))
* Improve log panel with entry limit and automatic scrolling ([074896d](https://github.com/saitatter/pylrcget/commit/074896d1329a5c33294a2d6691abbc91e7b0c174))


## v0.6.0 (2026-04-09)

### ✨ Features
* Improve library scanning and lyrics personalization ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Enhance audio track extraction with error handling for unreadable files ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Implement exclusion paths and patterns for audio library scanning ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Enhance library scanning with file signature checks and improved path handling ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Update database version to 13 and add reaction delay configuration ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Update database version to 14 and add playback speed configuration ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Enhance database operations with optional commit control for add and delete functions ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Refactor audio path iteration and update track creation with signature support ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Optimize library pruning logic and ensure database closure on scan cancellation ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Improve track addition and playback speed persistence in main window ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Update database version to 15 and implement migration for version 15 ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Enhance database migration process and improve directory selection dialogs ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Refactor path exclusion logic and streamline database transaction handling in libraryscanner ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Add _join_normalized_path function and refactor audio path iteration for improved directory handling ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Update artist and album queries to use lowercased names for improved consistency ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Add custom speed editing with debounce timer in playerbar ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Add normalization methods for album and artist ids in respective widgets ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Enhance playerbar button styles and layout for improved usability ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Enhance seekslider appearance with custom paint event and update qss for rounded slider edges ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))

### ♻️ Refactors
* Remove unused excluded paths ui components and streamline library scanner error handling ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Remove back navigation functionality from albumlistwidget and artistlistwidget ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))

### 📚 Docs
* Add windows release note regarding unsigned builds and smartscreen warnings ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))

### 🔧 Other Changes
* Update layout spacing and border styles for playerbar and playershell ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))
* Refine layout and button sizes in playerbar for improved aesthetics and usability ([3440ab3](https://github.com/saitatter/pylrcget/commit/3440ab34f395696095d14844dcd09d67db15aced))


## v0.5.0 (2026-04-06)

### ✨ Features
* Improve library drilldown navigation and settings organization ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
* Enhance player bar with artist and album navigation ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
  - Added signals for artist and album navigation requests in PlayerBar.
- Updated artist and album labels to be clickable links, triggering navigation signals.
- Improved styling for artist and album labels in player bar QSS.
- Introduced TrackInfoDelegate for rendering track information with clickable artist and album links.
- Refactored AlbumListWidget and ArtistListWidget to support multiple artist and album IDs.
- Enhanced TrackListWidget to display scope banners for active filters.
- Implemented back navigation functionality in AlbumListWidget and ArtistListWidget.
- Updated data models to handle multiple IDs for albums and artists.
* Refactor musicfoldersdialog to include tabbed interface for library, lyrics, and appearance settings ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
* Improve track info display and handle missing album/artist ids in main window ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
* Implement navigation system with library routes and enhance ui components ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
* Add github actions workflow for running tests and create test suite for library scanning and navigation ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
* Add search and refresh functionality to album and artist lists with empty state handling ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
* Enhance musicfoldersdialog with filename pattern preview and validation ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
* Update database version to 17 and enhance album/artist widgets with pagination and sorting ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
* Implement caching for artist and album labels in main window; enhance album and artist list widgets with loaded row tracking ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))

### 🐛 Fixes
* Update artist and album id checks to use 'and' condition for clarity ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
* Ensure loading state is reset after attempting to load rows in tracklistwidget ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
* Improve artist name retrieval in album queries to handle empty album artist names ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))

### ♻️ Refactors
* Simplify test setup by removing unnecessary database table creation for album and artist widgets ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
* Remove navigation buttons from mainwindow and update layout accordingly ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
* Enhance album and artist tabs with dedicated lyrics views and improved layout ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))
* Add unit tests for library routes, scan helpers, and navigation widgets ([fcaf261](https://github.com/saitatter/pylrcget/commit/fcaf2619e7fe05199eae9e2198cef088c4da26a3))


## v0.4.0 (2026-04-06)

### ✨ Features
* Improve syncing workflow and incremental library scanning ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))
* Enhance audio track extraction with error handling for unreadable files ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))
* Implement exclusion paths and patterns for audio library scanning ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))
* Enhance library scanning with file signature checks and improved path handling ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))
* Update database version to 13 and add reaction delay configuration ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))
* Update database version to 14 and add playback speed configuration ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))
* Enhance database operations with optional commit control for add and delete functions ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))
* Refactor audio path iteration and update track creation with signature support ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))
* Optimize library pruning logic and ensure database closure on scan cancellation ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))
* Improve track addition and playback speed persistence in main window ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))
* Update database version to 15 and implement migration for version 15 ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))
* Enhance database migration process and improve directory selection dialogs ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))
* Refactor path exclusion logic and streamline database transaction handling in libraryscanner ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))
* Add _join_normalized_path function and refactor audio path iteration for improved directory handling ([ad6dc32](https://github.com/saitatter/pylrcget/commit/ad6dc3248230349e51ab6034b42f8a6ee765bad0))


## v0.3.0 (2026-04-06)

### ✨ Features
* Add theme system, player bar refresh, and extended format support ([58059d8](https://github.com/saitatter/pylrcget/commit/58059d8d43038c3bd8039a93dcf38e2b42800128))
* Enhance ui with theme support and style updates ([58059d8](https://github.com/saitatter/pylrcget/commit/58059d8d43038c3bd8039a93dcf38e2b42800128))
  - Added theme selection in MusicFoldersDialog with QComboBox for user customization.
- Updated ActionsDelegate to handle button states more effectively during loading.
- Refactored MainWindow to apply themes dynamically based on user selection.
- Introduced new theme tokens for consistent styling across the application.
- Updated QSS files to utilize theme tokens for colors, borders, and backgrounds.
- Enhanced EmptyStateWidget and LyricsEditorWidget to apply styles dynamically.
- Improved ToastWidget to reflect theme colors for notifications.
- Enabled mouse tracking in TrackListWidget for better interactivity.
* Refactor playerbar layout and improve styling for better ui consistency ([58059d8](https://github.com/saitatter/pylrcget/commit/58059d8d43038c3bd8039a93dcf38e2b42800128))
* Add support for embedding lyrics in asf/wma files and update audio file handling ([58059d8](https://github.com/saitatter/pylrcget/commit/58059d8d43038c3bd8039a93dcf38e2b42800128))
* Add support for dsf and dsdiff audio formats in lyrics embedding and scanning ([58059d8](https://github.com/saitatter/pylrcget/commit/58059d8d43038c3bd8039a93dcf38e2b42800128))
* Update audio tag handling for id3 and asf formats ([58059d8](https://github.com/saitatter/pylrcget/commit/58059d8d43038c3bd8039a93dcf38e2b42800128))
* Refactor audio file handling and improve lyrics extraction logic ([58059d8](https://github.com/saitatter/pylrcget/commit/58059d8d43038c3bd8039a93dcf38e2b42800128))


## v0.2.0 (2026-04-06)

### ✨ Features
* Add configurable lyrics export and refresh ui icons ([5cb1feb](https://github.com/saitatter/pylrcget/commit/5cb1feb0ec356998f39e019801f58c05b90b3e59))
* **database:** Update to version 8 and add new config fields for lyrics export ([5cb1feb](https://github.com/saitatter/pylrcget/commit/5cb1feb0ec356998f39e019801f58c05b90b3e59))
* **ui:** Enhance music folders dialog with lyrics export settings ([5cb1feb](https://github.com/saitatter/pylrcget/commit/5cb1feb0ec356998f39e019801f58c05b90b3e59))
* **lyrics:** Implement export functionality for lyrics sidecars ([5cb1feb](https://github.com/saitatter/pylrcget/commit/5cb1feb0ec356998f39e019801f58c05b90b3e59))
* **database:** Upgrade to version 9 and add save_lyrics_sidecars config option ([5cb1feb](https://github.com/saitatter/pylrcget/commit/5cb1feb0ec356998f39e019801f58c05b90b3e59))
* **ui:** Add checkbox for saving lyrics files in music folders dialog ([5cb1feb](https://github.com/saitatter/pylrcget/commit/5cb1feb0ec356998f39e019801f58c05b90b3e59))
* **ui:** Replace standard icons with svg icons and add icon loader utility ([5cb1feb](https://github.com/saitatter/pylrcget/commit/5cb1feb0ec356998f39e019801f58c05b90b3e59))
* **config:** Update musicfoldersdialog to use dataclass replacement for config updates ([5cb1feb](https://github.com/saitatter/pylrcget/commit/5cb1feb0ec356998f39e019801f58c05b90b3e59))

### 🐛 Fixes
* **ui:** Update lyrics export logic to respect save_lyrics_sidecars setting ([5cb1feb](https://github.com/saitatter/pylrcget/commit/5cb1feb0ec356998f39e019801f58c05b90b3e59))
* **qss:** Correct url syntax for checkbox checked indicator image ([5cb1feb](https://github.com/saitatter/pylrcget/commit/5cb1feb0ec356998f39e019801f58c05b90b3e59))
* **delegate:** Correct event type reference in editorevent method ([5cb1feb](https://github.com/saitatter/pylrcget/commit/5cb1feb0ec356998f39e019801f58c05b90b3e59))

### ♻️ Refactors
* **main:** Integrate lyrics export in the main window's download process ([5cb1feb](https://github.com/saitatter/pylrcget/commit/5cb1feb0ec356998f39e019801f58c05b90b3e59))


## v0.1.1 (2026-04-06)

### 🐛 Fixes
* **ci:** Use release pat for semantic-release pushes ([9314cc8](https://github.com/saitatter/pylrcget/commit/9314cc87383be090379d768a37902fabc6e2e6ac))
* **build:** Make pyinstaller spec resolve root without __file__ ([5b83577](https://github.com/saitatter/pylrcget/commit/5b8357702c9f9adbf02f3f6df35995d47e5f96f7))


## v0.1.0 (2026-04-06)

### ✨ Features
* **ui:** Move refresh and settings actions to top bar icon buttons ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **release:** Add github actions workflow for automated releases and changelog generation ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **ui:** Implement sorting functionality in tracklistwidget ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **ui:** Implement theming and style loading for ui components ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **ui:** Add sortable header functionality to album and track list widgets ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **ui:** Standardize layout spacing across ui components ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **ui:** Enhance top bar layout and styling for improved user experience ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **ui:** Implement empty state widget and enhance ui responsiveness with new icons and styles ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **ui:** Implement download state management for track list and enhance button feedback ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **ui:** Retrieve track information in play_track method ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **ui:** Enhance player bar layout and styling for improved user experience ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **ui:** Add album information to track metadata and enhance player bar layout ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **ui:** Add support for embedded and sidecar cover art in player bar ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* Improve synced lyrics editor feedback ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* Polish tab navigation states ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* Organize library context menus ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* Improve responsive ui layouts ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* Enhance library scan progress ui ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* Add first-run onboarding flow ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* Improve ui accessibility affordances ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **player:** Add playback speed control for lyric editing ([093fc7b](https://github.com/saitatter/pylrcget/commit/093fc7be2d689c2b0c397afecbccbf5d16d3e378))
* **library:** Add artists & albums pages with id-based navigation ([1074b89](https://github.com/saitatter/pylrcget/commit/1074b897d0cb633f6645a0827f3aa13bda53448a))
* **tracks:** Add multi-select instrumental tagging with bulk actions ([1074b89](https://github.com/saitatter/pylrcget/commit/1074b897d0cb633f6645a0827f3aa13bda53448a))
  - enable extended selection in track list
- add bulk "mark as instrumental" and "unmark instrumental" actions
- add confirmation dialog for large selections
- preserve selection after bulk updates
- add fast batch DB updates for instrumental tagging
* Add embed lyrics functionality and ui integration ([adcfea0](https://github.com/saitatter/pylrcget/commit/adcfea04e9c8deb81744d45057e8875c5847365d))
* Add functionality to read embedded lyrics from various audio formats ([adcfea0](https://github.com/saitatter/pylrcget/commit/adcfea04e9c8deb81744d45057e8875c5847365d))
* Reintroduce main application logic and dependencies in main.py and requirements.txt ([adcfea0](https://github.com/saitatter/pylrcget/commit/adcfea04e9c8deb81744d45057e8875c5847365d))
* Implement main window ui and functionality ([1e91efa](https://github.com/saitatter/pylrcget/commit/1e91efac95a6e1f5cd6dfb8f8d6f1d5fa091b116))
  - Added MainWindow class with layout and controls for track management.
- Integrated player controls and notifications.
- Implemented track filtering and searching capabilities.
- Added functionality for refreshing the music library and scanning directories.
- Implemented track playback and handling of lyrics download and publishing.
* Create track table model ([1e91efa](https://github.com/saitatter/pylrcget/commit/1e91efac95a6e1f5cd6dfb8f8d6f1d5fa091b116))
  - Introduced TrackTableModel for managing track data in a table format.
- Implemented methods for setting rows, retrieving track IDs, and handling display data.
* Add player bar ui ([1e91efa](https://github.com/saitatter/pylrcget/commit/1e91efac95a6e1f5cd6dfb8f8d6f1d5fa091b116))
  - Created PlayerBar class for controlling playback with buttons and a slider.
- Integrated display for current track information and playback duration.
* Implement toast notifications ([1e91efa](https://github.com/saitatter/pylrcget/commit/1e91efac95a6e1f5cd6dfb8f8d6f1d5fa091b116))
  - Added Toast class for displaying temporary notifications in the UI.
* Create track list widget ([1e91efa](https://github.com/saitatter/pylrcget/commit/1e91efac95a6e1f5cd6dfb8f8d6f1d5fa091b116))
  - Developed TrackListWidget for displaying and managing a list of tracks.
- Implemented context menu for track actions and double-click functionality for playback.
* Implement library scanner worker ([1e91efa](https://github.com/saitatter/pylrcget/commit/1e91efac95a6e1f5cd6dfb8f8d6f1d5fa091b116))
  - Created LibraryScanner class for scanning directories and adding tracks to the database.
- Added progress and completion signals for tracking the scanning process.
* Implement lyrics download worker ([1e91efa](https://github.com/saitatter/pylrcget/commit/1e91efac95a6e1f5cd6dfb8f8d6f1d5fa091b116))
  - Developed LyricsDownloadWorker for downloading lyrics from LRCLIB API.
- Added functionality for saving synced and plain lyrics to the database.

### 🐛 Fixes
* **ui:** Import player class for audio functionality ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))

### ♻️ Refactors
* **ui:** Clean up mainwindow and signal wiring ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* **lyrics:** Preserve timestamp-only lines in synced editor ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* Centralize ui design tokens ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
* Simplify header layout by removing duplicate buttons in lyricsview ([adcfea0](https://github.com/saitatter/pylrcget/commit/adcfea04e9c8deb81744d45057e8875c5847365d))
* Improve embed lyrics functionality and update comments for clarity ([adcfea0](https://github.com/saitatter/pylrcget/commit/adcfea04e9c8deb81744d45057e8875c5847365d))
* Remove version constraints from requirements.txt for dependencies ([adcfea0](https://github.com/saitatter/pylrcget/commit/adcfea04e9c8deb81744d45057e8875c5847365d))
* Update signal connection for saverequested in mainwindow ([adcfea0](https://github.com/saitatter/pylrcget/commit/adcfea04e9c8deb81744d45057e8875c5847365d))
  * Use pathlib instead of os.path; now the scan library uses the embed tags defined by embed_lyrics
  * Update src/ui/lyrics_view.py
  Co-authored-by: gemini-code-assist[bot] <176961590+gemini-code-assist[bot]@users.noreply.github.com>
  * Update src/core/embed_lyrics.py
  ---------

### 🧰 CI & Build
* Polish ui copy ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))

### 🔧 Other Changes
* Unify input and action controls ([7c91941](https://github.com/saitatter/pylrcget/commit/7c9194158932565844c7f704c2e27e46de5d5f98))
