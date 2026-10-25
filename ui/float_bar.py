# -*- coding: utf-8 -*-
"""左下浮动工具条（覆盖播放栏左上角）：主题 / 正在播放 / 数据目录 / 设置。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ui import icons as ic


class FloatBar(QWidget):
    theme_clicked = Signal()
    now_playing_clicked = Signal()
    data_dir_clicked = Signal()
    settings_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.theme_btn = self._make_btn("sun", "切换主题（深色 / 浅色）")
        self.theme_btn.clicked.connect(self.theme_clicked.emit)
        root.addWidget(self.theme_btn)
        self.np_btn = self._make_btn("note", "正在播放")
        self.np_btn.clicked.connect(self.now_playing_clicked.emit)
        root.addWidget(self.np_btn)
        self.dir_btn = self._make_btn("folder", "打开数据目录")
        self.dir_btn.clicked.connect(self.data_dir_clicked.emit)
        root.addWidget(self.dir_btn)
        self.settings_btn = self._make_btn("settings", "设置")
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        root.addWidget(self.settings_btn)
        self.set_theme_icon(True)

    def _make_btn(self, kind: str, tip: str) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("FloatBtn")
        btn.setToolTip(tip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(btn, kind, 16, "dim")
        return btn

    def set_theme_icon(self, is_dark: bool) -> None:
        """深色主题下显示太阳（点它切到浅色），反之显示月亮。"""
        ic.set_icon_kind(self.theme_btn, "sun" if is_dark else "moon")
        self.theme_btn.setToolTip("切换到浅色主题" if is_dark else "切换到深色主题")
