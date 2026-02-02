# ui/player_bar.py
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QToolButton, QSlider, QComboBox
from PySide6.QtCore import QByteArray
from PySide6.QtSvg import QSvgRenderer

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

    p = QPainter(pm)
    renderer.render(p)
    p.end()

    return QIcon(pm)


# Simple, clean icons (Material-ish)
SVG_PREV = "M6 18V6h2v12H6zm3.5-6L18 6v12l-8.5-6z"
SVG_NEXT = "M16 6v12h2V6h-2zM6 18l8.5-6L6 6v12z"
SVG_PLAY = "M8 5v14l11-7L8 5z"
SVG_PAUSE = "M6 5h4v14H6V5zm8 0h4v14h-4V5z"

class PlayerBar(QWidget):
    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player

        self._dragging = False
        self._duration_ms = 0
        self._is_playing = False

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(10)

        # --- buttons ---
        self.btn_prev = QToolButton()
        self.btn_prev.setObjectName("BtnPrev")
        self.btn_prev.setIcon(_svg_icon(SVG_PREV, 20))
        self.btn_prev.setIconSize(QSize(20, 20))
        self.btn_prev.setToolTip("Previous")

        self.btn_play = QToolButton()
        self.btn_play.setObjectName("BtnPlay")
        self.btn_play.setIcon(_svg_icon(SVG_PLAY, 22))
        self.btn_play.setIconSize(QSize(22, 22))
        self.btn_play.setToolTip("Play/Pause")

        self.btn_next = QToolButton()
        self.btn_next.setObjectName("BtnNext")
        self.btn_next.setIcon(_svg_icon(SVG_NEXT, 20))
        self.btn_next.setIconSize(QSize(20, 20))
        self.btn_next.setToolTip("Next")

        self._icons = {
            "prev": (_svg_icon(SVG_PREV, 20, "#e5e7eb"), _svg_icon(SVG_PREV, 20, "#38bdf8")),
            "next": (_svg_icon(SVG_NEXT, 20, "#e5e7eb"), _svg_icon(SVG_NEXT, 20, "#38bdf8")),
            "play": (_svg_icon(SVG_PLAY, 22, "#e5e7eb"), _svg_icon(SVG_PLAY, 22, "#38bdf8")),
            "pause": (_svg_icon(SVG_PAUSE, 22, "#e5e7eb"), _svg_icon(SVG_PAUSE, 22, "#38bdf8")),
        }

        self.btn_prev.setIcon(self._icons["prev"][0])
        self.btn_next.setIcon(self._icons["next"][0])
        self.btn_play.setIcon(self._icons["play"][0])

        # --- labels ---
        self.lbl_title = QLabel("Nothing playing")
        self.lbl_title.setMinimumWidth(220)
        self.lbl_title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_title.setObjectName("NowPlaying")

        self.lbl_time = QLabel("0:00")
        self.lbl_dur = QLabel("0:00")

        # --- speed selector ---
        self.cmb_speed = QComboBox()
        self.cmb_speed.setObjectName("SpeedCombo")
        self.cmb_speed.setToolTip("Playback speed")
        # Display text -> speed float
        self._speed_items = [("1.0×", 1.0), ("0.75×", 0.75), ("0.5×", 0.5), ("0.25×", 0.25)]
        for label, speed in self._speed_items:
            self.cmb_speed.addItem(label, speed)
        self.cmb_speed.setCurrentIndex(0)

        # --- slider ---
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setSingleStep(1000)
        self.slider.setPageStep(5000)

        root.addWidget(self.btn_prev)
        root.addWidget(self.btn_play)
        root.addWidget(self.btn_next)
        root.addSpacing(6)
        root.addWidget(self.lbl_title, 1)
        root.addWidget(self.cmb_speed)
        root.addWidget(self.lbl_time)
        root.addWidget(self.slider, 3)
        root.addWidget(self.lbl_dur)

        # --- signals ---
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.sliderMoved.connect(self._on_slider_moved)

        self.cmb_speed.currentIndexChanged.connect(self._on_speed_changed)

        if self.player:
            self.player.trackChanged.connect(self._on_track_changed)
            self.player.statusChanged.connect(self._on_status_changed)
            self.player.positionChanged.connect(self._on_position)
            # optional but recommended:
            if hasattr(self.player, "durationChanged"):
                self.player.durationChanged.connect(self._on_duration)

            self.btn_play.clicked.connect(self.player.toggle_play_pause)

        self.setObjectName("PlayerBar")
        self._apply_styles()

    def set_prev_next_handlers(self, prev_fn, next_fn):
        self.btn_prev.clicked.connect(prev_fn)
        self.btn_next.clicked.connect(next_fn)

    # --- speed handling ---
    def _on_speed_changed(self, _index: int):
        if not self.player:
            return
        speed = float(self.cmb_speed.currentData() or 1.0)

        # Only works on mpv backend; Qt fallback may ignore.
        if hasattr(self.player, "set_playback_speed"):
            try:
                self.player.set_playback_speed(speed)
            except Exception:
                pass

    # --- slider handling ---
    def _on_slider_pressed(self):
        self._dragging = True

    def _on_slider_moved(self, value: int):
        # show preview time while dragging
        self.lbl_time.setText(_fmt(value))

    def _on_slider_released(self):
        self._dragging = False
        if self.player:
            self.player.seek_ms(int(self.slider.value()))

    # --- player updates ---
    def _on_track_changed(self, now_playing):
        if now_playing:
            artist = now_playing.artist or "Unknown Artist"
            title = now_playing.title or "Unknown"
            self.lbl_title.setText(f"{artist} — {title}")
        else:
            self.lbl_title.setText("Nothing playing")
            self.slider.setValue(0)
            self.lbl_time.setText("0:00")
            self.lbl_dur.setText("0:00")
            self._set_playing(False)

    def _on_status_changed(self, status):
        name = getattr(status, "name", str(status)).lower()
        self._set_playing("play" in name)

    def _set_playing(self, playing: bool):
        self._is_playing = bool(playing)
        if self._is_playing:
            self.btn_play.setIcon(_svg_icon(SVG_PAUSE, 22))
            self.btn_play.setToolTip("Pause")
        else:
            self.btn_play.setIcon(_svg_icon(SVG_PLAY, 22))
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

    def _apply_styles(self):
        self.setStyleSheet("""
        QWidget#PlayerBar {
            background-color: #020617;
            border-top: 1px solid #111827;
        }

        QToolButton {
            border: 1px solid transparent;
            background: transparent;
            padding: 6px;
            border-radius: 10px;
            color: #e5e7eb;      /* drives SVG via currentColor */
        }
        QToolButton:hover {
            background: #0b1222;
            border-color: #1f2937;
            color: #38bdf8;
        }
        QToolButton:pressed {
            background: #0f172a;
        }

        /* Round play button */
        QToolButton#BtnPlay {
            background: #111827;
            border: 1px solid #1f2937;
            border-radius: 999px;
            padding: 8px;
            color: #e5e7eb;
        }
        QToolButton#BtnPlay:hover {
            border-color: #38bdf8;
            background: #020617;
            color: #38bdf8;
        }
        QToolButton#BtnPlay:pressed {
            background: #0f172a;
        }

        QSlider::groove:horizontal {
            height: 4px;
            background: #0f172a;
            border-radius: 2px;
        }
        QSlider::handle:horizontal {
            width: 12px;
            height: 12px;
            margin: -4px 0;
            border-radius: 6px;
            background: #38bdf8;
        }
        QSlider::sub-page:horizontal {
            background: #38bdf8;
            border-radius: 2px;
        }

        QLabel {
            color: #9ca3af;
            font-size: 11px;
        }
        QLabel#NowPlaying {
            color: #e5e7eb;
            font-size: 12px;
        }
                           
        QComboBox#SpeedCombo {
            background: #0b1222;
            border: 1px solid #1f2937;
            border-radius: 10px;
            padding: 4px 8px;
            color: #e5e7eb;
            min-width: 74px;
            font-size: 11px;
        }
        QComboBox#SpeedCombo:hover { border-color: #38bdf8; }
        QComboBox#SpeedCombo::drop-down { border: none; width: 18px; }
        """)