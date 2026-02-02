# src/player/player.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtCore import QUrl

from .mpv_ipc import MpvIpcBackend, MpvBackendConfig

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

        self.status = PlayerStatus.STOPPED
        self.track: NowPlaying | None = None

        # --- Backend selection ---
        self._use_mpv: bool = False
        self._mpv: Optional[MpvIpcBackend] = None

        # Qt fallback backend
        self.audio = QAudioOutput()
        self.media = QMediaPlayer()
        self.media.setAudioOutput(self.audio)

        # Default volume (0.0 - 1.0)
        self._volume_0_to_1: float = 0.7
        self.audio.setVolume(self._volume_0_to_1)

        # Qt signal forwarding
        self.media.positionChanged.connect(self.positionChanged.emit)
        self.media.durationChanged.connect(self.durationChanged.emit)
        self.media.playbackStateChanged.connect(self._on_qt_state_changed)
        self.media.mediaStatusChanged.connect(self._on_qt_media_status)

        # mpv polling (also used to emit signals)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(30)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

        self._last_pos_ms: int = -1
        self._last_dur_ms: int = -1

        # mpv end detection
        self._mpv_last_eof: bool = False

        # Try to start mpv backend; if it fails, we keep Qt fallback
        self._try_init_mpv()

    # ----------------------------
    # Backend init
    # ----------------------------

    def _try_init_mpv(self) -> None:
        """
        Prefer mpv (fast seeking). If mpv is missing or fails to start,
        we silently fall back to QMediaPlayer.
        """
        try:
            cfg = MpvBackendConfig(
                mpv_path=None,          # auto-detect bundled or PATH
                ipc_endpoint=None,      # auto endpoint
                start_paused=False,
                audio_only=True,
                keep_open=False,
                cwd=None,
            )
            backend = MpvIpcBackend(cfg)
            backend.start()
            backend.set_volume_0_to_1(self._volume_0_to_1)

            # Detect playback end via eof-reached
            backend.observe_property("eof-reached", self._on_mpv_eof_reached)

            self._mpv = backend
            self._use_mpv = True
        except Exception:
            self._mpv = None
            self._use_mpv = False

    # ----------------------------
    # Qt backend handlers
    # ----------------------------

    def _on_qt_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if self._use_mpv:
            return

        if state == QMediaPlayer.PlayingState:
            self._set_status(PlayerStatus.PLAYING)
        elif state == QMediaPlayer.PausedState:
            self._set_status(PlayerStatus.PAUSED)
        else:
            self._set_status(PlayerStatus.STOPPED)

    def _on_qt_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if self._use_mpv:
            return

        # Emit ended when playback reaches end
        if status == QMediaPlayer.EndOfMedia:
            self._set_status(PlayerStatus.STOPPED)
            self.ended.emit()

    # ----------------------------
    # mpv handlers
    # ----------------------------

    def _on_mpv_eof_reached(self, value) -> None:
        """
        mpv sets eof-reached=True at end-of-file.
        This callback may run on our message-processing thread; we only cache state here.
        """
        try:
            self._mpv_last_eof = bool(value)
        except Exception:
            self._mpv_last_eof = False

    # ----------------------------
    # Shared helpers
    # ----------------------------

    def _set_status(self, new_status: PlayerStatus) -> None:
        if self.status != new_status:
            self.status = new_status
            self.statusChanged.emit(self.status)

    def _poll(self) -> None:
        """
        Timer-driven pump:
          - For mpv: process IPC messages + emit position/duration + status + ended.
          - For Qt: no-op (Qt already emits signals), but we keep timer for symmetry.
        """
        if not self._use_mpv or not self._mpv:
            return

        # Pump mpv incoming messages
        try:
            self._mpv.process_messages(max_messages=500)
        except Exception:
            # If mpv dies, fall back to Qt (optional).
            # For now, we just stop using mpv.
            self._use_mpv = False
            self._mpv = None
            return

        # Emit position/duration changes
        pos_ms = self._mpv.position_ms()
        dur_ms = self._mpv.duration_ms()

        if pos_ms != self._last_pos_ms:
            self._last_pos_ms = pos_ms
            self.positionChanged.emit(pos_ms)

        if dur_ms != self._last_dur_ms:
            self._last_dur_ms = dur_ms
            self.durationChanged.emit(dur_ms)

        # Status
        if self._mpv.is_idle():
            self._set_status(PlayerStatus.STOPPED)
        else:
            self._set_status(PlayerStatus.PAUSED if self._mpv.is_paused() else PlayerStatus.PLAYING)

        # Ended event
        # eof-reached tends to briefly flip true at the end; emit once when it transitions false->true.
        if self._mpv_last_eof:
            self._mpv_last_eof = False
            self._set_status(PlayerStatus.STOPPED)
            self.ended.emit()

    # ----------------------------
    # Public API (unchanged)
    # ----------------------------

    def play_file(self, path: str, meta: NowPlaying | None = None) -> None:
        self.track = meta
        self.trackChanged.emit(self.track)

        if self._use_mpv and self._mpv:
            self._mpv.load(path, start_playing=True)
            self._set_status(PlayerStatus.PLAYING)
            return

        url = QUrl.fromLocalFile(path)
        self.media.setSource(url)
        self.media.play()

    def play(self) -> None:
        if self._use_mpv and self._mpv:
            self._mpv.play()
            self._set_status(PlayerStatus.PLAYING)
        else:
            self.media.play()

    def pause(self) -> None:
        if self._use_mpv and self._mpv:
            self._mpv.pause()
            self._set_status(PlayerStatus.PAUSED)
        else:
            self.media.pause()

    def stop(self) -> None:
        if self._use_mpv and self._mpv:
            self._mpv.stop_playback()
            self._set_status(PlayerStatus.STOPPED)
        else:
            self.media.stop()

    def toggle_play_pause(self) -> None:
        if self._use_mpv and self._mpv:
            if self._mpv.is_paused():
                self.play()
            else:
                self.pause()
        else:
            if self.media.playbackState() == QMediaPlayer.PlayingState:
                self.pause()
            else:
                self.play()

    def seek_ms(self, ms: int, *, exact: bool = False) -> None:
        ms = max(0, int(ms))

        if self._use_mpv and self._mpv:
            # For UI scrubbing: call seek_ms(..., exact=False) while dragging,
            # then seek_ms(..., exact=True) on slider release.
            self._mpv.seek_ms(ms, exact=exact)
            return

        self.media.setPosition(ms)

    def set_volume(self, volume_0_to_1: float) -> None:
        v = min(1.0, max(0.0, float(volume_0_to_1)))
        self._volume_0_to_1 = v

        if self._use_mpv and self._mpv:
            self._mpv.set_volume_0_to_1(v)
        else:
            self.audio.setVolume(v)

    # convenient getters for UI
    def position_ms(self) -> int:
        if self._use_mpv and self._mpv:
            return self._mpv.position_ms()
        return int(self.media.position())

    def duration_ms(self) -> int:
        if self._use_mpv and self._mpv:
            return self._mpv.duration_ms()
        return int(self.media.duration())

    # Optional helper if you want to show which backend is active in UI/logs
    def backend_name(self) -> str:
        return "mpv-ipc" if (self._use_mpv and self._mpv) else "qt-multimedia"

    def set_playback_speed(self, speed: float):
        speed = max(0.25, min(2.0, float(speed)))

        if self._use_mpv and self._mpv:
            self._mpv.set_property("speed", speed)
            return

        # Qt fallback (best-effort)
        try:
            self.media.setPlaybackRate(speed)
        except Exception:
            pass

    def playback_speed(self) -> float:
        if self._use_mpv and self._mpv:
            return float(self._mpv.get_property("speed") or 1.0)
        return 1.0
