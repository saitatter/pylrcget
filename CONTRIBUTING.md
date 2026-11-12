# Contributing to PyLrcGet

Read [AGENTS.md](AGENTS.md) for working rules and [README.md](README.md) for
installation and local builds. Use Python 3.13.15 and an isolated virtual
environment. Install development dependencies with `pip install -e ".[dev]"`.
The optional `ai` extra is only needed for local AI integration checks.

Use focused conventional commits with a body describing the change, its reason
and validation. Add a short user-facing entry under `Unreleased` in
[CHANGELOG.md](CHANGELOG.md). Avoid emoji. Add regression tests for behavior
changes and test migrations against isolated databases, never a real library.

On Windows, run:

```powershell
$env:PYTHONPATH = "src"
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
```

On Unix, use `.venv/bin/python` and export the same environment variables.
Tests requiring a network, GPU or reference library must be explicit; describe
any such checks separately in your PR. Include the behavior before and after
the change, issue references, and the checks you actually ran.

Keep documentation in [docs](docs/README.md), reusable developer tools in
`tools/`, and generated reports outside Git. Use rebase merging for PRs with
several focused commits. Releases are prepared by the manual Release workflow
on `main`, as described in [release notes](docs/release-notes.md).

Contributions are distributed under this project's [MIT license](LICENSE).
Only submit code and assets you have the right to contribute, and preserve
third-party license notices.
