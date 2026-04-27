import re
import unicodedata

def lower_lay_string(s: str) -> str:
    """Normalize a string via NFKD and strip combining (accent) characters."""
    normalized = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in normalized if not unicodedata.combining(c))


def collapse(s: str) -> str:
    """Collapse multiple whitespace characters into a single space and strip."""
    return re.sub(r'\s+', ' ', s).strip()


def prepare_input(input_str: str) -> str:
    # Normalize and strip accents
    prepared_input = lower_lay_string(input_str)

    # Replace special characters with space
    prepared_input = re.sub(r"[`~!@#$%^&*()_|+\-=?;:\",.<>{}\[\]\\\/]", " ", prepared_input)

    # Remove apostrophes (plain, left-single, right-single)
    prepared_input = re.sub(r"['‘’]", "", prepared_input)

    # Convert to lowercase
    prepared_input = prepared_input.lower()

    # Collapse multiple spaces
    prepared_input = collapse(prepared_input)

    return prepared_input


LRC_TS_RE = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\]")
_LRC_TS_RE = LRC_TS_RE  # internal alias for backward compat
_LRC_META_PREFIXES = ("[ar:", "[ti:", "[al:", "[by:", "[offset:", "[au:")


def plain_text_from_lrc(lrc_text: str) -> str:
    """Strip timestamps and metadata tags from synced LRC, returning plain text."""
    lines: list[str] = []
    for raw in lrc_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if any(line.startswith(p) for p in _LRC_META_PREFIXES):
            continue
        if not _LRC_TS_RE.search(line):
            continue
        text = _LRC_TS_RE.sub("", line).strip()
        lines.append(text)
    return "\n".join(lines).rstrip()


def _ts_to_ms(mm: str, ss: str, frac: str | None) -> int:
    m = int(mm)
    s = int(ss)
    if frac is None:
        ms = 0
    else:
        frac = frac.strip()
        if len(frac) == 1:
            ms = int(frac) * 100
        elif len(frac) == 2:
            ms = int(frac) * 10
        else:
            ms = int(frac[:3])
    return (m * 60 + s) * 1000 + ms


def ms_to_ts(ms: int) -> str:
    """Format milliseconds as mm:ss.xx (centiseconds)."""
    if ms < 0:
        ms = 0
    total_s = ms // 1000
    m = total_s // 60
    s = total_s % 60
    cs = (ms % 1000) // 10
    return f"{m:02d}:{s:02d}.{cs:02d}"


def parse_ts_str(ts: str) -> int | None:
    """
    Accepts:
      - mm:ss
      - mm:ss.xx
      - mm:ss.xxx
    """
    t = (ts or "").strip()
    if not t:
        return None
    t = t.replace(",", ".")
    m = re.match(r"^(\d+):(\d{1,2})(?:\.(\d{1,3}))?$", t)
    if not m:
        return None
    if int(m.group(2)) >= 60:
        return None
    try:
        return _ts_to_ms(m.group(1), m.group(2), m.group(3))
    except (ValueError, TypeError):
        return None


def parse_lrc(lrc_text: str) -> list[tuple[int, str]]:
    """
    Returns list of (time_ms, text) sorted by time.
    Supports multiple timestamps per line.
    Ignores metadata tags like [ar:], [ti:], etc.
    """
    out: list[tuple[int, str]] = []
    if not lrc_text:
        return out

    for raw_line in lrc_text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if any(line.startswith(p) for p in _LRC_META_PREFIXES):
            continue

        matches = list(_LRC_TS_RE.finditer(line))
        if not matches:
            continue

        text = _LRC_TS_RE.sub("", line).strip()

        for m in matches:
            t = _ts_to_ms(m.group(1), m.group(2), m.group(3))
            out.append((t, text))

    out.sort(key=lambda x: x[0])
    return out
