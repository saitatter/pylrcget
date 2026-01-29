# player/player.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


class PlayerStatus(Enum):
    STOPPED = auto()
    PLAYING = auto()
    PAUSED = auto()


@dataclass
class NowPlaying:
    track_id: int
    title: str
    artist: str | None
    path: str


class Player(QObject):
    # Optional signals if you want to update UI without polling
    statusChanged = Signal(object)      # PlayerStatus
    positionChanged = Signal(int)       # ms
    durationChanged = Signal(int)       # ms
    trackChanged = Signal(object)       # NowPlaying | None
    ended = Signal()

    def __init__(self):
        super().__init__()
        self.audio = QAudioOutput()
        self.media = QMediaPlayer()
        self.media.setAudioOutput(self.audio)

        self.status = PlayerStatus.STOPPED
        self.track: NowPlaying | None = None

        # forward signals
        self.media.positionChanged.connect(self.positionChanged.emit)
        self.media.durationChanged.connect(self.durationChanged.emit)
        self.media.playbackStateChanged.connect(self._on_state_changed)

        # default volume (0.0 - 1.0)
        self.audio.setVolume(0.7)

    def _on_state_changed(self, state: QMediaPlayer.PlaybackState):
        if state == QMediaPlayer.PlayingState:
            self.status = PlayerStatus.PLAYING
        elif state == QMediaPlayer.PausedState:
            self.status = PlayerStatus.PAUSED
        else:
            self.status = PlayerStatus.STOPPED
        self.statusChanged.emit(self.status)

    def play_file(self, path: str, meta: NowPlaying | None = None):
        url = QUrl.fromLocalFile(path)
        self.media.setSource(url)
        self.media.play()
        self.track = meta
        self.trackChanged.emit(self.track)

    def play(self):
        self.media.play()

    def pause(self):
        self.media.pause()

    def stop(self):
        self.media.stop()

    def toggle_play_pause(self):
        if self.media.playbackState() == QMediaPlayer.PlayingState:
            self.pause()
        else:
            self.play()

    def seek_ms(self, ms: int):
        self.media.setPosition(max(0, ms))

    def set_volume(self, volume_0_to_1: float):
        self.audio.setVolume(min(1.0, max(0.0, float(volume_0_to_1))))

    # convenient getters for UI
    def position_ms(self) -> int:
        return int(self.media.position())

    def duration_ms(self) -> int:
        return int(self.media.duration())
