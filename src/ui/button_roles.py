from __future__ import annotations

from typing import Literal

from PySide6.QtWidgets import QAbstractButton

ButtonRole = Literal["primary", "secondary", "ghost", "danger", "icon", "segmented", "chip"]


def set_button_role(button: QAbstractButton, role: ButtonRole) -> None:
    """Apply a semantic button role and refresh its QSS immediately."""
    button.setProperty("buttonRole", role)
    style = button.style()
    style.unpolish(button)
    style.polish(button)
    button.update()
