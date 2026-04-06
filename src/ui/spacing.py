from __future__ import annotations

from PySide6.QtWidgets import QLayout


SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16


def set_layout_spacing(
    layout: QLayout,
    *,
    margins: int | tuple[int, int, int, int] | None = None,
    spacing: int | None = None,
) -> None:
    if margins is not None:
        if isinstance(margins, int):
            layout.setContentsMargins(margins, margins, margins, margins)
        else:
            left, top, right, bottom = margins
            layout.setContentsMargins(left, top, right, bottom)
    if spacing is not None:
        layout.setSpacing(spacing)
