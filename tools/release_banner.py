"""Render a release's personalized studio artwork and freeze its data snapshot."""

from __future__ import annotations

import argparse
import base64
import functools
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs/assets/release-banner"
BANNER_BRANCH = "release-banners"


@dataclass(frozen=True)
class Slot:
    box: tuple[int, int, int, int]
    size: int
    color: str = "#ebe8dc"
    hand: bool = False
    lines: int = 1
    angle: float = 0
    align: str = "left"


SLOTS = {
    "version": Slot((515, 168, 1100, 225), 45, "#a4ed70"),
    "preview": Slot((1000, 188, 1145, 219), 20, "#f6ce79", align="right"),
    "date": Slot((1187, 132, 1280, 195), 24, "#262638", True, 2, -6, "center"),
    "open_issues": Slot((250, 423, 371, 492), 29, "#63352b", True, 2, 2, "center"),
    "stars": Slot((1342, 549, 1494, 588), 27, "#35281f", True, align="center"),
    "previous": Slot((294, 693, 521, 725), 22, align="center"),
    "next": Slot((294, 732, 521, 763), 22, "#a4ed70", align="center"),
    "commits": Slot((940, 685, 1046, 719), 31, "#252638", True, align="right"),
    "contributor_count": Slot((940, 741, 1046, 774), 31, "#252638", True, align="right"),
    "issues_addressed": Slot((940, 794, 1046, 827), 31, "#252638", True, align="right"),
    **{f"item_{i + 1}": Slot((515, 247 + 43 * i, 1180, 281 + 43 * i), 27) for i in range(6)},
    **{f"person_{i + 1}": Slot((1140, 698 + 36 * i, 1402, 733 + 36 * i), 27, "#252638", True) for i in range(4)},
}


@functools.cache
def font(size: int, hand: bool):
    return ImageFont.truetype(str(ASSETS / ("PatrickHand-Regular.ttf" if hand else "JetBrainsMono.ttf")), size)


def fit_text(text: str, slot: Slot):
    width, height = slot.box[2] - slot.box[0], slot.box[3] - slot.box[1]
    for size in range(slot.size, 13, -1):
        face = font(size, slot.hand)
        rows = []
        for paragraph in str(text).splitlines():
            current = ""
            for word in paragraph.split():
                if current and face.getlength(current + " " + word) <= width:
                    current += " " + word
                else:
                    if current:
                        rows.append(current)
                    current = word
            rows.append(current)
        if rows and len(rows) <= slot.lines and max(face.getlength(row) for row in rows) <= width and size * 1.22 * len(rows) <= height:
            return face, "\n".join(rows)
    # Long names remain inside the card, even when a contributor uses no spaces.
    shortened = " ".join(str(text).split())
    while shortened and face.getlength(shortened + "…") > width:
        shortened = shortened[:-1]
    return face, shortened + "…"


def item_text(item: str | dict) -> str:
    return item["text"] if isinstance(item, dict) else item


def emoji_rows(data: dict) -> bool:
    return data.get("schema_version", 1) >= 3 or any(isinstance(item, dict) for item in data["items"])


@functools.cache
def emoji_image(emoji: str):
    code = "_".join(f"{ord(char):x}" for char in emoji if char != "\ufe0f")
    if not re.fullmatch(r"[0-9a-f]+(?:_[0-9a-f]+)*", code):
        raise ValueError("An emoji code point is required")
    with Image.open(ASSETS / "emoji" / f"emoji_u{code}.png") as source:
        return source.convert("RGBA").resize((34, 34), Image.Resampling.LANCZOS)


