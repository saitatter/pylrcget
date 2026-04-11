from __future__ import annotations

import base64
import html
import logging
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from mutagen import File as MutagenFile
from mutagen.apev2 import APEBinaryValue
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC
from mutagen.mp4 import MP4, MP4Cover
from mutagen.asf import ASF
from mutagen.musepack import Musepack
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from ui.icon_loader import load_svg_icon
from ui.spacing import SPACE_2, SPACE_3, set_layout_spacing
from ui.style_loader import load_stylesheet
from ui.theme_tokens import STYLE_TOKENS

logger = logging.getLogger(__name__)


def _fmt(ms: int) -> str:
    ms = max(0, int(ms))
    s = ms // 1000
    m = s // 60
    s = s % 60
    return f"{m}:{s:02d}"


def _cover_pixmap(title: str, artist: str | None, size: int = 56) -> QPixmap:
    key = (artist or title or "?").strip() or "?"
    glyph = key[0].upper()

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor("#1e293b"))
    gradient.setColorAt(1.0, QColor("#0f172a"))
    painter.setBrush(gradient)
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(0, 0, size, size, 12, 12)

    font = QFont()
    font.setPointSize(max(14, size // 3))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#e2e8f0"))
    painter.drawText(pixmap.rect(), Qt.AlignCenter, glyph)
    painter.end()

    return pixmap


def _sidecar_cover_path(audio_path: str | None) -> Path | None:
    if not audio_path:
        return None

    folder = Path(audio_path).resolve().parent
    candidate_names = (
        "cover.jpg",
        "cover.jpeg",
        "cover.png",
        "folder.jpg",
        "folder.jpeg",
        "folder.png",
        "front.jpg",
        "front.jpeg",
        "front.png",
        "album.jpg",
        "album.jpeg",
        "album.png",
        "artwork.jpg",
        "artwork.jpeg",
        "artwork.png",
    )
    for name in candidate_names:
        candidate = folder / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _embedded_cover_bytes(audio_path: str | None) -> bytes | None:
    if not audio_path:
        return None

    try:
        audio = MutagenFile(audio_path, easy=False)
    except Exception:
        return None

    if audio is None:
        return None

    try:
        if isinstance(audio, ASF):
            for picture in audio.get("WM/Picture", []):
                data = getattr(picture, "data", None)
                if data:
                    return bytes(data)

        if isinstance(audio, FLAC) and getattr(audio, "pictures", None):
            picture = audio.pictures[0]
            return bytes(getattr(picture, "data", b"") or b"")

        if isinstance(audio, MP4):
            covers = audio.tags.get("covr", []) if audio.tags else []
            if covers:
                cover = covers[0]
                if isinstance(cover, MP4Cover):
                    return bytes(cover)
                return bytes(cover)

        if isinstance(audio, Musepack) and getattr(audio, "tags", None):
            for key in ("Cover Art (Front)", "Cover Art (Front).jpg", "Cover Art (Front).png"):
                picture = audio.tags.get(key)
                if not picture:
                    continue
                raw = bytes(picture) if isinstance(picture, APEBinaryValue) else bytes(picture)
                if b"\x00" in raw:
                    _, image_data = raw.split(b"\x00", 1)
                else:
                    image_data = raw
                if image_data:
                    return image_data

        if hasattr(audio, "tags") and audio.tags:
            for tag in audio.tags.values():
                if isinstance(tag, APIC):
                    return bytes(tag.data or b"")

        if isinstance(audio, (OggVorbis, OggOpus)):
            if audio.tags:
                metadata_blocks = audio.tags.get("metadata_block_picture", [])
                for raw in metadata_blocks:
                    try:
                        picture = Picture(base64.b64decode(raw))
                        if picture.data:
                            return bytes(picture.data)
                    except Exception:
                        continue

                coverart_blocks = audio.tags.get("coverart", [])
                for raw in coverart_blocks:
                    try:
                        data = base64.b64decode(raw)
                        if data:
                            return data
                    except Exception:
                        continue
    except Exception:
        return None

    return None


def _artwork_pixmap(title: str, artist: str | None, audio_path: str | None, size: int = 56) -> QPixmap:
    sidecar = _sidecar_cover_path(audio_path)
    if sidecar is not None:
        pixmap = QPixmap(str(sidecar))
        if not pixmap.isNull():
            return pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)

    embedded = _embedded_cover_bytes(audio_path)
    if embedded:
        pixmap = QPixmap()
        if pixmap.loadFromData(embedded):
            return pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)

    return _cover_pixmap(title, artist, size)


