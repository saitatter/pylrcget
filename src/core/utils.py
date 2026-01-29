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


def strip_timestamp(synced_lyrics: str) -> str:
    """
    Elimină timestamp-ul de tip [00:00.00] de la începutul unei linii.
    """
    plain_lyrics = re.sub(r"^\[.*?\]\s*", "", synced_lyrics)
    return plain_lyrics
