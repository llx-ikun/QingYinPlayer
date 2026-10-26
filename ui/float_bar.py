# -*- coding: utf-8 -*-
"""左下浮动工具条（覆盖播放栏左上角）：主题（开关式切换按钮）/ 正在播放 / 数据目录 / 设置（图标+文字）。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
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

        # 主题：开关式切换按钮（icon-only，checkable）
        self.theme_toggle = QPushButton()
        self.theme_toggle.setObjectName("ThemeToggle")
        self.theme_toggle.setCheckable(True)
        self.theme_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_toggle.setIconSize(QSize(16, 16))
        ic.bind_icon(self.theme_toggle, "sun", 16, "dim")
        self.theme_toggle.clicked.connect(self.theme_clicked.emit)
        root.addWidget(self.theme_toggle)

        # 其余：图标 + 文字按钮
        self.np_btn = self._make_text_btn("note", "正在播放")
        self.np_btn.clicked.connect(self.now_playing_clicked.emit)
        root.addWidget(self.np_btn)
        self.dir_btn = self._make_text_btn("folder", "数据目录")
        self.dir_btn.clicked.connect(self.data_dir_clicked.emit)
        root.addWidget(self.dir_btn)
        self.settings_btn = self._make_text_btn("settings", "设置")
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        root.addWidget(self.settings_btn)

        self.set_theme_icon(True)

    def _make_text_btn(self, kind: str, text: str) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("FloatTextBtn")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIconSize(QSize(15, 15))
        ic.bind_icon(btn, kind, 15, "dim")
        btn.setText(text)
        btn.setToolTip(text)
        return btn

    def set_theme_icon(self, is_dark: bool) -> None:
        """深色主题下显示太阳（点它切到浅色），反之显示月亮；checked = 当前为浅色。"""
        ic.set_icon_kind(self.theme_toggle, "sun" if is_dark else "moon")
        self.theme_toggle.setToolTip("切换到浅色主题" if is_dark else "切换到深色主题")
        self.theme_toggle.setChecked(not is_dark)
