# -*- coding: utf-8 -*-
"""矢量图标工厂：全部用 QPainter 手绘，避免不同系统 emoji 字体渲染差异。

用法：make_icon("play", color) -> QIcon
"""
from __future__ import annotations

import weakref

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
        path.moveTo(u * 0.30, u * 0.20)
        path.lineTo(u * 0.80, u * 0.50)
        path.lineTo(u * 0.30, u * 0.80)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "pause":
        # 加宽竖线（0.16 宽 / 间距 0.14），40px 圆内更饱满，不再显得空
        p.drawRoundedRect(QRectF(u * 0.27, u * 0.21, u * 0.16, u * 0.58), u * 0.04, u * 0.04)
        p.drawRoundedRect(QRectF(u * 0.57, u * 0.21, u * 0.16, u * 0.58), u * 0.04, u * 0.04)
    elif kind == "prev":
        # ⏮ = 竖线在左 + 三角朝左（「退回上一首」）。此前 prev/next 画反了：
        # prev 画成 ▶|（前进形状）、next 画成 |◀，按钮语义与图形相反。
        p.drawLine(QPointF(u * 0.24, u * 0.30), QPointF(u * 0.24, u * 0.70))
        path = QPainterPath()
        path.moveTo(u * 0.72, u * 0.29)
        path.lineTo(u * 0.31, u * 0.50)
        path.lineTo(u * 0.72, u * 0.71)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "next":
        # ⏭ = 三角朝右 + 竖线在右
        path = QPainterPath()
        path.moveTo(u * 0.28, u * 0.29)
        path.lineTo(u * 0.69, u * 0.50)
        path.lineTo(u * 0.28, u * 0.71)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(u * 0.76, u * 0.30), QPointF(u * 0.76, u * 0.70))
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
        # 列表循环：上下两条横线 + 两端反向箭头（通用 repeat 图形）。
        # 旧版是「一段 300° 圆弧 + 两条斜线当箭头」，16px 下看起来像刷新按钮，
        # 与「循环播放」语义不符，已重画。
        p.drawLine(QPointF(u * 0.24, u * 0.33), QPointF(u * 0.64, u * 0.33))
        path = QPainterPath()
        path.moveTo(u * 0.64, u * 0.22)
        path.lineTo(u * 0.80, u * 0.33)
        path.lineTo(u * 0.64, u * 0.44)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(u * 0.76, u * 0.67), QPointF(u * 0.36, u * 0.67))
        path = QPainterPath()
        path.moveTo(u * 0.36, u * 0.56)
        path.lineTo(u * 0.20, u * 0.67)
        path.lineTo(u * 0.36, u * 0.78)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "repeat_one":
        # 单曲循环：同 repeat，中间加一个「1」。
        p.drawLine(QPointF(u * 0.24, u * 0.26), QPointF(u * 0.64, u * 0.26))
        path = QPainterPath()
        path.moveTo(u * 0.64, u * 0.15)
        path.lineTo(u * 0.80, u * 0.26)
        path.lineTo(u * 0.64, u * 0.37)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(u * 0.76, u * 0.74), QPointF(u * 0.36, u * 0.74))
        path = QPainterPath()
        path.moveTo(u * 0.36, u * 0.63)
        path.lineTo(u * 0.20, u * 0.74)
        path.lineTo(u * 0.36, u * 0.85)
        path.closeSubpath()
        p.drawPath(path)
        # 「1」用矢量画（text 在 16px 下依赖字体、易歪）：竖笔 + 左上小旗
        p.drawLine(QPointF(u * 0.50, u * 0.36), QPointF(u * 0.50, u * 0.66))
        p.drawLine(QPointF(u * 0.42, u * 0.43), QPointF(u * 0.50, u * 0.36))
    elif kind == "shuffle":
        # 随机播放：两条交叉的「车道」+ 右端箭头（通用 shuffle 图形）。
        # 旧版是 7 段互不相连的碎线，16px 下完全读不出形状。
        for y0, y1 in ((0.32, 0.68), (0.68, 0.32)):
            path = QPainterPath()
            path.moveTo(u * 0.18, u * y0)
            path.lineTo(u * 0.40, u * y0)
            path.lineTo(u * 0.66, u * y1)
            path.lineTo(u * 0.74, u * y1)
            p.drawPath(path)
            arrow = QPainterPath()
            arrow.moveTo(u * 0.72, u * (y1 - 0.09))
            arrow.lineTo(u * 0.86, u * y1)
            arrow.lineTo(u * 0.72, u * (y1 + 0.09))
            arrow.closeSubpath()
            p.drawPath(arrow)
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
    elif kind == "feather":
        # 羽毛（「空月」主题钮）：**实心羽片 + 镂空羽轴 + 两侧羽枝缺口**。
        # 首版是「羽轴 + 8 条细羽枝」（纯线条），出验收表后发现 16px 下糊成一小团
        # 灰点，和相邻的 settings（细横线）撞气质 —— 主题钮是最常被点到的按钮，
        # 必须靠实心轮廓才站得住（同 gear 的教训）。
        p.save()
        p.translate(u * 0.5, u * 0.5)
        p.rotate(-42)  # 羽尖朝右上，和界面里其他斜向元素同方向
        blade = QPainterPath()
        blade.moveTo(-u * 0.32, 0)
        blade.cubicTo(-u * 0.20, -u * 0.23, u * 0.10, -u * 0.23, u * 0.32, -u * 0.03)
        blade.cubicTo(u * 0.12, u * 0.20, -u * 0.16, u * 0.22, -u * 0.32, 0)
        blade.closeSubpath()
        cuts = QPainterPath()
        cuts.addRect(QRectF(-u * 0.38, -u * 0.028, u * 0.74, u * 0.056))  # 羽轴细缝
        for i in range(3):  # 羽枝缺口：越靠羽尖越短，缺口必须切穿羽片边缘
            cx = -u * 0.16 + i * u * 0.16
            ln = u * (0.28 - i * 0.06)
            cuts.addRect(QRectF(cx, u * 0.02, u * 0.04, ln))
            cuts.addRect(QRectF(cx, -u * 0.02 - ln, u * 0.04, ln))
        p.setBrush(color)
        p.fillPath(blade.subtracted(cuts), color)
        p.restore()
    elif kind == "gear":
        # 齿轮：实心 + 锯齿外轮廓 + 中心镂空圆孔。
        # 为什么不用「圆环 + 8 条短射线」：那样在 16px 下与 sun（实心圆点 + 细长
        # 射线）几乎无法区分，而齿轮就排在主题钮正下方，用户会以为两个都是换主题的。
        # 靠「宽齿的锯齿轮廓」而不是「细线」来识别，小尺寸下才站得住。
        import math
        teeth = 8
        r_root, r_tip = 0.29, 0.45
        step = 2 * math.pi / teeth
        outline = QPainterPath()
        for i in range(teeth):
            a0 = i * step
            # 齿根 → 上升沿 → 齿顶平台 → 下降沿，回到齿根
            for frac, r in ((0.0, r_root), (0.16, r_tip), (0.44, r_tip), (0.60, r_root)):
                ang = a0 + frac * step
                x, y = 0.5 + r * math.cos(ang), 0.5 + r * math.sin(ang)
                if outline.elementCount() == 0:
                    outline.moveTo(u * x, u * y)
                else:
                    outline.lineTo(u * x, u * y)
        outline.closeSubpath()
        hole = QPainterPath()
        hole.addEllipse(QRectF(u * 0.36, u * 0.36, u * 0.28, u * 0.28))
        p.setBrush(color)
        p.fillPath(outline.subtracted(hole), color)
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
    # ---------- v2.1 视频 ----------
    elif kind == "video":
        # 摄像机：机身 + 镜头 + 右侧取景框
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(u * 0.14, u * 0.30, u * 0.42, u * 0.40), u * 0.06, u * 0.06)
        path = QPainterPath()
        path.moveTo(u * 0.60, u * 0.42)
        path.lineTo(u * 0.84, u * 0.30)
        path.lineTo(u * 0.84, u * 0.70)
        path.lineTo(u * 0.60, u * 0.58)
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "fullscreen":
        # 四角括号
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(u * 0.18, u * 0.38), QPointF(u * 0.18, u * 0.18))
        p.drawLine(QPointF(u * 0.18, u * 0.18), QPointF(u * 0.38, u * 0.18))
        p.drawLine(QPointF(u * 0.82, u * 0.38), QPointF(u * 0.82, u * 0.18))
        p.drawLine(QPointF(u * 0.82, u * 0.18), QPointF(u * 0.62, u * 0.18))
        p.drawLine(QPointF(u * 0.18, u * 0.62), QPointF(u * 0.18, u * 0.82))
        p.drawLine(QPointF(u * 0.18, u * 0.82), QPointF(u * 0.38, u * 0.82))
        p.drawLine(QPointF(u * 0.82, u * 0.62), QPointF(u * 0.82, u * 0.82))
        p.drawLine(QPointF(u * 0.82, u * 0.82), QPointF(u * 0.62, u * 0.82))
    elif kind == "video_fill":
        # 实心播放三角（视频列表行徽标用）
        path = QPainterPath()
        path.moveTo(u * 0.32, u * 0.26)
        path.lineTo(u * 0.76, u * 0.50)
        path.lineTo(u * 0.32, u * 0.74)
        path.closeSubpath()
        p.drawPath(path)
    else:  # 未知类型画个圆点
        p.drawEllipse(QRectF(u * 0.35, u * 0.35, u * 0.30, u * 0.30))

    p.end()
    return pm


