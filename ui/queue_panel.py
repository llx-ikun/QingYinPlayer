# -*- coding: utf-8 -*-
"""播放队列浮层（Qt.Popup）：展示当前播放队列，当前曲高亮，点击跳转。

- 从播放栏队列按钮处弹出，点击面板外自动关闭；
- exec_at(global_pos) 返回被点击的 track_id（取消/点外部返回 None）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui import icons as ic
from ui.theme import current_theme
from ui.widgets import ElidedLabel

_ROW_H = 40
_MAX_H = 420


class QueuePanel(QDialog):
    def __init__(self, ids: list[str], current_index: int, text_getter, parent=None):
        """
        ids: 当前队列（播放顺序）；current_index: 当前曲位置（-1 表示无）；
        text_getter: callable(tid) -> (title, artist)
        """
        super().__init__(parent)
        self.setObjectName("QueuePanel")
        self.setWindowFlags(Qt.WindowType.Popup)
        self._chosen: str | None = None
        self._ids = list(ids)
        self._current_index = current_index

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        header = QLabel(f"播放队列 · {len(self._ids)} 首")
        header.setObjectName("Dim")
        root.addWidget(header)

        self.list = QListWidget()
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(self._on_clicked)
        root.addWidget(self.list)

        theme = current_theme()
        for i, tid in enumerate(self._ids):
            title, artist = text_getter(tid)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, tid)
            item.setSizeHint(self._row_size())
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 0, 8, 0)
            row_layout.setSpacing(8)
            if i == current_index:
                icon = QLabel()
                icon.setPixmap(ic.make_pixmap("playing", theme.ACCENT, 13))
                icon.setFixedWidth(18)
                row_layout.addWidget(icon)
            else:
                index_lbl = QLabel(str(i + 1))
                index_lbl.setObjectName("Dim")
                index_lbl.setFixedWidth(18)
                index_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                row_layout.addWidget(index_lbl)
            text_col = QVBoxLayout()
            text_col.setSpacing(0)
            title_lbl = ElidedLabel(title)
            title_lbl.setObjectName("TrackTitle")
            if i == current_index:
                title_lbl.setStyleSheet(f"color: {theme.ACCENT}; font-weight: bold;")
            text_col.addWidget(title_lbl)
            if artist:
                artist_lbl = ElidedLabel(artist)
                artist_lbl.setObjectName("TrackSub")
                text_col.addWidget(artist_lbl)
            row_layout.addLayout(text_col, 1)
            self.list.addItem(item)
            self.list.setItemWidget(item, row)

        height = 30 + len(self._ids) * _ROW_H + 24
        self.setFixedSize(320, min(_MAX_H, height))
        if len(self._ids) * _ROW_H + 54 > _MAX_H:
            self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self.list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    @staticmethod
    def _row_size():
        from PySide6.QtCore import QSize
        return QSize(280, _ROW_H)

    def exec_at(self, global_pos) -> str | None:
        """在 global_pos 上方居中弹出；返回点击的 track_id 或 None。"""
        from PySide6.QtCore import QPoint
        x = global_pos.x() - self.width() // 2
        y = global_pos.y() - self.height() - 8
        self.move(QPoint(x, y))
        self.exec()
        return self._chosen

    def _on_clicked(self, item: QListWidgetItem) -> None:
        self._chosen = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
        super().keyPressEvent(event)
