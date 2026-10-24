# -*- coding: utf-8 -*-
"""通用小部件：省略号标签 / 可点击封面 / 均衡器动效条。"""
from __future__ import annotations

import time

from PySide6.QtCore import QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel, QWidget


class ElidedLabel(QLabel):
    """文本过长时自动省略（保留 tooltip 全量文本）。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = text
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self.setToolTip(text)
        super().setText(self._elide(text))

    def _elide(self, text: str) -> str:
        if not text:
            return text
        metrics = QFontMetrics(self.font())
        return metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(10, self.width() - 2))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        super().setText(self._elide(self._full))


class ClickableCover(QLabel):
    """显示封面图的标签，点击发信号；圆角由封面提供器烘焙进 pixmap。"""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit()
        super().mousePressEvent(event)


class EqualizerBars(QWidget):
    """播放中的音量条动效（3 根柱子的正弦起伏）。单实例使用，开销可忽略。"""

    _PHASE = {"t": time.time()}

    def __init__(self, parent=None, color: str = "#6c8cff", bar_count: int = 3):
        super().__init__(parent)
        self._color = QColor(color)
        self._bar_count = bar_count
        self._timer = QTimer(self)
        self._timer.setInterval(140)
        self._timer.timeout.connect(self.update)
        self.setFixedSize(18, 16)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(self._color)
        p.setPen(Qt.PenStyle.NoPen)
        t = time.time() * 6.0
        w = self.width()
        h = self.height()
        bar_w = max(2, w // (self._bar_count * 2))
        gap = (w - bar_w * self._bar_count) // (self._bar_count - 1) if self._bar_count > 1 else 0
        for i in range(self._bar_count):
            phase = t + i * 1.7
            amp = (math.sin(phase) + 1) / 2  # 0..1
            bar_h = max(3, int(h * (0.25 + 0.7 * amp)))
            x = i * (bar_w + gap)
            y = (h - bar_h) // 2
            p.drawRoundedRect(QRect(x, y, bar_w, bar_h), 1, 1)
        p.end()
