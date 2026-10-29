# -*- coding: utf-8 -*-
"""矢量图标工厂：全部用 QPainter 手绘，避免不同系统 emoji 字体渲染差异。

用法：make_icon("play", color) -> QIcon
"""
from __future__ import annotations

import weakref

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap

_cache: dict[tuple, QIcon] = {}


def device_ratio() -> float:
    """当前屏幕的缩放比（125% → 1.25）。

    图标必须按**设备像素**渲染再标上 DPR，否则 16px 位图会在高分屏上被放大
    1.25~1.5 倍绘制，抗锯齿一糊，齿轮这种多齿形状就变成一团灰点（v2.5 实测：
    125% 下 16px 齿轮的有效深色区域只剩 ~11 设备像素，整窗截图里读成脏点）。
    没有 QGuiApplication 时（构建脚本 / 纯逻辑测试）退回 1.0。
    """
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return 1.0
    return max(1.0, float(screen.devicePixelRatio()))


def _paint(kind: str, size: int, color: QColor, dpr: float = 1.0) -> QPixmap:
    # 画布用设备像素；`size` 仍是逻辑尺寸，两处分开才能让笔画边界落在整像素上。
    px = max(1, round(size * dpr))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = p.pen()
    pen.setColor(color)
    pen.setWidthF(max(1.2 * dpr, px * 0.085))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(color)

    u = px  # 画布单位（设备像素）
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
        # 羽毛：实心羽片 + 镂空羽轴 + 两侧羽枝缺口。
        # **v2.5.1 起主题钮不再用它**（改成月亮，16px 下羽毛仍读不出形状），
        # 保留这个字形作为备选（深色主题的装饰语汇里仍有羽毛）。
        # 首版是「羽轴 + 8 条细羽枝」（纯线条），出验收表后发现 16px 下糊成一小团
        # 灰点，和相邻的 settings（细横线）撞气质 —— 必须靠实心轮廓才站得住。
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
        # 齿轮：实心厚环 + 8 个「短而宽」的梯形齿 + 镂空轴孔。
        #
        # 为什么不用「圆环 + 8 条短射线」：那样在 16px 下与 sun（实心圆点 + 细长
        # 射线）几乎无法区分，而齿轮就排在主题钮正下方，用户会以为两个都是换主题的。
        #
        # v2.5 重画（用户圈图「优化一下图案」）。旧版 8 齿但齿深 0.16、齿顶平台只占
        # 0.28 步、轴孔 Ø0.28 —— 齿又长又尖、齿谷和齿一样宽，轮廓读成多角星；再叠加
        # 高分屏把 16px 位图放大绘制（见 `device_ratio()`），整窗截图里就是一团灰点。
        # 现在按「厚环 + 短宽齿」重排，三处关键参数：
        #   ① 齿深 0.16 → 0.12（齿顶 0.47 / 齿根 0.35）：环体明显占主导，
        #      齿只是环上的凸起，才不会读成星星；
        #   ② 齿顶平台 0.28 → 0.44 步、齿面斜边收到 0.09 步：齿顶是宽平面，
        #      不是尖角——这是「齿轮」而不是「星形」的决定性特征；
        #   ③ 轴孔 Ø0.28 → Ø0.30 且环体加厚：20px 下孔径 6px、环宽 4px，
        #      孔和环都稳定（孔再小会被抗锯齿填掉一半）。
        # 参数是在 20px / 24px 设备像素上逐个比过才定的（16px 判断会得出错误结论）。
        import math
        teeth = 8
        r_tip, r_root = 0.47, 0.35
        plateau, flank = 0.44, 0.09
        step = 2 * math.pi / teeth
        # 齿根 → 齿顶平台起 → 齿顶平台止 → 回落齿根；末点到下一齿起点之间即齿谷
        profile = ((0.00, r_root), (flank, r_tip),
                   (flank + plateau, r_tip), (flank * 2 + plateau, r_root))
        outline = QPainterPath()
        for i in range(teeth):
            for frac, radius in profile:
                angle = i * step + frac * step
                point = QPointF(0.5 + radius * math.cos(angle),
                                0.5 + radius * math.sin(angle))
                if outline.elementCount() == 0:
                    outline.moveTo(u * point.x(), u * point.y())
                else:
                    outline.lineTo(u * point.x(), u * point.y())
        outline.closeSubpath()
        hole = QPainterPath()
        hole.addEllipse(QRectF(u * 0.35, u * 0.35, u * 0.30, u * 0.30))
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
        # 月亮（v2.5.1 起作为「切到深色」的主题钮图标；原来这里用的是羽毛，
        # 16px 下糊成一团认不出，用户圈图要求「画成月亮」）。
        #
        # 用**两圆差集**画月牙：尖角是两个圆真实相交处，天然锐利。
        # 千万别用 arcMoveTo + arcTo 拼两段弧——两个弧端点之间会连一条直线弦，
        # 月牙被削平成"灰色 D"（v2.3.6 深色背景装饰踩过同一个坑，见 DESIGN §17.2）。
        #
        # 参数在 20/24 设备像素上比过：外圆 R=0.42（占满画布）、内圆 0.90R 右移 0.16、
        # 整体转 -30°（经典月亮的斜开口）。太薄（k>0.95）小尺寸下会断成一弯细线。
        p.save()
        p.translate(u * 0.5, u * 0.5)
        p.rotate(-30)
        p.translate(-u * 0.5, -u * 0.5)
        r_out = 0.42
        r_in = r_out * 0.90
        dx = 0.16
        outer = QPainterPath()
        outer.addEllipse(QRectF(u * (0.5 - r_out), u * (0.5 - r_out),
                                u * r_out * 2, u * r_out * 2))
        inner = QPainterPath()
        inner.addEllipse(QRectF(u * (0.5 + dx - r_in), u * (0.5 - r_in),
                                u * r_in * 2, u * r_in * 2))
        p.fillPath(outer.subtracted(inner), color)
        p.restore()
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
    pm.setDevicePixelRatio(dpr)   # 告诉 Qt：这是 dpr 倍的位图，按逻辑尺寸绘制
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
    """生成（带缓存的）QIcon。color 为 '#rrggbb'。

    位图按当前屏幕缩放比渲染并标记 DPR，高分屏上才不会被放大糊掉
    （见 `device_ratio()`）。缓存键带上 dpr，换屏幕不会拿到旧比例的小图。
    """
    dpr = device_ratio()
    key = (kind, color, size, dpr)
    icon = _cache.get(key)
    if icon is None:
        icon = QIcon(_paint(kind, size, QColor(color), dpr))
        _cache[key] = icon
    return icon


def make_pixmap(kind: str, color: str, size: int = 16) -> QPixmap:
    """直接给 QLabel.setPixmap 用（不走 QIcon）。

    `QIcon.pixmap(18, 18)` 的两参重载默认按 DPR=1 取图，会把高分屏位图又降采样
    回去；这里直接拿 `_paint` 的 DPR 位图，QLabel 会按逻辑尺寸正确显示。
    """
    return _paint(kind, size, QColor(color), device_ratio())