class SeekSlider(QSlider):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        groove_height = 7.0
        handle_size = 12.0
        radius = groove_height / 2.0
        value_range = max(1, self.maximum() - self.minimum())
        ratio = (self.value() - self.minimum()) / value_range if self.maximum() > self.minimum() else 0.0

        track_left = handle_size / 2.0
        track_width = max(1.0, self.width() - handle_size)
        track_top = (self.height() - groove_height) / 2.0
        track_rect = QRectF(track_left, track_top, track_width, groove_height)

        fill_width = track_width * max(0.0, min(1.0, ratio))
        fill_rect = QRectF(track_left, track_top, fill_width, groove_height)

        fill_gradient = QLinearGradient(track_rect.left(), track_rect.top(), track_rect.right(), track_rect.top())
        fill_gradient.setColorAt(0.0, QColor(STYLE_TOKENS["color-slider-fill-start"]))
        fill_gradient.setColorAt(1.0, QColor(STYLE_TOKENS["color-slider-fill-end"]))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(STYLE_TOKENS["color-bg-pressed"]))
        painter.drawRoundedRect(track_rect, radius, radius)

        if fill_width > 0:
            painter.setBrush(fill_gradient)
            painter.drawRoundedRect(fill_rect, radius, radius)

        handle_center_x = track_left + fill_width
        handle_rect = QRectF(
            handle_center_x - handle_size / 2.0,
            (self.height() - handle_size) / 2.0,
            handle_size,
            handle_size,
        )
        handle_color = (
            QColor(STYLE_TOKENS["color-accent-alt"])
            if self.underMouse() or self.isSliderDown()
            else QColor(STYLE_TOKENS["color-accent"])
        )
        painter.setBrush(handle_color)
        painter.setPen(QPen(QColor(STYLE_TOKENS["color-slider-handle-border"]), 2))
        painter.drawEllipse(handle_rect)
        painter.end()

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
    playbackSpeedChanged = Signal(float)
    volumeChanged = Signal(float)
    artistNavigationRequested = Signal(int)
    albumNavigationRequested = Signal(int)

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player

        self._dragging = False
        self._duration_ms = 0
        self._is_playing = False
        self._speed_step = 0.05
        self._current_track_id: int | None = None
        self._speed_commit_timer = QTimer(self)
        self._speed_commit_timer.setSingleShot(True)
        self._speed_commit_timer.setInterval(450)
        self._speed_commit_timer.timeout.connect(self._commit_pending_custom_speed)
        self.setObjectName("PlayerBar")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        set_layout_spacing(root, margins=(SPACE_2, SPACE_2, SPACE_2, SPACE_2), spacing=0)

        shell = QWidget()
        shell.setObjectName("PlayerShell")
        shell_layout = QGridLayout(shell)
        set_layout_spacing(shell_layout, margins=(SPACE_2, SPACE_2, SPACE_2, SPACE_2), spacing=SPACE_2)
        root.addWidget(shell)

        left_panel = QWidget()
        left_panel.setObjectName("PlayerMeta")
        left_panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        left_layout = QHBoxLayout(left_panel)
        set_layout_spacing(left_layout, margins=0, spacing=SPACE_2)

        self.lbl_cover = QLabel()
        self.lbl_cover.setObjectName("NowPlayingCover")
        self.lbl_cover.setFixedSize(56, 56)
        self.lbl_cover.setPixmap(_artwork_pixmap("?", None, None, 56))

        text_stack = QVBoxLayout()
        set_layout_spacing(text_stack, spacing=2)

        self.lbl_title = QLabel("Nothing playing")
        self.lbl_title.setObjectName("NowPlaying")
        self.lbl_title.setMinimumWidth(220)
        self.lbl_title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_title.setWordWrap(False)

        self.lbl_artist = QLabel("Choose a track to start playback")
        self.lbl_artist.setObjectName("NowPlayingArtist")
        self.lbl_artist.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_artist.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.lbl_artist.setOpenExternalLinks(False)
        self.lbl_artist.linkActivated.connect(self._on_artist_link_activated)

        self.lbl_album = QLabel("")
        self.lbl_album.setObjectName("NowPlayingAlbum")
        self.lbl_album.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_album.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.lbl_album.setOpenExternalLinks(False)
        self.lbl_album.linkActivated.connect(self._on_album_link_activated)

        text_stack.addWidget(self.lbl_title)
        text_stack.addWidget(self.lbl_artist)
        text_stack.addWidget(self.lbl_album)
        text_stack.addStretch(1)

        left_layout.addWidget(self.lbl_cover, 0, Qt.AlignVCenter)
        left_layout.addLayout(text_stack, 1)

        center_panel = QWidget()
        center_panel.setObjectName("PlayerCenter")
        center_panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        center_layout = QVBoxLayout(center_panel)
        set_layout_spacing(center_layout, margins=(0, 1, 0, 1), spacing=2)

        controls_row = QHBoxLayout()
        set_layout_spacing(controls_row, margins=0, spacing=SPACE_2)
        controls_row.addStretch(1)

        self.btn_prev = QToolButton()
        self.btn_prev.setObjectName("BtnPrev")
        self.btn_prev.setToolTip("Previous")
        self.btn_prev.setAccessibleName("Previous track")
        self.btn_prev.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_prev.setAutoRaise(False)
        self.btn_prev.setFixedSize(28, 28)

        self.btn_play = QToolButton()
        self.btn_play.setObjectName("BtnPlay")
        self.btn_play.setToolTip("Play/Pause")
        self.btn_play.setAccessibleName("Play or pause")
        self.btn_play.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_play.setAutoRaise(False)
        self.btn_play.setFixedSize(44, 44)

        self.btn_next = QToolButton()
        self.btn_next.setObjectName("BtnNext")
        self.btn_next.setToolTip("Next")
        self.btn_next.setAccessibleName("Next track")
        self.btn_next.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_next.setAutoRaise(False)
        self.btn_next.setFixedSize(28, 28)

        self._icons = {
            "prev": load_svg_icon("skip-back.svg", 20, "#e5e7eb"),
            "next": load_svg_icon("skip-forward.svg", 20, "#e5e7eb"),
            "play": load_svg_icon("play.svg", 28, "#e5e7eb"),
            "pause": load_svg_icon("pause.svg", 28, "#e5e7eb"),
        }
        self.btn_prev.setIcon(self._icons["prev"])
        self.btn_next.setIcon(self._icons["next"])
        self.btn_play.setIcon(self._icons["play"])
        self.btn_prev.setIconSize(QSize(12, 12))
        self.btn_next.setIconSize(QSize(12, 12))
        self.btn_play.setIconSize(QSize(18, 18))

        controls_row.addWidget(self.btn_prev)
        controls_row.addWidget(self.btn_play)
        controls_row.addWidget(self.btn_next)
        controls_row.addStretch(1)
        center_layout.addLayout(controls_row)

        progress_row = QHBoxLayout()
        set_layout_spacing(progress_row, margins=0, spacing=SPACE_2)

        self.lbl_time = QLabel("0:00")
        self.lbl_time.setObjectName("TimeLabel")
        self.lbl_dur = QLabel("0:00")
        self.lbl_dur.setObjectName("TimeLabel")

        self.slider = SeekSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("PlayerSlider")
        self.slider.setRange(0, 0)
        self.slider.setSingleStep(1000)
        self.slider.setPageStep(5000)
        self.slider.setMinimumHeight(16)

        progress_row.addWidget(self.lbl_time)
        progress_row.addWidget(self.slider, 1)
        progress_row.addWidget(self.lbl_dur)
        center_layout.addLayout(progress_row)

        right_panel = QWidget()
        right_panel.setObjectName("PlayerExtras")
        right_panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        right_layout = QVBoxLayout(right_panel)
        set_layout_spacing(right_layout, margins=0, spacing=4)

        self.lbl_speed = QLabel("Speed")
        self.lbl_speed.setObjectName("MetaLabel")

        speed_row = QHBoxLayout()
        set_layout_spacing(speed_row, margins=0, spacing=SPACE_2)

        self.btn_speed_down = QToolButton()
        self.btn_speed_down.setObjectName("SpeedAdjustButton")
        self.btn_speed_down.setText("-")
        self.btn_speed_down.setToolTip("Decrease playback speed by 0.05x")

        self.cmb_speed = QComboBox()
        self.cmb_speed.setObjectName("SpeedCombo")
        self.cmb_speed.setToolTip("Playback speed")
        self.cmb_speed.setAccessibleName("Playback speed")
        self.cmb_speed.setEditable(True)
        self.cmb_speed.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._speed_items = [
            ("1.0x", 1.0),
            ("0.9x", 0.9),
            ("0.8x", 0.8),
            ("0.75x", 0.75),
            ("0.5x", 0.5),
            ("0.25x", 0.25),
        ]
        for label, speed in self._speed_items:
            self.cmb_speed.addItem(label, speed)
        self.cmb_speed.setCurrentIndex(0)
        self.cmb_speed.lineEdit().setPlaceholderText("Custom")
        self.cmb_speed.lineEdit().installEventFilter(self)

        self.btn_speed_up = QToolButton()
        self.btn_speed_up.setObjectName("SpeedAdjustButton")
        self.btn_speed_up.setText("+")
        self.btn_speed_up.setToolTip("Increase playback speed by 0.05x")

        speed_row.addWidget(self.btn_speed_down)
        speed_row.addWidget(self.cmb_speed, 1)
        speed_row.addWidget(self.btn_speed_up)

        right_layout.addWidget(self.lbl_speed)
        right_layout.addLayout(speed_row)

        volume_row = QHBoxLayout()
        set_layout_spacing(volume_row, margins=0, spacing=SPACE_2)

        self.lbl_volume = QLabel("Volume")
        self.lbl_volume.setObjectName("MetaLabel")

        self.slider_volume = SeekSlider(Qt.Orientation.Horizontal)
        self.slider_volume.setObjectName("VolumeSlider")
        self.slider_volume.setRange(0, 100)
        self.slider_volume.setSingleStep(5)
        self.slider_volume.setPageStep(10)
        self.slider_volume.setMinimumHeight(16)

        self.lbl_volume_value = QLabel("70%")
        self.lbl_volume_value.setObjectName("TimeLabel")
        self.lbl_volume_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_volume_value.setMinimumWidth(34)

        volume_row.addWidget(self.lbl_volume)
        volume_row.addWidget(self.slider_volume, 1)
        volume_row.addWidget(self.lbl_volume_value)
        right_layout.addLayout(volume_row)

        shell_layout.addWidget(left_panel, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        shell_layout.addWidget(center_panel, 0, 1, Qt.AlignCenter)
        shell_layout.addWidget(right_panel, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        shell_layout.setColumnStretch(0, 1)
        shell_layout.setColumnStretch(1, 0)
        shell_layout.setColumnStretch(2, 1)

        center_panel.setMinimumWidth(500)
        center_panel.setMaximumWidth(640)

        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.cmb_speed.activated.connect(self._on_speed_preset_selected)
        self.cmb_speed.lineEdit().editingFinished.connect(self._on_custom_speed_committed)
        self.cmb_speed.lineEdit().textEdited.connect(self._on_custom_speed_edited)
        self.btn_speed_down.clicked.connect(lambda: self._step_speed(-self._speed_step))
        self.btn_speed_up.clicked.connect(lambda: self._step_speed(self._speed_step))
        self.slider_volume.valueChanged.connect(self._on_volume_changed)

        if self.player:
            self.player.trackChanged.connect(self._on_track_changed)
            self.player.statusChanged.connect(self._on_status_changed)
            self.player.positionChanged.connect(self._on_position)
            if hasattr(self.player, "durationChanged"):
                self.player.durationChanged.connect(self._on_duration)
            self.btn_play.clicked.connect(self.player.toggle_play_pause)

        self._apply_styles()
        self._sync_speed_from_player()
        self._sync_volume_from_player()
        self.set_compact_mode(False)

    def set_prev_next_handlers(self, prev_fn, next_fn):
        self.btn_prev.clicked.connect(prev_fn)
        self.btn_next.clicked.connect(next_fn)

    def set_playback_speed_value(self, speed: float) -> None:
        self._set_speed_combo_value(self._normalize_speed(speed))

    def set_volume_value(self, volume_0_to_1: float) -> None:
        self._set_volume_slider_value(volume_0_to_1)

    def set_compact_mode(self, compact: bool):
        self.setProperty("compact", compact)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

        self.lbl_album.setVisible(not compact)
        self.lbl_speed.setVisible(not compact)
        self.lbl_volume.setVisible(True)
        self.lbl_title.setMinimumWidth(110 if compact else 150)
        left_width = 240 if compact else 300
        right_width = 150 if compact else 190
        center_width = 420 if compact else 560
        cover_size = 44 if compact else 52
        bar_height = 92 if compact else 104
        self.lbl_cover.setFixedSize(cover_size, cover_size)
        self.findChild(QWidget, "PlayerMeta").setFixedWidth(left_width)
        self.findChild(QWidget, "PlayerExtras").setFixedWidth(right_width)
        self.findChild(QWidget, "PlayerCenter").setFixedWidth(center_width)
        self.setMinimumHeight(bar_height)
        self.setMaximumHeight(bar_height)

        now_playing = None
        if self.player:
            now_playing = getattr(self.player, "track", None)
        if now_playing:
            self.lbl_cover.setPixmap(_artwork_pixmap(now_playing.title or "?", now_playing.artist, getattr(now_playing, "path", None), cover_size))
        else:
            self.lbl_cover.setPixmap(_artwork_pixmap("?", None, None, cover_size))

    def _format_speed_label(self, speed: float) -> str:
        rendered = f"{float(speed):.2f}".rstrip("0").rstrip(".")
        if "." not in rendered:
            rendered += ".0"
        return f"{rendered}x"

    def _normalize_speed(self, speed: float) -> float:
        return max(0.25, min(2.0, round(float(speed), 2)))

    def _apply_speed(self, speed: float) -> None:
        normalized = self._normalize_speed(speed)
        self._speed_commit_timer.stop()
        if self.player and hasattr(self.player, "set_playback_speed"):
            try:
                self.player.set_playback_speed(normalized)
            except Exception:
                self._sync_speed_from_player()
                return
        self._set_speed_combo_value(normalized)
        self.playbackSpeedChanged.emit(normalized)

    def _set_volume_slider_value(self, volume_0_to_1: float) -> None:
        normalized = max(0.0, min(1.0, float(volume_0_to_1)))
        rendered = int(round(normalized * 100))
        self.slider_volume.blockSignals(True)
        self.slider_volume.setValue(rendered)
        self.slider_volume.blockSignals(False)
        self.lbl_volume_value.setText(f"{rendered}%")

    def _on_volume_changed(self, value: int) -> None:
        normalized = max(0.0, min(1.0, float(value) / 100.0))
        self.lbl_volume_value.setText(f"{int(round(normalized * 100))}%")
        if self.player and hasattr(self.player, "set_volume"):
            try:
                self.player.set_volume(normalized)
            except Exception as exc:
                logger.warning("Failed to set volume from slider: %s", exc)
                self._sync_volume_from_player()
                return
        self.volumeChanged.emit(normalized)

    def _on_speed_preset_selected(self, index: int):
        speed = self.cmb_speed.itemData(index)
        if speed is None:
            return
        self._apply_speed(float(speed))

    def _on_custom_speed_committed(self):
        raw = (self.cmb_speed.currentText() or "").strip().lower().replace("x", "")
        if not raw:
            self._sync_speed_from_player()
            return

        try:
            speed = float(raw)
        except ValueError:
            self._sync_speed_from_player()
            return

        self._apply_speed(speed)

    def _on_custom_speed_edited(self, _text: str) -> None:
        self._speed_commit_timer.start()

    def _commit_pending_custom_speed(self) -> None:
        if self.cmb_speed.lineEdit().hasFocus():
            self._on_custom_speed_committed()

    def _step_speed(self, delta: float) -> None:
        current = 1.0
        if self.player and hasattr(self.player, "playback_speed"):
            try:
                current = float(self.player.playback_speed() or 1.0)
            except Exception:
                current = 1.0
        self._apply_speed(current + delta)

    def _sync_speed_from_player(self):
        if not self.player or not hasattr(self.player, "playback_speed"):
            return
        try:
            speed = float(self.player.playback_speed() or 1.0)
        except Exception:
            speed = 1.0

        self._set_speed_combo_value(speed)

    def _sync_volume_from_player(self):
        if not self.player or not hasattr(self.player, "volume"):
            return
        try:
            volume = float(self.player.volume())
        except Exception as exc:
            logger.warning("Failed to sync volume from player: %s", exc)
            volume = 0.7
        self._set_volume_slider_value(volume)

    def _set_speed_combo_value(self, speed: float):
        for idx in range(self.cmb_speed.count()):
            if abs(float(self.cmb_speed.itemData(idx)) - speed) < 0.001:
                self.cmb_speed.blockSignals(True)
                self.cmb_speed.setCurrentIndex(idx)
                self.cmb_speed.lineEdit().setText(self.cmb_speed.itemText(idx))
                self.cmb_speed.blockSignals(False)
                return

        self.cmb_speed.blockSignals(True)
        self.cmb_speed.setCurrentIndex(-1)
        self.cmb_speed.lineEdit().setText(self._format_speed_label(speed))
        self.cmb_speed.blockSignals(False)

    def eventFilter(self, watched, event):
        if watched is self.cmb_speed.lineEdit() and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._on_custom_speed_committed()
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _on_slider_pressed(self):
        self._dragging = True

    def _on_slider_moved(self, value: int):
        self.lbl_time.setText(_fmt(value))

    def _on_slider_released(self):
        self._dragging = False
        if self.player:
            self.player.seek_ms(int(self.slider.value()), exact=True)

    def _on_track_changed(self, now_playing):
        cover_size = self.lbl_cover.width() or 56
        if now_playing:
            self._current_track_id = int(getattr(now_playing, "track_id", 0) or 0) or None
            artist = now_playing.artist or "Unknown Artist"
            title = now_playing.title or "Unknown"
            album = getattr(now_playing, "album", None) or ""
            self.lbl_title.setText(title)
            self.lbl_artist.setText(f'<a href="artist">{html.escape(artist)}</a>')
            self.lbl_album.setText(f'<a href="album">{html.escape(album)}</a>' if album else "")
            self.lbl_cover.setPixmap(_artwork_pixmap(title, artist, getattr(now_playing, "path", None), cover_size))
        else:
            self._current_track_id = None
            self.lbl_title.setText("Nothing playing")
            self.lbl_artist.setText("Choose a track to start playback")
            self.lbl_album.setText("")
            self.lbl_cover.setPixmap(_artwork_pixmap("?", None, None, cover_size))
            self.slider.setValue(0)
            self.lbl_time.setText("0:00")
            self.lbl_dur.setText("0:00")
            self._set_playing(False)

    def _on_artist_link_activated(self, _link: str) -> None:
        if self._current_track_id is not None:
            self.artistNavigationRequested.emit(self._current_track_id)

    def _on_album_link_activated(self, _link: str) -> None:
        if self._current_track_id is not None:
            self.albumNavigationRequested.emit(self._current_track_id)

    def _on_status_changed(self, status):
        name = getattr(status, "name", str(status)).lower()
        self._set_playing("play" in name)

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

    def _apply_styles(self):
        self.setStyleSheet(load_stylesheet("player_bar.qss"))
