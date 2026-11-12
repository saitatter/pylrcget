"""Preview or update release descriptions using reviewed summaries and full history."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True, encoding="utf-8").strip()


def changelog_summary(changelog: str, tag: str) -> list[str]:
    section = re.search(
        rf"^## v?{re.escape(tag.removeprefix('v'))}(?:\s|$).*?\n(.*?)(?=^## |\Z)",
        changelog, re.MULTILINE | re.DOTALL,
    )
    if section is None:
        raise ValueError(f"No changelog section for {tag}")
    return [line[2:] for line in section.group(1).splitlines() if line.startswith("- ")][:10]


def render_notes(summary: list[str], commits: list[str], generated: str) -> str:
    # GitHub supplies contributor credits and the comparison, not the commit list.
    footer_match = re.search(r"(?m)^## New Contributors|^\*\*Full Changelog\*\*", generated)
    footer = generated[footer_match.start():].strip() if footer_match else ""
    body = "Changes since last release:\n\n" + "\n".join(f"- {line}" for line in summary)
    body += "\n\n---\n\n## What's Changed\n\n" + "\n".join(commits)
    return body + ("\n\n" + footer if footer else "") + "\n"


def commit_rows(history: str, repo: str) -> list[str]:
    rows = []
    for record in history.split("\x1e"):
        if not record.strip():
            continue
        sha, author, email, title, body = record.strip("\r\n").split("\x00", 4)
        login = re.fullmatch(r"(?:\d+\+)?([\w-]+)@users\.noreply\.github\.com", email)
        credit = f"[@{login[1]}](https://github.com/{login[1]})" if login else author
        issues = dict.fromkeys(re.findall(r"(?<![\w/])#(\d+)\b", body))
        links = ", ".join(f"[#{number}](https://github.com/{repo}/issues/{number})" for number in issues)
        row = f"- {title} by {credit} ([{sha[:7]}](https://github.com/{repo}/commit/{sha}))"
        rows.append(row + (f"; {links}" if links else ""))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="saitatter/pylrcget")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    # Verify refs before using them in a revision range.
    run("git", "rev-parse", "--verify", f"refs/tags/{args.tag}")
    tags = run("git", "tag", "--merged", args.tag, "--sort=-version:refname").splitlines()
    previous = next((tag for tag in tags if tag != args.tag), None)
    revision = f"{previous}..{args.tag}" if previous else args.tag
    history = run("git", "log", "--reverse", "--no-merges", "--format=%H%x00%an%x00%ae%x00%s%x00%b%x1e", revision)
    commits = commit_rows(history, args.repo)
    summaries = json.loads((ROOT / "docs/release-summaries.json").read_text(encoding="utf-8"))
    summary = summaries.get(args.tag, {}).get("summary")
    if summary is None:
        summary = changelog_summary((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), args.tag)
    command = ["gh", "api", "--method", "POST", f"repos/{args.repo}/releases/generate-notes", "-f", f"tag_name={args.tag}"]
    if previous:
        command.extend(["-f", f"previous_tag_name={previous}"])
    generated = json.loads(run(*command))["body"]
    notes = render_notes(summary, commits, generated)
    if len(notes.encode("utf-8")) > 120000:
        raise ValueError("Release description is too large; shorten the history before publishing")
    if args.write:
        release = json.loads(run("gh", "release", "view", args.tag, "--repo", args.repo, "--json", "isDraft,body"))
        if release["isDraft"]:
            raise ValueError("Draft releases are not updated")
        if release["body"].strip() == notes.strip():
            return
        subprocess.run(
            ["gh", "release", "edit", args.tag, "--repo", args.repo, "--notes-file", "-"],
            input=notes, text=True, encoding="utf-8", cwd=ROOT, check=True,
        )
    else:
        print(notes)


if __name__ == "__main__":
    main()
