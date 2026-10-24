# -*- coding: utf-8 -*-
"""底部播放栏：封面/信息/控制按钮/进度/音量/模式/歌词开关。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.lyrics import format_time
from app.models import MODE_LOOP, MODE_SEQUENTIAL, MODE_SHUFFLE, MODE_SINGLE
from ui import icons as ic
from ui.theme import ACCENT, TEXT, TEXT_DIM
from ui.widgets import ClickableCover, ElidedLabel

_MODE_ICON = {
    MODE_LOOP: "loop",
    MODE_SEQUENTIAL: "sequential",
    MODE_SINGLE: "repeat_one",
    MODE_SHUFFLE: "shuffle",
}
_MODE_TIP = {
    MODE_LOOP: "列表循环",
    MODE_SEQUENTIAL: "顺序播放",
    MODE_SINGLE: "单曲循环",
    MODE_SHUFFLE: "随机播放",
}


class PlayerBar(QWidget):
    play_clicked = Signal()
    next_clicked = Signal()
    prev_clicked = Signal()
    seek_released = Signal(int)
    seek_preview = Signal(int)
    volume_changed = Signal(float)
    mute_clicked = Signal()
    mode_clicked = Signal()
    lyrics_toggled = Signal(bool)
    cover_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(76)
        self.setObjectName("Panel")
        self._seeking = False
        self._vol_dragging = False
        self._duration_ms = 0

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 8, 14, 8)
        root.setSpacing(10)

        # ---- 左：封面 + 信息 ----
        self.cover = ClickableCover()
        self.cover.setFixedSize(52, 52)
        self.cover.setScaledContents(True)
        self.cover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cover.clicked.connect(self.cover_clicked.emit)
        root.addWidget(self.cover)

        info_col = QVBoxLayout()
        info_col.setSpacing(1)
        self.title = ElidedLabel("未在播放")
        self.title.setObjectName("TrackTitle")
        self.artist = ElidedLabel("")
        self.artist.setObjectName("TrackSub")
        info_col.addWidget(self.title)
        info_col.addWidget(self.artist)
        root.addLayout(info_col, 1)

        # ---- 中：控制 ----
        center = QHBoxLayout()
        center.setSpacing(4)
        self.mode_btn = QPushButton()
        self.mode_btn.setObjectName("ControlBtn")
        self.mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_btn.clicked.connect(self.mode_clicked.emit)
        center.addWidget(self.mode_btn)

        self.prev_btn = QPushButton()
        self.prev_btn.setObjectName("ControlBtn")
        self.prev_btn.setIcon(ic.make_icon("prev", TEXT, 16))
        self.prev_btn.setToolTip("上一首")
        self.prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_btn.clicked.connect(self.prev_clicked.emit)
        center.addWidget(self.prev_btn)

        self.play_btn = QPushButton()
        self.play_btn.setObjectName("PlayCircle")
        self.play_btn.setIcon(ic.make_icon("play", "#ffffff", 18))
        self.play_btn.setToolTip("播放 / 暂停（空格）")
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.clicked.connect(self.play_clicked.emit)
        center.addWidget(self.play_btn)

        self.next_btn = QPushButton()
        self.next_btn.setObjectName("ControlBtn")
        self.next_btn.setIcon(ic.make_icon("next", TEXT, 16))
        self.next_btn.setToolTip("下一首")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_btn.clicked.connect(self.next_clicked.emit)
        center.addWidget(self.next_btn)

        self.lyrics_btn = QPushButton()
        self.lyrics_btn.setObjectName("ControlBtn")
        self.lyrics_btn.setIcon(ic.make_icon("lyrics", TEXT_DIM, 16))
        self.lyrics_btn.setToolTip("歌词面板")
        self.lyrics_btn.setCheckable(True)
        self.lyrics_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lyrics_btn.toggled.connect(self._on_lyrics_toggled)
        center.addWidget(self.lyrics_btn)
        root.addLayout(center)

        # ---- 进度 ----
        progress_col = QHBoxLayout()
        progress_col.setSpacing(8)
        self.time_cur = QLabel("0:00")
        self.time_cur.setObjectName("Dim")
        self.time_cur.setFixedWidth(36)
        progress_col.addWidget(self.time_cur)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setFixedWidth(320)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setTracking(False)  # 拖动中不触发 seek，release 时才跳转
        self.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        progress_col.addWidget(self.seek_slider, 1)

        self.time_total = QLabel("0:00")
        self.time_total.setObjectName("Dim")
        self.time_total.setFixedWidth(36)
        progress_col.addWidget(self.time_total)
        root.addLayout(progress_col, 2)

        # ---- 右：音量 ----
        vol_col = QHBoxLayout()
        vol_col.setSpacing(6)
        self.mute_btn = QPushButton()
        self.mute_btn.setObjectName("ControlBtn")
        self.mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mute_btn.clicked.connect(self.mute_clicked.emit)
        vol_col.addWidget(self.mute_btn)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setFixedWidth(90)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        vol_col.addWidget(self.volume_slider)
        root.addLayout(vol_col)

        self.set_mode(MODE_LOOP)
        self.update_volume(0.7, False)
        self.update_position(0, 0)

    # ---------- 状态更新 ----------

    def update_track(self, title: str, artist: str, cover_pixmap) -> None:
        self.title.setText(title or "未在播放")
        self.artist.setText(artist or "")
        self.cover.setPixmap(cover_pixmap)

    def update_state(self, state: str) -> None:
        playing = state == "playing"
        self.play_btn.setIcon(ic.make_icon("pause" if playing else "play", "#ffffff", 18))

    def update_duration(self, duration_ms: int) -> None:
        self._duration_ms = max(0, duration_ms)
        self.seek_slider.setRange(0, self._duration_ms)
        self.time_total.setText(format_time(self._duration_ms))

    def update_position(self, position_ms: int, duration_ms: int | None = None) -> None:
        if duration_ms is not None and duration_ms != self._duration_ms:
            self.update_duration(duration_ms)
        if not self._seeking:
            self.seek_slider.setValue(max(0, position_ms))
        if not self._seeking:
            self.time_cur.setText(format_time(position_ms))

    def update_volume(self, volume: float, muted: bool) -> None:
        if not self._vol_dragging:
            self.volume_slider.setValue(int(round(max(0.0, min(1.0, volume)) * 100)))
        icon = "mute" if muted or volume <= 0 else "volume"
        color = TEXT_DIM if muted or volume <= 0 else TEXT
        self.mute_btn.setIcon(ic.make_icon(icon, color, 16))

    def set_mode(self, mode: str) -> None:
        self.mode_btn.setIcon(ic.make_icon(_MODE_ICON.get(mode, "loop"), TEXT_DIM, 16))
        self.mode_btn.setToolTip(f"播放模式：{_MODE_TIP.get(mode, mode)}")

    def set_lyrics_active(self, active: bool) -> None:
        self.lyrics_btn.blockSignals(True)
        self.lyrics_btn.setChecked(active)
        self.lyrics_btn.blockSignals(False)
        color = ACCENT if active else TEXT_DIM
        self.lyrics_btn.setIcon(ic.make_icon("lyrics", color, 16))

    # ---------- 内部 ----------

    def _on_seek_pressed(self) -> None:
        self._seeking = True

    def _on_seek_moved(self, value: int) -> None:
        self.time_cur.setText(format_time(value))
        self.seek_preview.emit(value)

    def _on_seek_released(self) -> None:
        self._seeking = False
        self.seek_released.emit(self.seek_slider.value())

    def _on_volume_changed(self, value: int) -> None:
        self.volume_changed.emit(value / 100.0)

    def _on_lyrics_toggled(self, checked: bool) -> None:
        self.lyrics_toggled.emit(checked)
