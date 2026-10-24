# -*- coding: utf-8 -*-
"""正在播放页：大封面 + 曲目信息 + 内嵌歌词面板。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.lyrics import format_time
from app.models import Track
from ui.lyrics_panel import LyricsPanel
from ui.theme import BORDER, TEXT_DIM
from ui.widgets import ClickableCover


class NowPlayingPage(QWidget):
    seek_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
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

        left.addStretch(1)
        root.addLayout(left, 4)

        # 右：歌词
        self.lyrics = LyricsPanel()
        self.lyrics.seek_requested.connect(self.seek_requested.emit)
        root.addWidget(self.lyrics, 5)

    # ---------- 转发 ----------

    def set_track(self, track: Track, cover_pixmap) -> None:
        self.cover.setPixmap(cover_pixmap)
        self.title.setText(track.display_title)
        self.artist.setText(track.display_artist)
        duration = format_time(track.duration_ms) if track.duration_ms else "--:--"
        fmt = (track.fmt or "").upper()
        self.meta.setText(f"{track.display_album} · {duration} · {fmt}")

    def set_synced(self, lines) -> None:
        self.lyrics.set_synced(lines)

    def set_plain(self, lines) -> None:
        self.lyrics.set_plain(lines)

    def set_empty(self, hint: str | None = None) -> None:
        self.lyrics.set_empty(hint)

    def update_position(self, position_ms: int) -> None:
        self.lyrics.update_position(position_ms)
