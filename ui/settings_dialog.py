# -*- coding: utf-8 -*-
"""设置对话框：昵称 / 主题（深色·浅色）/ 本地统计。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)


class SettingsDialog(QDialog):
    theme_changed = Signal(str)      # "dark" / "light"
    nickname_changed = Signal(str)

    def __init__(self, theme_name: str, nickname: str, stats: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsDialog")
        self.setWindowTitle("设置")
        self.setMinimumWidth(360)
        self._theme_name = theme_name if theme_name in ("dark", "light") else "dark"

        root = QVBoxLayout(self)
        root.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(8)
        self.nickname_edit = QLineEdit(nickname)
        self.nickname_edit.textChanged.connect(self.nickname_changed.emit)
        form.addRow("昵称", self.nickname_edit)
        root.addLayout(form)

        # ---- 主题 ----
        theme_row = QHBoxLayout()
        theme_row.setSpacing(16)
        self.dark_radio = QRadioButton("深色")
        self.light_radio = QRadioButton("浅色")
        (self.dark_radio if self._theme_name == "dark" else self.light_radio).setChecked(True)
        self.dark_radio.toggled.connect(lambda checked: checked and self._on_theme("dark"))
        self.light_radio.toggled.connect(lambda checked: checked and self._on_theme("light"))
        theme_row.addWidget(QLabel("主题"))
        theme_row.addWidget(self.dark_radio)
        theme_row.addWidget(self.light_radio)
        theme_row.addStretch(1)
        root.addLayout(theme_row)

        # ---- 本地统计 ----
        stats_text = (
            f"曲目 {stats.get('tracks', 0)} 首 · 歌单 {stats.get('playlists', 0)} 个 · "
            f"喜欢 {stats.get('favorites', 0)} 首\n"
            f"总时长 {stats.get('total_duration', '0 分钟')}"
        )
        stats_label = QLabel(stats_text)
        stats_label.setObjectName("Dim")
        stats_label.setWordWrap(True)
        root.addWidget(stats_label)

        about = QLabel("轻音播放器 v2.1.6 · 纯本地播放，无需联网")
        about.setObjectName("Dim")
        root.addWidget(about)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("Primary")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

    def _on_theme(self, name: str) -> None:
        if name != self._theme_name:
            self._theme_name = name
            self.theme_changed.emit(name)


def format_duration(total_ms: int) -> str:
    minutes = total_ms // 60000
    if minutes < 60:
        return f"{minutes} 分钟"
    return f"{minutes // 60} 小时 {minutes % 60} 分钟"


def stats_for(store) -> dict:
    tracks = store.all_tracks()
    return {
        "tracks": len(tracks),
        "playlists": len(store.user_playlists()),
        "favorites": store.favorite_count(),
        "total_duration": format_duration(sum(t.duration_ms for t in tracks)),
    }
