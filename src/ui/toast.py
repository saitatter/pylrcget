from PySide6.QtWidgets import QFrame, QLabel, QHBoxLayout
from PySide6.QtCore import Qt, QTimer

class Toast(QFrame):
    def __init__(self, parent, text: str, kind: str = "info", ms: int = 5000):
        super().__init__(parent)
        self.setWindowFlags(Qt.ToolTip)  # floats above
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        self.label = QLabel(text)
        layout = QHBoxLayout(self)
        layout.addWidget(self.label)

        self.setObjectName(f"toast-{kind}")
        self.setStyleSheet("""
        QFrame { border-radius: 10px; padding: 10px 12px; background: #222; color: #fff; }
        QFrame#toast-success { background: #1f6f3b; }
        QFrame#toast-warn { background: #7a5b12; }
        QFrame#toast-error { background: #7a1b1b; }
        """)

        QTimer.singleShot(ms, self.close)

    def show_bottom_right(self, margin=16):
        p = self.parentWidget()
        if not p:
            self.show()
            return
        self.adjustSize()
        x = p.x() + p.width() - self.width() - margin
        y = p.y() + p.height() - self.height() - margin
        self.move(x, y)
        self.show()
