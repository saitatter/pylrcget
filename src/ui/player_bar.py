from __future__ import annotations

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.spacing import SPACE_2, SPACE_3, set_layout_spacing
from ui.style_loader import load_stylesheet


def _fmt(ms: int) -> str:
    ms = max(0, int(ms))
    s = ms // 1000
    m = s // 60
    s = s % 60
    return f"{m}:{s:02d}"


def _svg_icon(path_d: str, size: int = 20, color: str = "#e5e7eb") -> QIcon:
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24">
      <path d="{path_d}" fill="{color}"/>
    </svg>
    """.strip()

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)

    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()

    return QIcon(pm)


SVG_PREV = "M6 18V6h2v12H6zm3.5-6L18 6v12l-8.5-6z"
SVG_NEXT = "M16 6v12h2V6h-2zM6 18l8.5-6L6 6v12z"
SVG_PLAY = "M8 5v14l11-7L8 5z"
SVG_PAUSE = "M6 5h4v14H6V5zm8 0h4v14h-4V5z"


class SeekSlider(QSlider):
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            value = QStyle.sliderValueFromPosition(
                self.minimum(),
                self.maximum(),
                int(event.position().x()),
                max(1, self.width()),
            )
            self.setValue(value)
            self.sliderMoved.emit(value)
        super().mousePressEvent(event)


class PlayerBar(QWidget):
    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player

        self._dragging = False
        self._duration_ms = 0
        self._is_playing = False
        self._backend_name = self.player.backend_name() if self.player and hasattr(self.player, "backend_name") else "unknown"

        self.setObjectName("PlayerBar")

        root = QHBoxLayout(self)
        set_layout_spacing(root, margins=(SPACE_3, SPACE_2, SPACE_3, SPACE_2), spacing=SPACE_2)

        left_panel = QWidget()
        left_panel.setObjectName("PlayerMeta")
        left_layout = QVBoxLayout(left_panel)
        set_layout_spacing(left_layout, margins=SPACE_2, spacing=4)

        badges = QHBoxLayout()
        set_layout_spacing(badges, spacing=SPACE_2)

        self.lbl_status = QLabel("Stopped")
        self.lbl_status.setObjectName("PlaybackStatus")
        badges.addWidget(self.lbl_status)

        self.lbl_backend = QLabel(self._backend_name.upper())
        self.lbl_backend.setObjectName("BackendBadge")
        badges.addWidget(self.lbl_backend)
        badges.addStretch(1)

        self.lbl_title = QLabel("Nothing playing")
        self.lbl_title.setObjectName("NowPlaying")
        self.lbl_title.setMinimumWidth(240)
        self.lbl_title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_title.setWordWrap(False)

        self.lbl_subtitle = QLabel("Choose a track to start playback")
        self.lbl_subtitle.setObjectName("NowPlayingMeta")

        left_layout.addLayout(badges)
        left_layout.addWidget(self.lbl_title)
        left_layout.addWidget(self.lbl_subtitle)

        center_panel = QWidget()
        center_panel.setObjectName("PlayerCenter")
        center_layout = QVBoxLayout(center_panel)
        set_layout_spacing(center_layout, margins=SPACE_2, spacing=SPACE_2)

        controls_row = QHBoxLayout()
        set_layout_spacing(controls_row, spacing=SPACE_2)
        controls_row.addStretch(1)

        self.btn_prev = QToolButton()
        self.btn_prev.setObjectName("BtnPrev")
        self.btn_prev.setToolTip("Previous")

        self.btn_play = QToolButton()
        self.btn_play.setObjectName("BtnPlay")
        self.btn_play.setToolTip("Play/Pause")

        self.btn_next = QToolButton()
        self.btn_next.setObjectName("BtnNext")
        self.btn_next.setToolTip("Next")

        self._icons = {
            "prev": _svg_icon(SVG_PREV, 20, "#e5e7eb"),
            "next": _svg_icon(SVG_NEXT, 20, "#e5e7eb"),
            "play": _svg_icon(SVG_PLAY, 22, "#e5e7eb"),
            "pause": _svg_icon(SVG_PAUSE, 22, "#e5e7eb"),
        }
        self.btn_prev.setIcon(self._icons["prev"])
        self.btn_next.setIcon(self._icons["next"])
        self.btn_play.setIcon(self._icons["play"])
        self.btn_prev.setIconSize(QSize(20, 20))
        self.btn_next.setIconSize(QSize(20, 20))
        self.btn_play.setIconSize(QSize(22, 22))

        controls_row.addWidget(self.btn_prev)
        controls_row.addWidget(self.btn_play)
        controls_row.addWidget(self.btn_next)
        controls_row.addStretch(1)
        center_layout.addLayout(controls_row)

        progress_row = QHBoxLayout()
        set_layout_spacing(progress_row, spacing=SPACE_2)

        self.lbl_time = QLabel("0:00")
        self.lbl_time.setObjectName("TimeLabel")
        self.lbl_dur = QLabel("0:00")
        self.lbl_dur.setObjectName("TimeLabel")

        self.slider = SeekSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("PlayerSlider")
        self.slider.setRange(0, 0)
        self.slider.setSingleStep(1000)
        self.slider.setPageStep(5000)
        self.slider.setMinimumHeight(28)

        progress_row.addWidget(self.lbl_time)
        progress_row.addWidget(self.slider, 1)
        progress_row.addWidget(self.lbl_dur)
        center_layout.addLayout(progress_row)

        right_panel = QWidget()
        right_panel.setObjectName("PlayerExtras")
        right_layout = QVBoxLayout(right_panel)
        set_layout_spacing(right_layout, margins=SPACE_2, spacing=SPACE_2)

        self.lbl_speed = QLabel("Speed")
        self.lbl_speed.setObjectName("MetaLabel")

        self.cmb_speed = QComboBox()
        self.cmb_speed.setObjectName("SpeedCombo")
        self.cmb_speed.setToolTip("Playback speed")
        self._speed_items = [("1.0x", 1.0), ("0.75x", 0.75), ("0.5x", 0.5), ("0.25x", 0.25)]
        for label, speed in self._speed_items:
            self.cmb_speed.addItem(label, speed)
        self.cmb_speed.setCurrentIndex(0)

        right_layout.addWidget(self.lbl_speed)
        right_layout.addWidget(self.cmb_speed)
        right_layout.addStretch(1)

        root.addWidget(left_panel, 3)
        root.addWidget(center_panel, 4)
        root.addWidget(right_panel, 0)

        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.cmb_speed.currentIndexChanged.connect(self._on_speed_changed)

        if self.player:
            self.player.trackChanged.connect(self._on_track_changed)
            self.player.statusChanged.connect(self._on_status_changed)
            self.player.positionChanged.connect(self._on_position)
            if hasattr(self.player, "durationChanged"):
                self.player.durationChanged.connect(self._on_duration)
            self.btn_play.clicked.connect(self.player.toggle_play_pause)

        self._apply_styles()
        self._sync_speed_from_player()
        self._update_status_badge("stopped")

    def set_prev_next_handlers(self, prev_fn, next_fn):
        self.btn_prev.clicked.connect(prev_fn)
        self.btn_next.clicked.connect(next_fn)

    def _on_speed_changed(self, _index: int):
        if not self.player:
            return
        speed = float(self.cmb_speed.currentData() or 1.0)
        if hasattr(self.player, "set_playback_speed"):
            try:
                self.player.set_playback_speed(speed)
            except Exception:
                pass

    def _sync_speed_from_player(self):
        if not self.player or not hasattr(self.player, "playback_speed"):
            return
        try:
            speed = float(self.player.playback_speed() or 1.0)
        except Exception:
            speed = 1.0

        for idx in range(self.cmb_speed.count()):
            if abs(float(self.cmb_speed.itemData(idx)) - speed) < 0.001:
                self.cmb_speed.setCurrentIndex(idx)
                return

    def _on_slider_pressed(self):
        self._dragging = True

    def _on_slider_moved(self, value: int):
        self.lbl_time.setText(_fmt(value))

    def _on_slider_released(self):
        self._dragging = False
        if self.player:
            self.player.seek_ms(int(self.slider.value()), exact=True)

    def _on_track_changed(self, now_playing):
        if now_playing:
            artist = now_playing.artist or "Unknown Artist"
            title = now_playing.title or "Unknown"
            self.lbl_title.setText(title)
            self.lbl_subtitle.setText(artist)
        else:
            self.lbl_title.setText("Nothing playing")
            self.lbl_subtitle.setText("Choose a track to start playback")
            self.slider.setValue(0)
            self.lbl_time.setText("0:00")
            self.lbl_dur.setText("0:00")
            self._set_playing(False)
            self._update_status_badge("stopped")

    def _on_status_changed(self, status):
        name = getattr(status, "name", str(status)).lower()
        self._set_playing("play" in name)
        self._update_status_badge(name)

    def _set_playing(self, playing: bool):
        self._is_playing = bool(playing)
        if self._is_playing:
            self.btn_play.setIcon(self._icons["pause"])
            self.btn_play.setToolTip("Pause")
        else:
            self.btn_play.setIcon(self._icons["play"])
            self.btn_play.setToolTip("Play")

    def _on_duration(self, ms: int):
        self._duration_ms = int(ms)
        self.slider.setRange(0, max(0, int(ms)))
        self.lbl_dur.setText(_fmt(int(ms)))

    def _on_position(self, ms: int):
        if self._dragging:
            return
        self.lbl_time.setText(_fmt(int(ms)))
        self.slider.setValue(int(ms))

    def _update_status_badge(self, status_name: str):
        status_name = (status_name or "stopped").lower()
        label = "Playing" if "play" in status_name else "Paused" if "pause" in status_name else "Stopped"
        self.lbl_status.setText(label)
        self.lbl_status.setProperty("playbackState", status_name)
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)
        self.lbl_status.update()

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("player_bar.qss"))
