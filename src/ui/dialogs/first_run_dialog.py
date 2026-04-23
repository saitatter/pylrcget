from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout

from ui.spacing import SPACE_2, SPACE_3, SPACE_4, set_layout_spacing


class FirstRunDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to PyLrcGet")
        self.setModal(True)
        self.resize(520, 260)

        root = QVBoxLayout(self)
        set_layout_spacing(root, margins=SPACE_4, spacing=SPACE_3)

        title = QLabel("Set up your music library")
        title.setObjectName("OnboardingTitle")
        root.addWidget(title)

        body = QLabel(
            "PyLrcGet needs one or more music folders before it can scan tracks, download lyrics, "
            "and open the synced editor. Start by choosing the folders that contain your library."
        )
        body.setWordWrap(True)
        body.setObjectName("OnboardingBody")
        root.addWidget(body)

        steps = QLabel(
            "1. Choose your music folders.\n"
            "2. Save the folder list.\n"
            "3. Start the first library scan."
        )
        steps.setObjectName("OnboardingSteps")
        steps.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        root.addWidget(steps)

        buttons = QHBoxLayout()
        set_layout_spacing(buttons, spacing=SPACE_2)
        buttons.addStretch(1)

        self.btn_later = QPushButton("Set Up Later")
        self.btn_start = QPushButton("Choose Music Folders")
        self.btn_start.setDefault(True)

        self.btn_later.clicked.connect(self.reject)
        self.btn_start.clicked.connect(self.accept)

        buttons.addWidget(self.btn_later)
        buttons.addWidget(self.btn_start)
        root.addLayout(buttons)