def fields(data: dict) -> dict[str, str]:
    people = list(data.get("contributor_names", []))
    if len(people) > 4:
        people = people[:3] + [f"+{len(people) - 3} others"]
    values = {
        "version": data["tag"], "date": data["date"], "previous": data.get("previous") or "First release",
        "next": data["tag"], "preview": "PREVIEW" if data.get("preview") else "",
        "open_issues": f"{data.get('open_issues', '—')} open\nissues",
        "stars": f"{data.get('stars', '—')} stars", "commits": str(data["commits"]),
        "contributor_count": str(data["contributors"]), "issues_addressed": str(data["issues_addressed"]),
        **{f"item_{i + 1}": (item_text(item) if emoji_rows(data) else f"{i + 1:02d}  {item_text(item)}") for i, item in enumerate(data["items"][:6])},
        **{f"person_{i + 1}": name for i, name in enumerate(people)},
    }
    if not people:
        values["person_1"] = "Community release"
    return values


def render(data: dict, out: Path) -> None:
    canvas = Image.open(ASSETS / "template.png").convert("RGBA")
    # Use the shipped application artwork verbatim, never an AI interpretation.
    with Image.open(ROOT / "src/ui/assets/app-icon.ico") as source_logo:
        logo = source_logo.ico.getimage((256, 256)).convert("RGBA")
    logo = logo.resize((100, 100), Image.Resampling.LANCZOS)
    canvas.alpha_composite(logo, (104, 15))
    for key, text in fields(data).items():
        if not text:
            continue
        slot = SLOTS[key]
        if key.startswith("item_") and emoji_rows(data):
            item = data["items"][int(key.removeprefix("item_")) - 1]
            icon = item.get("emoji", "\U0001f6e0\ufe0f") if isinstance(item, dict) else "\U0001f6e0\ufe0f"
            canvas.alpha_composite(emoji_image(icon), (slot.box[0], slot.box[1]))
            slot = Slot((slot.box[0] + 50, *slot.box[1:]), slot.size)
        face, content = fit_text(text, slot)
        x0, y0, x1, y1 = slot.box
        layer = Image.new("RGBA", (x1 - x0 + 30, y1 - y0 + 30))
        draw = ImageDraw.Draw(layer)
        bounds = draw.multiline_textbbox((0, 0), content, font=face, spacing=1)
        left = 15 + {"left": 0, "center": (x1 - x0 - bounds[2]) / 2, "right": x1 - x0 - bounds[2]}[slot.align]
        top = 15 + (y1 - y0 - (bounds[3] - bounds[1])) / 2 - bounds[1]
        draw.multiline_text((left, top), content, font=face, fill=slot.color, spacing=1, align=slot.align)
        if slot.angle:
            layer = layer.rotate(slot.angle, resample=Image.Resampling.BICUBIC)
        canvas.alpha_composite(layer, (x0 - 15, y0 - 15))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out, "WEBP", quality=92, method=6)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def gh(method: str, endpoint: str, payload: dict | None = None, *, accept: str | None = None):
    if method == "GET" and payload:
        endpoint += ("&" if "?" in endpoint else "?") + urlencode(payload)
        payload = None
    command = ["gh", "api", "--method", method, endpoint]
    if accept:
        command += ["-H", f"Accept: {accept}"]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None, text=True, encoding="utf-8", capture_output=True, check=True)
    return json.loads(result.stdout)


def _pages(endpoint: str, *, payload: dict | None = None, accept: str | None = None) -> list:
    result = []
    page = 1
    while True:
        rows = gh("GET", endpoint, {**(payload or {}), "per_page": 100, "page": page}, accept=accept)
        result.extend(rows)
        if len(rows) < 100:
            return result
        page += 1


@functools.cache
def repository_history(repo: str) -> tuple[list, list, list]:
    """Fetch surviving stars and issue transitions once for historical rendering."""
    issues = [row for row in _pages(f"repos/{repo}/issues", payload={"state": "all"}) if "pull_request" not in row]
    issue_ids = {row["id"] for row in issues}
    events = [
        row for row in _pages(f"repos/{repo}/issues/events")
        if row.get("event") in {"closed", "reopened"} and row.get("issue", {}).get("id") in issue_ids
    ]
    stars = _pages(f"repos/{repo}/stargazers", accept="application/vnd.github.star+json")
    return issues, events, stars


