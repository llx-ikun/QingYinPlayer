# -*- coding: utf-8 -*-
"""歌词面板：同步高亮 + 平滑自动滚动 + 点击跳转。"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from app.lyrics import LyricLine, lyric_index_at
from ui.theme import ACCENT, TEXT_DIM


class LyricsPanel(QWidget):
    seek_requested = Signal(int)   # ms

    _NORMAL = QColor(TEXT_DIM)
    _PLAYED = QColor("#5a5a6e")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.list = QListWidget()
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.itemClicked.connect(self._on_clicked)
        root.addWidget(self.list, 1)

        self.empty_label = QLabel("暂无歌词\n支持同名 .lrc 文件与内嵌歌词")
        self.empty_label.setObjectName("Dim")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty_label)

        self._lines: list[LyricLine] = []
        self._plain: list[str] = []
        self._mode = "empty"  # empty | synced | plain
        self._current_index = -1
        self._anim: QPropertyAnimation | None = None
        self.set_empty()

    # ---------- 对外 ----------

    def set_synced(self, lines: list[LyricLine]) -> None:
        self._mode = "synced" if lines else "empty"
        self._lines = list(lines)
        self._plain = []
        self._current_index = -1
        self.list.clear()
        if lines:
            for line in lines:
                item = QListWidgetItem(line.text)
                item.setData(Qt.ItemDataRole.UserRole, line.time_ms)
                item.setForeground(self._NORMAL)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.list.addItem(item)
        self._refresh_visibility()

    def set_plain(self, lines: list[str]) -> None:
        self._mode = "plain" if lines else "empty"
        self._plain = list(lines)
        self._lines = []
        self._current_index = -1
        self.list.clear()
        if lines:
            for text in lines:
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, -1)
                item.setForeground(self._NORMAL)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.list.addItem(item)
        self._refresh_visibility()

    def set_empty(self, hint: str | None = None) -> None:
        self._mode = "empty"
        self._lines = []
        self._plain = []
        self._current_index = -1
        self.list.clear()
        if hint:
            self.empty_label.setText(hint)
        self._refresh_visibility()

    def update_position(self, position_ms: int) -> None:
        if self._mode != "synced" or not self._lines:
            return
        index = lyric_index_at(self._lines, position_ms)
        if index == self._current_index:
            return
        self._highlight(index)

    # ---------- 内部 ----------

    def _refresh_visibility(self) -> None:
        has = self._mode != "empty"
        self.list.setVisible(has)
        self.empty_label.setVisible(not has)

    def _highlight(self, index: int) -> None:
        old = self._current_index
        self._current_index = index
        for i in (old, index):
            if 0 <= i < self.list.count():
                self._style_item(self.list.item(i), i == index)
        if 0 <= index < self.list.count():
            self._smooth_scroll_to(self.list.item(index))

    def _style_item(self, item: QListWidgetItem, current: bool) -> None:
        font = QFont(item.font())
        if current:
            font.setPointSize(font.pointSize() + 3)
            font.setBold(True)
            item.setFont(font)
            item.setForeground(QColor(ACCENT))
        else:
            font.setBold(False)
            font.setPointSize(max(9, font.pointSize() - 3) if item.font().bold() else font.pointSize())
            item.setFont(font)
            item.setForeground(self._NORMAL)

    def _smooth_scroll_to(self, item: QListWidgetItem) -> None:
        bar = self.list.verticalScrollBar()
        rect = self.list.visualItemRect(item)
        if rect.height() == 0:
            return
        target = rect.top() + rect.height() // 2 - self.list.viewport().height() // 2
        target = max(bar.minimum(), min(bar.maximum(), target))
        if target == bar.value():
            return
        if self._anim is None:
            self._anim = QPropertyAnimation(bar, b"value", self)
            self._anim.setDuration(260)
            self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.stop()
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_clicked(self, item: QListWidgetItem) -> None:
        if self._mode != "synced":
            return
        time_ms = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(time_ms, int) and time_ms >= 0:
            self.seek_requested.emit(time_ms)
