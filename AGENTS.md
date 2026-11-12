# Working rules

- Follow the user's instructions over this file. Communicate concisely in Romanian;
  write code, documentation, changelog entries and commit messages in English.
- Use conventional commit titles and a body explaining what changed, why and
  how it was checked. Keep each commit focused on one change.
- Update `CHANGELOG.md` under `Unreleased` in the same commit, using Features,
  Fixes, Refactors, Docs or CI & Build. Describe the user-visible effect briefly.
  Fixes and Refactors describe shipped behavior; improve the existing Features
  entry when correcting unreleased work. Check the latest published tag if unsure.
- Use plain text without emoji in documentation, release notes and UI copy.
- Release through the Release workflow on `main`; never bump versions, publish,
  push, rewrite history or replace tags unless the user requests it.
- Prefer rebase merges for PRs with several focused commits; squash a PR only
  when it represents one change. Follow `docs/release-notes.md`.
- Target Python 3.13.15 consistently across metadata, CI, packaging and AI setup.
  Optional AI dependencies must never become required for core startup.
- Keep widgets in `src/ui/widgets`, dialogs in `src/ui/dialogs`, orchestration
  in controllers/main-window parts, background work in workers, provider rules
  in `src/lyrics/providers` and database queries in `src/db/query_modules`.
  Extract focused modules when changing large files; avoid unrelated reorganizations.
- Use the QSS and theme-token system. Keep Qt's event loop responsive and make
  long operations cancellable. Wire signals through the owning controller.
- Preserve committed lyrics separately from drafts. AI results are drafts until
  saved; exports, embedding and publishing use committed lyrics.
- Change released schemas through explicit ordered migrations, updating fresh
  schema and migration tests together. Fold unreleased schema changes into the
  next migration. Never reset a database to make an upgrade pass.
- Never modify a user's live library, database or backups while testing. Use
  isolated test storage. Keep secrets, logs and scratch captures out of Git.
- Run targeted regression tests first, then the full suite for shared changes.
  Use `.venv/Scripts/python.exe -m pytest` and `-m ruff check .` on Windows,
  with `PYTHONPATH=src` and `QT_QPA_PLATFORM=offscreen`. Use the equivalent
  `.venv/bin/python` on Unix. Report checks actually performed and limitations.
- Search with `rg`; read relevant slices and diffs rather than dumping files.
  Keep output short, expanding it when correctness requires it.