def stats_at(repo: str, moment: str) -> tuple[int, int]:
    """Reconstruct open issues and surviving stars at an instant, including reopenings.

    GitHub cannot recover withdrawn stars. Their absence must not be described
    as an exact historical star count. Pull requests never enter issue counts.
    """
    def instant(value: str):
        return datetime.fromisoformat(value).astimezone(UTC)

    cutoff = instant(moment)
    issues, events, stars = repository_history(repo)
    states = {row["id"]: True for row in issues if instant(row["created_at"]) <= cutoff}
    with_events = {row["issue"]["id"] for row in events}
    # Imported/older closed issues may have no transition event available.
    for row in issues:
        if row["id"] in states and row["id"] not in with_events and row.get("closed_at"):
            states[row["id"]] = instant(row["closed_at"]) > cutoff
    for event in sorted(events, key=lambda row: instant(row["created_at"])):
        issue_id = event["issue"]["id"]
        if issue_id in states and instant(event["created_at"]) <= cutoff:
            states[issue_id] = event["event"] == "reopened"
    return sum(states.values()), sum(instant(row["starred_at"]) <= cutoff for row in stars)


@functools.cache
def _commit_author(repo: str, sha: str) -> dict:
    return gh("GET", f"repos/{repo}/commits/{sha}").get("author") or {}


def contributor_names(repo: str, revision: str) -> list[str]:
    """Credit human GitHub accounts once even when Git author names differ."""
    names: dict[str, str] = {}
    seen_emails = set()
    for row in git("log", "--reverse", "--no-merges", "--format=%H%x09%aN%x09%aE", revision).splitlines():
        sha, name, email = row.split("\t", 2)
        if name.lower().endswith("[bot]") or email in seen_emails:
            continue
        seen_emails.add(email)
        login = re.fullmatch(r"(?:\d+\+)?([\w-]+)@users\.noreply\.github\.com", email)
        account = {"login": login[1]} if login else _commit_author(repo, sha)
        if account.get("type") == "Bot":
            continue
        credit = "@" + account["login"] if account.get("login") else name
        names.setdefault(credit.casefold(), credit)
    return list(names.values())


def release_data(repo: str, tag: str, *, preview: bool = False) -> dict:
    ref = "HEAD" if preview else tag
    git("rev-parse", "--verify", ref)
    try:
        previous = git("describe", "--tags", "--abbrev=0", ref if preview else f"{tag}^")
    except subprocess.CalledProcessError:
        previous = None
    revision = f"{previous}..{ref}" if previous else ref
    subjects = git("log", "--no-merges", "--format=%s", revision).splitlines()
    bodies = git("log", "--no-merges", "--format=%B", revision)
    issues = set(re.findall(r"(?i)\b(?:fix(?:es|ed)?|clos(?:e[sd]?)|resolv(?:e[sd]?))\s+#(\d+)", bodies))
    names = contributor_names(repo, revision)
    metadata = json.loads((ROOT / "docs/release-summaries.json").read_text(encoding="utf-8")).get(tag, {})
    items = metadata.get("items") or [re.sub(r"^\w+(?:\([^)]*\))?!?:\s*", "", s).capitalize() for s in subjects if s.startswith(("feat", "fix"))][:6]
    publication = datetime.now(UTC).isoformat() if preview else gh("GET", f"repos/{repo}/releases/tags/{tag}")["published_at"]
    open_issues, stars = stats_at(repo, publication)
    return {
        "schema_version": 3, "repo": repo, "tag": tag, "preview": preview,
        "date": datetime.fromisoformat(publication).strftime("%d %b\n%Y"),
        "published_at": publication, "metrics_captured_at": datetime.now(UTC).isoformat(),
        "metrics_as_of": publication,
        "artwork_revision": "emoji",
        "statistics_basis": {"open_issues": "issue_state_transitions_at_publication", "stars": "surviving_stars_given_by_publication"},
        "previous": previous, "commit": git("rev-parse", ref), "items": items,
        "commits": len(subjects), "contributors": len(names), "contributor_names": names,
        "issues_addressed": len(issues), "issue_numbers": sorted(issues, key=int),
        "stars": stars, "open_issues": open_issues,
    }


