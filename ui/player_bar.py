# -*- coding: utf-8 -*-
"""底部播放栏（v2.0 照 QQ 音乐截图重设计）：

左：封面 + 标题/艺人 + 爱心 + 更多；
中：上一首 / 绿色圆形播放 / 下一首 + 进度双行（0:00 ──●── 1:47）；
右：音量 + 当前格式徽标 + 歌词开关 + 播放队列。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.lyrics import format_time
from app.models import MODE_LOOP, MODE_SEQUENTIAL, MODE_SHUFFLE, MODE_SINGLE
from ui import icons as ic
from ui.track_list import format_badge
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
    favorite_clicked = Signal()
    more_clicked = Signal()
    queue_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(84)
        self.setObjectName("PlayerBar")
        self._seeking = False
        self._vol_dragging = False
        self._duration_ms = 0

        root = QHBoxLayout(self)
        # 左侧 330px 缩进：给左下角浮动工具条留位（QQ 音乐同款布局；
        # 浮动条现为「主题切换 + 图标文字按钮」，展开后约 300px 宽）
        root.setContentsMargins(330, 8, 14, 8)
        root.setSpacing(10)

        # ---- 左：封面 + 信息 + 爱心/更多 ----
        self.cover = ClickableCover()
        self.cover.setFixedSize(48, 48)
        self.cover.setScaledContents(True)
        self.cover.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cover.clicked.connect(self.cover_clicked.emit)
        root.addWidget(self.cover)

        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        self.title = ElidedLabel("未在播放")
        self.title.setObjectName("TrackTitle")
        self.artist = ElidedLabel("")
        self.artist.setObjectName("TrackSub")
        info_col.addWidget(self.title)
        info_col.addWidget(self.artist)
        root.addLayout(info_col, 1)
        root.setStretchFactor(info_col, 1)

        self.fav_btn = self._make_row_btn("heart", "喜欢 / 取消喜欢")
        self.fav_btn.clicked.connect(self.favorite_clicked.emit)
        root.addWidget(self.fav_btn)

        self.more_btn = self._make_row_btn("more", "更多")
        self.more_btn.clicked.connect(self.more_clicked.emit)
        root.addWidget(self.more_btn)

        root.addSpacing(20)

        # ---- 中：控制 + 进度（双行） ----
        center = QVBoxLayout()
        center.setSpacing(2)
        center.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.mode_btn = QPushButton()
        self.mode_btn.setObjectName("ControlBtn")
        self.mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_btn.clicked.connect(self.mode_clicked.emit)
        buttons.addWidget(self.mode_btn)

        self.prev_btn = QPushButton()
        self.prev_btn.setObjectName("ControlBtn")
        self.prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(self.prev_btn, "prev", 16, "text")
        self.prev_btn.setToolTip("上一首")
        self.prev_btn.clicked.connect(self.prev_clicked.emit)
        buttons.addWidget(self.prev_btn)

        self.play_btn = QPushButton()
        self.play_btn.setObjectName("PlayCircle")
        self.play_btn.setToolTip("播放 / 暂停（空格）")
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(self.play_btn, "play", 18, "on_accent")
        self.play_btn.clicked.connect(self.play_clicked.emit)
        buttons.addWidget(self.play_btn)

        self.next_btn = QPushButton()
        self.next_btn.setObjectName("ControlBtn")
        self.next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(self.next_btn, "next", 16, "text")
        self.next_btn.setToolTip("下一首")
        self.next_btn.clicked.connect(self.next_clicked.emit)
        buttons.addWidget(self.next_btn)
        center.addLayout(buttons)

        progress = QHBoxLayout()
        progress.setSpacing(8)
        self.time_cur = QLabel("0:00")
        self.time_cur.setObjectName("Dim")
        self.time_cur.setFixedWidth(36)
        progress.addWidget(self.time_cur)

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setFixedWidth(380)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.setTracking(False)  # 拖动中不触发 seek，release 时才跳转
        self.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        progress.addWidget(self.seek_slider)

        self.time_total = QLabel("0:00")
        self.time_total.setObjectName("Dim")
        self.time_total.setFixedWidth(36)
        progress.addWidget(self.time_total)
        center.addLayout(progress)
        root.addLayout(center, 3)

        root.addSpacing(20)

        # ---- 右：音量 + 格式 + 歌词 + 队列 ----
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

        self.fmt_badge = QLabel("--")
        self.fmt_badge.setObjectName("FmtBadge")
        self.fmt_badge.setFixedSize(46, 20)
        self.fmt_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.fmt_badge)

        self.lyrics_btn = QPushButton()
        self.lyrics_btn.setObjectName("ControlBtn")
        self.lyrics_btn.setCheckable(True)
        self.lyrics_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(self.lyrics_btn, "lyrics", 16, "dim")
        self.lyrics_btn.setToolTip("歌词面板")
        self.lyrics_btn.toggled.connect(self._on_lyrics_toggled)
        root.addWidget(self.lyrics_btn)

        self.queue_btn = QPushButton()
        self.queue_btn.setObjectName("ControlBtn")
        self.queue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(self.queue_btn, "queue", 16, "dim")
        self.queue_btn.setToolTip("播放队列")
        self.queue_btn.clicked.connect(self.queue_clicked.emit)
        root.addWidget(self.queue_btn)

        self.set_mode(MODE_LOOP)
        self.update_volume(0.7, False)
        self.update_position(0, 0)

    # ---------- 内部小部件 ----------

    def _make_row_btn(self, kind: str, tip: str) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("RowBtn")
        btn.setToolTip(tip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(btn, kind, 14, "dim")
        return btn

    # ---------- 状态更新 ----------

    def update_track(self, title: str, artist: str, cover_pixmap) -> None:
        self.title.setText(title or "未在播放")
        self.artist.setText(artist or "")
        self.cover.setPixmap(cover_pixmap)

    def update_state(self, state: str) -> None:
        playing = state == "playing"
        ic.set_icon_kind(self.play_btn, "pause" if playing else "play")

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
            self.volume_slider.setValue(round(max(0.0, min(1.0, volume)) * 100))
        icon = "mute" if muted or volume <= 0 else "volume"
        color_role = "dim" if muted or volume <= 0 else "text"
        ic.bind_icon(self.mute_btn, icon, 16, color_role)

    def set_mode(self, mode: str) -> None:
        ic.bind_icon(self.mode_btn, _MODE_ICON.get(mode, "loop"), 16, "dim")
        self.mode_btn.setToolTip(f"播放模式：{_MODE_TIP.get(mode, mode)}")

    def set_lyrics_active(self, active: bool) -> None:
        self.lyrics_btn.blockSignals(True)
        self.lyrics_btn.setChecked(active)
        self.lyrics_btn.blockSignals(False)
        ic.bind_icon(self.lyrics_btn, "lyrics", 16, "accent" if active else "dim")

    def set_favorite_active(self, active: bool) -> None:
        ic.bind_icon(self.fav_btn, "heart_filled" if active else "heart", 14,
                     "heart" if active else "dim")
        self.fav_btn.setProperty("active", "true" if active else "false")
        self.fav_btn.style().unpolish(self.fav_btn)
        self.fav_btn.style().polish(self.fav_btn)
        self.fav_btn.setToolTip("取消喜欢" if active else "加入我喜欢")

    def set_format(self, fmt: str) -> None:
        text, tier = format_badge(fmt)
        self.fmt_badge.setText(text)
        self.fmt_badge.setProperty("tier", tier)
        self.fmt_badge.style().unpolish(self.fmt_badge)
        self.fmt_badge.style().polish(self.fmt_badge)
        self.fmt_badge.setToolTip(f"格式：{fmt or '未知'}")

    def queue_button_global_pos(self) -> QPoint:
        return self.queue_btn.mapToGlobal(QPoint(self.queue_btn.width() // 2, 0))

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
