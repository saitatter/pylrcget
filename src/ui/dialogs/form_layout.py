from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from ui.spacing import SPACE_2, SPACE_3

FORM_LABEL_WIDTH = 148
FORM_CONTROL_HEIGHT = 32


def _set_control_baseline(widget: QWidget) -> None:
    if isinstance(widget, (QComboBox, QLineEdit, QPushButton, QSpinBox, QKeySequenceEdit)):
        widget.setMinimumHeight(max(widget.minimumHeight(), FORM_CONTROL_HEIGHT))


def configure_form_grid(
    layout: QGridLayout,
    *,
    label_columns: tuple[int, ...] = (0,),
    label_width: int = FORM_LABEL_WIDTH,
) -> None:
    """Give settings grids one predictable label/control rhythm."""
    layout.setContentsMargins(SPACE_3, SPACE_3, SPACE_3, SPACE_3)
    layout.setHorizontalSpacing(SPACE_3)
    layout.setVerticalSpacing(SPACE_2)

    for index in range(layout.count()):
        item = layout.itemAt(index)
        _row, column, _row_span, column_span = layout.getItemPosition(index)
        widget = item.widget()
        if widget is None:
            continue
        _set_control_baseline(widget)
        if isinstance(widget, QLabel) and column in label_columns and column_span == 1:
            widget.setMinimumWidth(label_width)
            widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    for column in label_columns:
        layout.setColumnMinimumWidth(column, label_width)
    if layout.columnCount() > 1:
        layout.setColumnStretch(1, 1)


def configure_form_layout(
    layout: QFormLayout,
    *,
    label_width: int = FORM_LABEL_WIDTH,
) -> None:
    """Align a dialog form and keep its controls on a common baseline."""
    layout.setContentsMargins(SPACE_3, SPACE_3, SPACE_3, SPACE_3)
    layout.setHorizontalSpacing(SPACE_3)
    layout.setVerticalSpacing(SPACE_2)
    layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
    layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
    layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

    for row in range(layout.rowCount()):
        label_item = layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
        field_item = layout.itemAt(row, QFormLayout.ItemRole.FieldRole)
        label = label_item.widget() if label_item is not None else None
        field = field_item.widget() if field_item is not None else None
        if isinstance(label, QLabel):
            label.setMinimumWidth(label_width)
        if field is not None:
            _set_control_baseline(field)
