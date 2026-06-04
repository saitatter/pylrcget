# Copilot Instructions for PyLrcGet

## Communication

- Raspunde in romana, concis si practic.
- Explica tradeoff-urile importante inainte de schimbari riscante.
- Nu inventa comportamente; verifica in cod, teste sau documentatie locala.

## Project Context

- PyLrcGet is a Python 3.10+ PySide6 desktop app for local music library scanning, lyrics editing, playback, LRCLIB integration, sidecar export, embedding, updates, and optional local AI auto-sync.
- Entry point: `main.py`.
- App code lives in `src/`; tests live in `tests/`.
- SQLite schema and migrations live in `src/db/`.
- UI styles use QSS files in `src/ui/qss/` plus tokens in `src/ui/theme_tokens.py`.
- Optional AI dependencies are under the `ai` extra in `pyproject.toml`; do not make core startup depend on them.

## Git and Releases

- Use conventional commits. Examples:
  - `feat: add dirty lyrics drafts`
  - `fix: prevent context menu click-through`
  - `test: cover app data migration`
  - `chore: update packaging metadata`
- `python-semantic-release` reads conventional commits from `pyproject.toml`.
- Do not manually edit generated release artifacts unless explicitly requested.
- Keep commits focused; do not mix unrelated UI, DB, and packaging changes unless the feature requires it.

## Python and Style

- Target Python 3.10+.
- Prefer standard-library solutions unless a dependency already exists in `pyproject.toml`.
- Keep type hints on new public helpers and dataclasses.
- Avoid broad `except Exception` except at UI/service boundaries where errors are logged and surfaced to the user.
- Keep file operations safe on Windows: use `Path` or native Python APIs, and avoid destructive recursive deletes without path guards.

## PySide6 UI Rules

- Preserve the existing desktop UI language and QSS/token system.
- Do not hardcode colors in widgets if a QSS/token-based solution fits.
- Avoid blocking the Qt event loop. Long-running work belongs in workers/threads.
- When adding signals, connect them where the owning controller already wires related behavior.
- Use `QDesktopServices`/`QUrl` for cross-platform local file/folder opening.
- For editable lyrics fields, paste should stay plain-text unless rich text is explicitly required.

## Database and Migrations

- Bump `CURRENT_DB_VERSION` in `src/db/database.py` when changing schema.
- Update `src/db/schema.py` for fresh databases.
- Add an explicit migration step in `src/db/migrations.py` for existing databases.
- Add or update tests in `tests/test_migrations.py`.
- Keep query functions in `src/db/queries.py`; keep row dataclasses in `src/db/models.py`.
- When adding columns used by list views, update `get_track_rows`, `Track.from_row`, and UI row builders together.

## Lyrics Workflow

- Committed lyrics are `txt_lyrics` and `lrc_lyrics`.
- Draft/dirty lyrics are separate from committed lyrics and should not be exported or embedded until the user saves.
- Saving lyrics should promote draft content to committed lyrics, clear dirty state, and then run configured sidecar export/embed behavior.
- LRCLIB publish should use committed lyrics, not dirty drafts, unless explicitly changed by a feature request.
- Keep synced lyrics timestamp formatting compatible with existing LRC parsing helpers.

## Testing

- Run targeted tests first, then the full suite when touching shared paths.
- Preferred command on Windows:
  - `$env:PYTHONPATH='src'; .\venv\Scripts\python.exe -m pytest`
- If using global Python, ensure `PYTHONPATH=src` and PySide6 availability.
- UI tests use offscreen Qt setup from `tests/test_support.py`.
- Add regression tests for DB migrations, query behavior, parsing, and user-facing bug fixes.

## Packaging and Updates

- Keep `pylrcget.spec` and `pylrcget-portable.spec` changes minimal and intentional.
- In-app update logic lives in `src/ui/services/update_service.py`; test it with `tests/test_update_service.py`.
- Preserve Restart Manager/update behavior on Windows unless explicitly changing update flow.

## When to Use Skills or Agents

- Use skills for repeatable workflows such as release preparation, migration patterns, testing checklists, or packaging checklists.
- Use agents only when the task benefits from isolation or parallelism, such as an independent review or research pass.
- Do not spawn agents by default; explain why they are useful before using them.