def publish(repo: str, tag: str, image_path: Path, data: dict, *, revision: str | None = None) -> str:
    """Append artwork and its snapshot to an orphan branch; never overwrite a tag."""
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:[-.\w]*)?", tag):
        raise ValueError("A published version tag is required for banner publication")
    if data.get("preview"):
        raise ValueError("Preview banners cannot be published")
    revision = revision if revision is not None else data.get("artwork_revision")
    if revision is not None and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", revision):
        raise ValueError("An artwork revision must be a short lowercase slug")
    stem = f"{tag}-{revision}" if revision else tag
    try:
        head = gh("GET", f"repos/{repo}/git/ref/heads/{BANNER_BRANCH}")["object"]["sha"]
    except subprocess.CalledProcessError as exc:
        if "404" not in exc.stderr:
            raise
        head = None
    filename = f"{stem}.webp"
    base_tree = None
    if head:
        tree = gh("GET", f"repos/{repo}/git/trees/{head}")
        if any(item["path"] == filename for item in tree["tree"]):
            commit = gh("GET", f"repos/{repo}/commits?sha={BANNER_BRANCH}&path={filename}&per_page=1")[0]["sha"]
            return f"https://raw.githubusercontent.com/{repo}/{commit}/{filename}"
        base_tree = tree["sha"]
    entries = []
    for name, content in ((filename, image_path.read_bytes()), (f"{stem}.json", json.dumps(data, indent=2).encode("utf-8"))):
        blob = gh("POST", f"repos/{repo}/git/blobs", {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"})
        entries.append({"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    payload = {"tree": entries}
    if base_tree:
        payload["base_tree"] = base_tree
    tree = gh("POST", f"repos/{repo}/git/trees", payload)
    commit = gh("POST", f"repos/{repo}/git/commits", {"message": f"docs(release): add {tag} artwork", "tree": tree["sha"], "parents": [head] if head else []})["sha"]
    if head:
        gh("PATCH", f"repos/{repo}/git/refs/heads/{BANNER_BRANCH}", {"sha": commit, "force": False})
    else:
        gh("POST", f"repos/{repo}/git/refs", {"ref": f"refs/heads/{BANNER_BRANCH}", "sha": commit})
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{filename}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="saitatter/pylrcget")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--data", type=Path, help="Render a saved snapshot without GitHub access")
    parser.add_argument("--preview", action="store_true", help="Use local HEAD without requiring a published tag")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="Override a snapshot field; use item_1 through item_6 for highlights")
    args = parser.parse_args()
    data = json.loads(args.data.read_text(encoding="utf-8")) if args.data else release_data(args.repo, args.tag, preview=args.preview)
    for override in args.set:
        key, sep, value = override.partition("=")
        if not sep:
            parser.error("Overrides must use KEY=VALUE")
        if re.fullmatch(r"(?:item|emoji)_[1-6]", key):
            index = int(key[-1]) - 1
            while len(data["items"]) <= index:
                data["items"].append({"text": "", "emoji": "\U0001f6e0\ufe0f"})
            current = data["items"][index]
            item = dict(current) if isinstance(current, dict) else {"text": current, "emoji": "\U0001f6e0\ufe0f"}
            item["emoji" if key.startswith("emoji_") else "text"] = value
            data["items"][index] = item
        elif key in data:
            data[key] = int(value) if key in {"commits", "contributors", "issues_addressed", "stars", "open_issues"} else value
        else:
            parser.error(f"Unknown snapshot field: {key}")
    render(data, args.out)
    args.out.with_suffix(".json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
