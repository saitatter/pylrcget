from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel


def display_album_name(value: str | None) -> str:
    text = (value or "").strip()
    if text.casefold() in {"", "album", "unknown album"}:
        return "N/A"
    return text


def display_artist_name(value: str | None) -> str:
    text = (value or "").strip()
    if text.casefold() in {"", "artist", "unknown artist"}:
        return "N/A"
    return text


def normalize_id_bucket(value) -> tuple[int, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(int(v) for v in value)
    return (int(value),)


def build_text_item(
    text: str,
    item_id: int | tuple[int, ...],
    *,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignVCenter,
) -> QStandardItem:
    item = QStandardItem(text)
    item.setEditable(False)
    bucket = normalize_id_bucket(item_id)
    item.setData(bucket[0] if len(bucket) == 1 else bucket, Qt.ItemDataRole.UserRole)
    item.setTextAlignment(align)
    return item


def find_display_row(model: QStandardItemModel, value: str, *, column: int = 0) -> int:
    for row in range(model.rowCount()):
        if model.index(row, column).data(Qt.ItemDataRole.DisplayRole) == value:
            return row
    return -1


def should_load_more(
    *,
    has_more_rows: bool,
    loading_more: bool,
    is_browser_visible: bool,
    value: int,
    maximum: int,
    threshold: int = 120,
) -> bool:
    if not has_more_rows or loading_more or not is_browser_visible:
        return False
    return value >= max(0, maximum - threshold)
