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
    # ---------- v2.0 新增 ----------
    elif kind == "back":
        p.drawLine(QPointF(u * 0.80, u * 0.50), QPointF(u * 0.24, u * 0.50))
        path = QPainterPath()
        path.moveTo(u * 0.44, u * 0.30)
        path.lineTo(u * 0.24, u * 0.50)
        path.lineTo(u * 0.44, u * 0.70)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setBrush(color)
    elif kind == "forward":
        p.drawLine(QPointF(u * 0.20, u * 0.50), QPointF(u * 0.76, u * 0.50))
        path = QPainterPath()
        path.moveTo(u * 0.56, u * 0.30)
        path.lineTo(u * 0.76, u * 0.50)
        path.lineTo(u * 0.56, u * 0.70)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setBrush(color)
    elif kind == "refresh":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(m, m, u - 2 * m, u - 2 * m), 55 * 16, 290 * 16)
        p.setBrush(color)
        p.drawLine(QPointF(u * 0.86, u * 0.22), QPointF(u * 0.80, u * 0.40))
        p.drawLine(QPointF(u * 0.86, u * 0.22), QPointF(u * 0.68, u * 0.26))
    elif kind == "minimize":
        p.drawLine(QPointF(u * 0.26, u * 0.74), QPointF(u * 0.74, u * 0.74))
    elif kind == "maximize":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(m, m, u - 2 * m, u - 2 * m), u * 0.04, u * 0.04)
        p.setBrush(color)
    elif kind == "restore":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(u * 0.34, u * 0.14, u * 0.50, u * 0.50), u * 0.04, u * 0.04)
        p.drawRoundedRect(QRectF(u * 0.16, u * 0.36, u * 0.50, u * 0.50), u * 0.04, u * 0.04)
        p.setBrush(color)
    elif kind in ("heart", "heart_filled"):
        path = QPainterPath()
        path.moveTo(u * 0.50, u * 0.84)
        path.cubicTo(u * 0.10, u * 0.58, u * 0.08, u * 0.30, u * 0.30, u * 0.20)
        path.cubicTo(u * 0.42, u * 0.14, u * 0.48, u * 0.26, u * 0.50, u * 0.34)
        path.cubicTo(u * 0.52, u * 0.26, u * 0.58, u * 0.14, u * 0.70, u * 0.20)
        path.cubicTo(u * 0.92, u * 0.30, u * 0.90, u * 0.58, u * 0.50, u * 0.84)
        path.closeSubpath()
        if kind == "heart_filled":
            p.drawPath(path)
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setBrush(color)
    elif kind == "more":
        for x in (0.22, 0.50, 0.78):
            p.drawEllipse(QRectF(u * (x - 0.06), u * 0.44, u * 0.12, u * 0.12))
    elif kind == "queue":
        for y in (0.28, 0.50, 0.72):
            p.drawLine(QPointF(u * 0.16, u * y), QPointF(u * 0.56, u * y))
        path = QPainterPath()
        path.moveTo(u * 0.62, u * 0.34)
        path.lineTo(u * 0.88, u * 0.50)
        path.lineTo(u * 0.62, u * 0.66)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "settings":
        for y, kx in ((0.28, 0.64), (0.50, 0.36), (0.72, 0.70)):
            p.drawLine(QPointF(u * 0.16, u * y), QPointF(u * 0.84, u * y))
            p.drawEllipse(QRectF(u * (kx - 0.08), u * (y - 0.08), u * 0.16, u * 0.16))
    elif kind == "sun":
        p.drawEllipse(QRectF(u * 0.34, u * 0.34, u * 0.32, u * 0.32))
        import math
        for i in range(8):
            a = math.pi * i / 4
            x0, y0 = 0.5 + 0.26 * math.cos(a), 0.5 + 0.26 * math.sin(a)
            x1, y1 = 0.5 + 0.40 * math.cos(a), 0.5 + 0.40 * math.sin(a)
            p.drawLine(QPointF(u * x0, u * y0), QPointF(u * x1, u * y1))
    elif kind == "moon":
        path = QPainterPath()
        path.arcMoveTo(QRectF(u * 0.14, u * 0.14, u * 0.72, u * 0.72), 75)
        path.arcTo(QRectF(u * 0.14, u * 0.14, u * 0.72, u * 0.72), 75, 210)
        path.arcTo(QRectF(u * 0.36, u * 0.20, u * 0.52, u * 0.60), 285, -210)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "home":
        path = QPainterPath()
        path.moveTo(u * 0.50, u * 0.16)
        path.lineTo(u * 0.86, u * 0.46)
        path.lineTo(u * 0.86, u * 0.82)
        path.lineTo(u * 0.14, u * 0.82)
        path.lineTo(u * 0.14, u * 0.46)
        path.closeSubpath()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(u * 0.42, u * 0.58, u * 0.16, u * 0.24), u * 0.02, u * 0.02)
    else:  # 未知类型画个圆点
        p.drawEllipse(QRectF(u * 0.35, u * 0.35, u * 0.30, u * 0.30))

    p.end()
    return pm


# ---------- 主题化图标绑定（v2.0） ----------

# [(target, kind, size, role)]；target 为任何有 setIcon 的对象（按钮/QAction）
_bindings: list = []

_ROLE_MAP = ("text", "dim", "accent", "on_accent", "heart", "danger")


def _role_color(role: str) -> str:
    from ui.theme import current_theme  # 延迟导入避免循环依赖
    t = current_theme()
    return {
        "text": t.TEXT, "dim": t.TEXT_DIM, "accent": t.ACCENT,
        "on_accent": t.ON_ACCENT, "heart": t.HEART, "danger": t.DANGER,
    }.get(role, t.TEXT_DIM)


def _unbind(target) -> None:
    for i, b in enumerate(_bindings):
        if b[0] is target:
            del _bindings[i]
            return


def bind_icon(target, kind: str, size: int = 16, role: str = "dim") -> None:
    """把 target 的图标绑定到主题角色；重复绑定同一 target 以新参数覆盖。"""
    _unbind(target)
    target.setIcon(make_icon(kind, _role_color(role), size))
    _bindings.append((target, kind, size, role))


def set_icon_kind(target, kind: str) -> None:
    """状态切换用：保持颜色角色不变，仅更换图标形状（如 play↔pause）。"""
    for i, (t_, k, s, r) in enumerate(_bindings):
        if t_ is target:
            t_.setIcon(make_icon(kind, _role_color(r), s))
            _bindings[i] = (t_, kind, s, r)
            return


def refresh_icons() -> None:
    """主题切换后重绘全部绑定图标；已销毁的绑定自动清除。"""
    alive = []
    for target, kind, size, role in _bindings:
        try:
            target.setIcon(make_icon(kind, _role_color(role), size))
        except RuntimeError:  # 控件已销毁
            continue
        alive.append((target, kind, size, role))
    _bindings[:] = alive


def make_icon(kind: str, color: str, size: int = 16) -> QIcon:
    """生成（带缓存的）QIcon。color 为 '#rrggbb'。"""
    key = (kind, color, size)
    icon = _cache.get(key)
    if icon is None:
        icon = QIcon(_paint(kind, size, QColor(color)))
        _cache[key] = icon
    return icon
