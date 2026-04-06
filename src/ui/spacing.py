from __future__ import annotations

from PySide6.QtWidgets import QLayout

from ui.theme_tokens import SPACE_TOKENS


SPACE_1 = int(SPACE_TOKENS["space-1"].replace("px", ""))
SPACE_2 = int(SPACE_TOKENS["space-2"].replace("px", ""))
SPACE_3 = int(SPACE_TOKENS["space-3"].replace("px", ""))
SPACE_4 = int(SPACE_TOKENS["space-4"].replace("px", ""))


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
