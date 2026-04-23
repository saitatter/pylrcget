import re
import unicodedata

def lower_lay_string(s: str) -> str:
    """
    Echivalentul funcției `secular::lower_lay_string` din Rust.
    Aceasta normalizează string-ul și elimină accentele.
    """
    normalized = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in normalized if not unicodedata.combining(c))


def collapse(s: str) -> str:
    """
    Echivalentul funcției `collapse::collapse` din Rust.
    Combină multiple spații într-un singur spațiu și taie spațiile la început și sfârșit.
    """
    return re.sub(r'\s+', ' ', s).strip()


def prepare_input(input_str: str) -> str:
    # Normalizează și elimină accentele
    prepared_input = lower_lay_string(input_str)

    # Înlocuiește caractere speciale cu spațiu
    prepared_input = re.sub(r"[`~!@#$%^&*()_|+\-=?;:\",.<>{}\[\]\\\/]", " ", prepared_input)

    # Elimină apostroafe
    prepared_input = re.sub(r"[’']", "", prepared_input)

    # Transformă totul în lowercase
    prepared_input = prepared_input.lower()

    # Collapse multiple spații
    prepared_input = collapse(prepared_input)

    return prepared_input


_LRC_TS_RE = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\]")
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
