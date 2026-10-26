# -*- coding: utf-8 -*-
"""通用小部件：省略号标签 / 可点击封面 / 均衡器动效条 / 带箭头的下拉框。"""
from __future__ import annotations

import contextlib
import time
import weakref

from PySide6.QtCore import QPointF, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QLabel, QWidget

from ui.theme import current_theme


class ElidedLabel(QLabel):
    """文本过长时自动省略（保留 tooltip 全量文本）。

    省略延后到事件循环空闲时执行：QListWidget 行刚创建时，布局会先按
    sizeHint 宽度（如 78px）排一次再拉伸到最终宽度（如 150px），同步
    省略会在过渡宽度上把「新名字」截成「新…」——既造成刷新闪烁，也让
    测试在事件循环前读到截断文本。setText 先放全量文本，resize 只重启
    一个 0ms 单次定时器，连续 resize 自动合并，最终按稳定宽度省略。
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = text
        self._elide_timer: QTimer | None = None
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self.setToolTip(text)
        super().setText(text)
        self._schedule_elide()

    def full_text(self) -> str:
        """未被省略的完整文本。"""
        return self._full

    def _schedule_elide(self) -> None:
        if self._elide_timer is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(0)
            t.timeout.connect(self._apply_elide)
            self._elide_timer = t
        self._elide_timer.start()  # 重启即合并：连续 resize 只省略最后一次

    def _apply_elide(self) -> None:
        with contextlib.suppress(RuntimeError):  # 控件已销毁
            super().setText(self._elide(self._full))

    def _elide(self, text: str) -> str:
        if not text:
            return text
        width = self.width()
        if width < 24:
            return text
        metrics = QFontMetrics(self.font())
        return metrics.elidedText(text, Qt.TextElideMode.ElideRight, max(10, width - 2))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_elide()


class ClickableCover(QLabel):
    """显示封面图的标签，点击发信号；圆角由封面提供器烘焙进 pixmap。"""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit()
        super().mousePressEvent(event)


class EqualizerBars(QWidget):
    """播放中的音量条动效（3 根柱子的正弦起伏）。单实例使用，开销可忽略。"""

    _PHASE = {"t": time.time()}
    _instances: "weakref.WeakSet[EqualizerBars]" = weakref.WeakSet()

    def __init__(self, parent=None, color: str = "#6c8cff", bar_count: int = 3):
        super().__init__(parent)
        self._color = QColor(color)
        self._bar_count = bar_count
        self._timer = QTimer(self)
        self._timer.setInterval(140)
        self._timer.timeout.connect(self.update)
        self.setFixedSize(18, 16)
        EqualizerBars._instances.add(self)

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


def refresh_equalizers(color: str) -> None:
    """主题切换：更新全部存活均衡器条的颜色。"""
    for bars in list(EqualizerBars._instances):
        try:
            bars._color = QColor(color)
            bars.update()
        except RuntimeError:  # 已销毁
            pass


class ChevronComboBox(QComboBox):
    """下拉框 + 自绘 V 形展开指示。

    QSS 一旦覆盖 QComboBox::drop-down，Qt 就不再绘制系统箭头——列表的排序框
    曾因此长得像普通输入框，用户看不出可以点开。这里改为自绘，颜色跟随主题。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(current_theme().TEXT_DIM), 1.6,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        cx = self.width() - 14.0
        cy = self.height() / 2.0
        half, drop = 3.8, 2.2
        painter.drawLine(QPointF(cx - half, cy - drop), QPointF(cx, cy + drop))
        painter.drawLine(QPointF(cx, cy + drop), QPointF(cx + half, cy - drop))
        painter.end()