# ---------- 主题化图标绑定（v2.0） ----------

# [(weakref(target), kind, size, role)]；用弱引用持有 target，控件销毁后自动
# 从注册表失效，避免跨窗口/跨测试累积的强引用在 refresh_icons 时对已销毁的
# Shiboken 对象调 setIcon（曾导致 C++ 层偶发 hang）。
_bindings: list = []

_ROLE_MAP = ("text", "dim", "accent", "on_accent", "heart", "danger")


def _deref(ref):
    try:
        return ref()
    except TypeError:  # 兼容旧格式（直接对象）的遗留绑定
        return ref


def _role_color(role: str) -> str:
    from ui.theme import current_theme  # 延迟导入避免循环依赖
    t = current_theme()
    return {
        "text": t.TEXT, "dim": t.TEXT_DIM, "accent": t.ACCENT,
        "on_accent": t.ON_ACCENT, "heart": t.HEART, "danger": t.DANGER,
    }.get(role, t.TEXT_DIM)


def _unbind(target) -> None:
    for i, b in enumerate(_bindings):
        if _deref(b[0]) is target:
            del _bindings[i]
            return


def bind_icon(target, kind: str, size: int = 16, role: str = "dim") -> None:
    """把 target 的图标绑定到主题角色；重复绑定同一 target 以新参数覆盖。"""
    _unbind(target)
    target.setIcon(make_icon(kind, _role_color(role), size))
    _bindings.append((weakref.ref(target), kind, size, role))


def set_icon_kind(target, kind: str) -> None:
    """状态切换用：保持颜色角色不变，仅更换图标形状（如 play↔pause）。"""
    for i, (ref, _k, s, r) in enumerate(_bindings):
        t_ = _deref(ref)
        if t_ is target:
            t_.setIcon(make_icon(kind, _role_color(r), s))
            _bindings[i] = (ref, kind, s, r)
            return


def refresh_icons() -> None:
    """主题切换后重绘全部存活绑定；已销毁的控件经弱引用自动失效。"""
    alive = []
    for ref, kind, size, role in _bindings:
        target = _deref(ref)
        if target is None:
            continue  # 控件已销毁
        target.setIcon(make_icon(kind, _role_color(role), size))
        alive.append((ref, kind, size, role))
    _bindings[:] = alive


def make_icon(kind: str, color: str, size: int = 16) -> QIcon:
    """生成（带缓存的）QIcon。color 为 '#rrggbb'。"""
    key = (kind, color, size)
    icon = _cache.get(key)
    if icon is None:
        icon = QIcon(_paint(kind, size, QColor(color)))
        _cache[key] = icon
    return icon
