# -*- coding: utf-8 -*-
"""矢量图标工厂：全部用 QPainter 手绘，避免不同系统 emoji 字体渲染差异。

用法：make_icon("play", color) -> QIcon
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap

_cache: dict[tuple, QIcon] = {}


def _paint(kind: str, size: int, color: QColor) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = p.pen()
    pen.setColor(color)
    pen.setWidthF(max(1.2, size * 0.085))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(color)

    u = size  # 画布单位
    m = u * 0.16  # 边距

    if kind == "play":
        path = QPainterPath()
        path.moveTo(u * 0.30, u * 0.22)
        path.lineTo(u * 0.80, u * 0.50)
        path.lineTo(u * 0.30, u * 0.78)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "pause":
        p.drawRoundedRect(QRectF(u * 0.28, u * 0.22, u * 0.14, u * 0.56), u * 0.03, u * 0.03)
        p.drawRoundedRect(QRectF(u * 0.58, u * 0.22, u * 0.14, u * 0.56), u * 0.03, u * 0.03)
    elif kind == "prev":
        path = QPainterPath()
        path.moveTo(u * 0.30, u * 0.26)
        path.lineTo(u * 0.72, u * 0.50)
        path.lineTo(u * 0.30, u * 0.74)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(u * 0.76, u * 0.26), QPointF(u * 0.76, u * 0.74))
    elif kind == "next":
        path = QPainterPath()
        path.moveTo(u * 0.70, u * 0.26)
        path.lineTo(u * 0.28, u * 0.50)
        path.lineTo(u * 0.70, u * 0.74)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(u * 0.24, u * 0.26), QPointF(u * 0.24, u * 0.74))
    elif kind == "volume":
        p.drawPolygon([QPointF(u * 0.20, u * 0.38), QPointF(u * 0.34, u * 0.38),
                       QPointF(u * 0.46, u * 0.26), QPointF(u * 0.46, u * 0.74),
                       QPointF(u * 0.34, u * 0.62), QPointF(u * 0.20, u * 0.62)])
        p.drawArc(QRectF(u * 0.50, u * 0.34, u * 0.22, u * 0.32), -50 * 16, 100 * 16)
        p.drawArc(QRectF(u * 0.60, u * 0.24, u * 0.34, u * 0.52), -50 * 16, 100 * 16)
    elif kind == "mute":
        p.drawPolygon([QPointF(u * 0.20, u * 0.38), QPointF(u * 0.34, u * 0.38),
                       QPointF(u * 0.46, u * 0.26), QPointF(u * 0.46, u * 0.74),
                       QPointF(u * 0.34, u * 0.62), QPointF(u * 0.20, u * 0.62)])
        p.drawLine(QPointF(u * 0.56, u * 0.40), QPointF(u * 0.82, u * 0.62))
        p.drawLine(QPointF(u * 0.82, u * 0.40), QPointF(u * 0.56, u * 0.62))
    elif kind == "loop":
        p.drawArc(QRectF(m, m, u - 2 * m, u - 2 * m), 40 * 16, 300 * 16)
        # 箭头
        p.drawLine(QPointF(u * 0.78, u * 0.16), QPointF(u * 0.88, u * 0.28))
        p.drawLine(QPointF(u * 0.88, u * 0.28), QPointF(u * 0.70, u * 0.32))
    elif kind == "repeat_one":
        p.drawArc(QRectF(m, m, u - 2 * m, u - 2 * m), 40 * 16, 300 * 16)
        p.drawLine(QPointF(u * 0.78, u * 0.16), QPointF(u * 0.88, u * 0.28))
        p.drawLine(QPointF(u * 0.88, u * 0.28), QPointF(u * 0.70, u * 0.32))
        p.drawText(QRectF(u * 0.30, u * 0.30, u * 0.40, u * 0.40), int(Qt.AlignmentFlag.AlignCenter), "1")
    elif kind == "shuffle":
        p.drawLine(QPointF(u * 0.18, u * 0.72), QPointF(u * 0.42, u * 0.42))
        p.drawLine(QPointF(u * 0.42, u * 0.42), QPointF(u * 0.78, u * 0.78))
        p.drawLine(QPointF(u * 0.24, u * 0.26), QPointF(u * 0.80, u * 0.66))
        p.drawLine(QPointF(u * 0.18, u * 0.72), QPointF(u * 0.18, u * 0.58))
        p.drawLine(QPointF(u * 0.18, u * 0.86), QPointF(u * 0.18, u * 0.72))
        p.drawLine(QPointF(u * 0.82, u * 0.14), QPointF(u * 0.82, u * 0.28))
        p.drawLine(QPointF(u * 0.82, u * 0.42), QPointF(u * 0.82, u * 0.56))
    elif kind == "sequential":
        # 列表顺序图标：三条线 + 右向小三角
        p.drawLine(QPointF(u * 0.16, u * 0.28), QPointF(u * 0.58, u * 0.28))
        p.drawLine(QPointF(u * 0.16, u * 0.50), QPointF(u * 0.58, u * 0.50))
        p.drawLine(QPointF(u * 0.16, u * 0.72), QPointF(u * 0.58, u * 0.72))
        path = QPainterPath()
        path.moveTo(u * 0.62, u * 0.36)
        path.lineTo(u * 0.86, u * 0.50)
        path.lineTo(u * 0.62, u * 0.64)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "note":
        # 八分音符：符头椭圆 + 符杆 + 符尾
        p.drawEllipse(QRectF(u * 0.20, u * 0.58, u * 0.30, u * 0.22))
        p.drawLine(QPointF(u * 0.50, u * 0.68), QPointF(u * 0.50, u * 0.20))
        path = QPainterPath()
        path.moveTo(u * 0.50, u * 0.20)
        path.quadTo(u * 0.78, u * 0.30, u * 0.68, u * 0.52)
        p.drawPath(path)
    elif kind == "search":
        p.drawEllipse(QRectF(u * 0.20, u * 0.20, u * 0.50, u * 0.50))
        p.drawLine(QPointF(u * 0.62, u * 0.62), QPointF(u * 0.82, u * 0.82))
    elif kind == "plus":
        p.drawLine(QPointF(u * 0.22, u * 0.50), QPointF(u * 0.78, u * 0.50))
        p.drawLine(QPointF(u * 0.50, u * 0.22), QPointF(u * 0.50, u * 0.78))
    elif kind == "folder":
        path = QPainterPath()
        path.moveTo(u * 0.16, u * 0.30)
        path.lineTo(u * 0.42, u * 0.30)
        path.lineTo(u * 0.50, u * 0.40)
        path.lineTo(u * 0.84, u * 0.40)
        path.lineTo(u * 0.84, u * 0.74)
        path.lineTo(u * 0.16, u * 0.74)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "trash":
        p.drawLine(QPointF(u * 0.24, u * 0.30), QPointF(u * 0.76, u * 0.30))
        p.drawLine(QPointF(u * 0.38, u * 0.24), QPointF(u * 0.62, u * 0.24))
        path = QPainterPath()
        path.moveTo(u * 0.32, u * 0.32)
        path.lineTo(u * 0.38, u * 0.78)
        path.lineTo(u * 0.62, u * 0.78)
        path.lineTo(u * 0.68, u * 0.32)
        p.drawPath(path)
    elif kind == "close":
        p.drawLine(QPointF(u * 0.26, u * 0.26), QPointF(u * 0.74, u * 0.74))
        p.drawLine(QPointF(u * 0.74, u * 0.26), QPointF(u * 0.26, u * 0.74))
    elif kind == "lyrics":
        for i, y in enumerate((0.26, 0.44, 0.62)):
            width = 0.56 if i != 1 else 0.40
            p.drawLine(QPointF(u * 0.20, u * y), QPointF(u * (0.20 + width), u * y))
    elif kind == "clock":
        p.drawEllipse(QRectF(m, m, u - 2 * m, u - 2 * m))
        p.drawLine(QPointF(u * 0.50, u * 0.50), QPointF(u * 0.50, u * 0.28))
        p.drawLine(QPointF(u * 0.50, u * 0.50), QPointF(u * 0.66, u * 0.58))
    elif kind == "library":
        p.drawEllipse(QRectF(u * 0.20, u * 0.20, u * 0.60, u * 0.60))
        p.drawEllipse(QRectF(u * 0.20, u * 0.42, u * 0.60, u * 0.60))
    elif kind == "playing":
        # 音量条动画的静态帧（动态版见 EqualizerBars）
        for i, h in enumerate((0.36, 0.60, 0.44)):
            x = u * (0.28 + i * 0.20)
            p.drawRoundedRect(QRectF(x, u * 0.50 - u * h / 2, u * 0.10, u * h), u * 0.02, u * 0.02)
    elif kind == "external":
        p.drawRoundedRect(QRectF(u * 0.20, u * 0.20, u * 0.44, u * 0.44), u * 0.06, u * 0.06)
        p.drawLine(QPointF(u * 0.58, u * 0.42), QPointF(u * 0.82, u * 0.18))
        p.drawLine(QPointF(u * 0.62, u * 0.18), QPointF(u * 0.82, u * 0.18))
        p.drawLine(QPointF(u * 0.82, u * 0.18), QPointF(u * 0.82, u * 0.38))
    else:  # 未知类型画个圆点
        p.drawEllipse(QRectF(u * 0.35, u * 0.35, u * 0.30, u * 0.30))

    p.end()
    return pm


def make_icon(kind: str, color: str, size: int = 16) -> QIcon:
    """生成（带缓存的）QIcon。color 为 '#rrggbb'。"""
    key = (kind, color, size)
    icon = _cache.get(key)
    if icon is None:
        icon = QIcon(_paint(kind, size, QColor(color)))
        _cache[key] = icon
    return icon
