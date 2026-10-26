# -*- coding: utf-8 -*-
"""正在播放页：内部按媒体类型分为「音频模式」与「视频模式」两个子视图。

v2.1 变更：
- 音频模式：原布局（大封面 + 曲目信息 + 内嵌歌词面板），行为不变；
- 视频模式：QVideoSink 自绘画面（黑底等比居中）+ 标题信息 + 返回列表/音乐模式/全屏；
- 两个子视图共用底部 PlayerBar，切换子视图**不触碰播放器**，
  因此声音与播放进度不中断；
- 音频模式下若当前曲目是视频，额外出现「视频画面」按钮可切回视频模式。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.lyrics import format_time
from app.models import Track
from ui import icons as ic
from ui.lyrics_panel import LyricsPanel
from ui.video_view import VideoSinkHost
from ui.widgets import ClickableCover

MODE_AUDIO = "audio"
MODE_VIDEO = "video"


class _AudioView(QWidget):
    """音频模式：大封面 + 曲目信息 + 歌词面板。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(28)

        # 左：封面 + 信息
        left = QVBoxLayout()
        left.setSpacing(16)
        left.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.cover = ClickableCover()
        self.cover.setFixedSize(280, 280)
        self.cover.setScaledContents(True)
        left.addWidget(self.cover)

        self.title = QLabel("未在播放")
        self.title.setStyleSheet("font-size: 20px; font-weight: bold;")
        left.addWidget(self.title)

        self.artist = QLabel("")
        self.artist.setObjectName("Dim")
        left.addWidget(self.artist)

        self.meta = QLabel("")
        self.meta.setObjectName("Dim")
        left.addWidget(self.meta)

        # 视频曲目在音频模式下提供「看画面」入口
        self.video_btn = QPushButton("  视频画面")
        self.video_btn.setObjectName("Ghost")
        self.video_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.video_btn.setToolTip("切回视频画面（不中断播放）")
        ic.bind_icon(self.video_btn, "video", 14, "text")
        self.video_btn.hide()
        left.addWidget(self.video_btn)

        left.addStretch(1)
        root.addLayout(left, 4)

        # 右：歌词
        self.lyrics = LyricsPanel()
        root.addWidget(self.lyrics, 5)


class _VideoView(QWidget):
    """视频模式：画面 + 标题信息 + 操作按钮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(12)

        # 顶部操作条
        top = QHBoxLayout()
        top.setSpacing(8)

        self.back_btn = QPushButton("  返回列表")
        self.back_btn.setObjectName("Ghost")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.setToolTip("返回歌曲列表（声音继续播放）")
        ic.bind_icon(self.back_btn, "back", 14, "text")
        top.addWidget(self.back_btn)

        self.music_btn = QPushButton("  音乐模式")
        self.music_btn.setObjectName("Ghost")
        self.music_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.music_btn.setToolTip("隐藏画面，只听声音（不中断播放）")
        ic.bind_icon(self.music_btn, "note", 14, "text")
        top.addWidget(self.music_btn)

        self.full_btn = QPushButton("  全屏 F11")
        self.full_btn.setObjectName("Ghost")
        self.full_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.full_btn.setToolTip("全屏播放画面（F11 切换，Esc 退出）")
        ic.bind_icon(self.full_btn, "fullscreen", 14, "text")
        top.addWidget(self.full_btn)

        top.addStretch(1)
        root.addLayout(top)

        # 画面（黑底等比居中）
        self.host = VideoSinkHost()
        root.addWidget(self.host, 1)

        # 底部信息
        self.title = QLabel("未在播放")
        self.title.setStyleSheet("font-size: 16px; font-weight: bold;")
        root.addWidget(self.title)

        self.meta = QLabel("")
        self.meta.setObjectName("Dim")
        root.addWidget(self.meta)


class NowPlayingPage(QWidget):
    """正在播放页容器：按当前媒体类型切换音频/视频子视图。"""

    seek_requested = Signal(int)
    media_mode_changed = Signal(str)      # "audio" / "video"
    back_to_list_requested = Signal()
    fullscreen_requested = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stack = QStackedWidget(self)
        self.audio_view = _AudioView(self)
        self.video_view = _VideoView(self)
        self.stack.addWidget(self.audio_view)   # index 0
        self.stack.addWidget(self.video_view)   # index 1
        root.addWidget(self.stack)

        # 兼容旧接口：歌词面板直接暴露在页面上
        self.lyrics = self.audio_view.lyrics
        self.audio_view.lyrics.seek_requested.connect(self.seek_requested.emit)

        self._mode = MODE_AUDIO
        self._is_video_track = False

    # ---------- 模式 ----------

    @property
    def media_mode(self) -> str:
        return self._mode

    @property
    def video_host(self) -> VideoSinkHost:
        return self.video_view.host

    def set_media_mode(self, is_video: bool) -> None:
        """切换音频/视频子视图（不动播放器，声音与进度不中断）。"""
        mode = MODE_VIDEO if is_video else MODE_AUDIO
        if mode == self._mode:
            self._sync_mode_widgets()
            return
        self._mode = mode
        self.stack.setCurrentIndex(1 if is_video else 0)
        self._sync_mode_widgets()
        self.media_mode_changed.emit(mode)

    def _sync_mode_widgets(self) -> None:
        # 音频模式下，当前是视频曲目时给出「视频画面」入口
        self.audio_view.video_btn.setVisible(self._mode == MODE_AUDIO and self._is_video_track)

    # ---------- 转发（音频模式） ----------

    def set_track(self, track: Track, cover_pixmap) -> None:
        self._is_video_track = track.is_video

        self.audio_view.cover.setPixmap(cover_pixmap)
        self.audio_view.title.setText(track.display_title)
        self.audio_view.artist.setText(track.display_artist)
        duration = format_time(track.duration_ms) if track.duration_ms else "--:--"
        fmt = (track.fmt or "").upper()
        self.audio_view.meta.setText(f"{track.display_album} · {duration} · {fmt}")

        # 视频模式信息行
        import os

        self.video_view.title.setText(track.display_title)
        parts = [fmt or "未知格式"]
        if track.duration_ms:
            parts.append(format_time(track.duration_ms))
        parts.append(os.path.basename(track.path))
        self.video_view.meta.setText(" · ".join(parts))

        self._sync_mode_widgets()

    def set_synced(self, lines) -> None:
        self.lyrics.set_synced(lines)

    def set_plain(self, lines) -> None:
        self.lyrics.set_plain(lines)

    def set_empty(self, hint: str | None = None) -> None:
        self.lyrics.set_empty(hint)

    def update_position(self, position_ms: int) -> None:
        self.lyrics.update_position(position_ms)
