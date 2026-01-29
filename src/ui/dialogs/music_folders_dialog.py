from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QListWidget, QPushButton,
    QFileDialog, QHBoxLayout, QMessageBox
)

from db.database import get_directories, set_directories

class MusicFoldersDialog(QDialog):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Music Folders")
        self.resize(500, 400)
        self.app_state = app_state

        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add Folder")
        self.remove_btn = QPushButton("Remove Selected")
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.remove_btn)
        layout.addLayout(btn_layout)

        self.save_btn = QPushButton("Save")
        layout.addWidget(self.save_btn)

        # load existing folders
        self._load()

        # connect
        self.add_btn.clicked.connect(self.add_folder)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.save_btn.clicked.connect(self.save)

    def _load(self):
        self.list_widget.clear()
        for d in get_directories(self.app_state.db):
            self.list_widget.addItem(d)

    def add_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Music Folder"
        )
        if not path:
            return

        # avoid duplicates
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).text() == path:
                return

        self.list_widget.addItem(path)

    def remove_selected(self):
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))

    def save(self):
        folders = [
            self.list_widget.item(i).text()
            for i in range(self.list_widget.count())
        ]

        if not folders:
            QMessageBox.warning(
                self, "No folders", "Please add at least one music folder."
            )
            return

        set_directories(self.app_state.db, folders)
        self.accept()
