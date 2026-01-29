from __future__ import annotations
from dataclasses import dataclass
from PySide6.QtCore import QObject, Signal, Slot

@dataclass(frozen=True)
class Notify:
    message: str
    notify_type: str = "info"   # info/success/warn/error

class AppState(QObject):
    notification = Signal(object)   # emits Notify
    status_changed = Signal(str)    # generic status text
    scan_progress = Signal(int, int)  # current, total
    track_changed = Signal(object)  # emits TrackMeta/whatever you use

    def __init__(self):
        super().__init__()
        self.db = None
        self.player = None
        self.cancel_requested = False
        self.queued_notifications: list[Notify] = []

    @Slot(str, str)
    def notify(self, message: str, notify_type: str = "info"):
        self.notification.emit(Notify(message=message, notify_type=notify_type))
