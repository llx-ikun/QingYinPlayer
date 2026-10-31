# -*- coding: utf-8 -*-
"""自定义背景层（v2.2）：纯色 / 线性渐变 / 图片（可模糊、暗化、降透明度）。

为什么单独一层控件而不是往 QSS 里塞 background-image：
`background-image` 不能按窗口尺寸等比裁切（KeepAspectRatioByExpanding），
也不能模糊、不能暗化、不能只调背景透明度。这些全都要逐像素算，只有自绘画布能做。

分层关系（自下而上）：WindowRoot(QSS 底色) → BackgroundLayer → 标题栏/侧栏/内容/播放栏
所以主题里的面板色要转成半透明（见 theme.build_stylesheet(scrim=...)），
否则这一层会被完全盖住，用户会以为「设置了没反应」。
"""
from __future__ import annotations

import math
import os
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import QWidget

from app.models import BackgroundConfig

# 图片背景的缓存上限：换歌/切页会反复刷新，只缓存最近一张，避免吃内存
_PIXMAP_CACHE: dict[tuple, QPixmap] = {}

# 主题装饰的星点用固定种子生成 —— 每次重绘位置必须一致，否则窗口一缩放星星就乱跳
_DECOR_SEED = 20261027


def load_background_pixmap(path: str) -> QPixmap | None:
    """读图片并转成 QPixmap；不存在/读不动返回 None（不抛）。"""
    if not path or not os.path.isfile(path):
        return None
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return None
    return pixmap


def _approximate_blur(pixmap: QPixmap, radius: int) -> QPixmap:
    """用「降采样 → 平滑升采样」近似高斯模糊。

    为什么不用 QGraphicsBlurEffect：它在 1280×800 上要上百毫秒并且边缘会发黑，
    而背景是低频内容，降采样的效果肉眼等价、耗时几乎为零。
    半径越大降采样越狠，所以滑块的强弱变化是真实可见的。
    """
    if radius <= 0 or pixmap.isNull():
        return pixmap
    factor = max(2, int(radius / 1.5) + 1)
    small_w = max(1, pixmap.width() // factor)
    small_h = max(1, pixmap.height() // factor)
    small = pixmap.scaled(small_w, small_h,
                          Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
    return small.scaled(pixmap.width(), pixmap.height(),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)


def prepare_pixmap(path: str, width: int, height: int, blur: int) -> QPixmap | None:
    """把原图裁成铺满 (width, height) 并模糊；结果按 (path,size,blur) 缓存。"""
    if width <= 0 or height <= 0:
        return None
    key = (path, width, height, blur)
    cached = _PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached
    source = load_background_pixmap(path)
    if source is None:
        return None
    # KeepAspectRatioByExpanding + CenterCrop：铺满且不变形（留黑边比裁掉更难看）
    scaled = source.scaled(width, height,
                           Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    if scaled.width() > width or scaled.height() > height:
        x = max(0, (scaled.width() - width) // 2)
        y = max(0, (scaled.height() - height) // 2)
        scaled = scaled.copy(x, y, width, height)
    result = _approximate_blur(scaled, blur)
    _PIXMAP_CACHE.clear()          # 只留一张：背景图可能很大
    _PIXMAP_CACHE[key] = result
    return result


def _paint_four_point_star(painter: QPainter, cx: float, cy: float, r: float) -> None:
    """画一枚四角星（sparkle）：外端在上下左右、内凹点在四角，读起来像发光星点。"""
    k = r * 0.32
    path = QPainterPath()
    path.moveTo(cx, cy - r)
    path.lineTo(cx + k, cy - k)
    path.lineTo(cx + r, cy)
    path.lineTo(cx + k, cy + k)
    path.lineTo(cx, cy + r)
    path.lineTo(cx - k, cy + k)
    path.lineTo(cx - r, cy)
    path.lineTo(cx - k, cy - k)
    path.closeSubpath()
    painter.drawPath(path)


def _lighten(color: QColor, amount: float) -> QColor:
    """把颜色往白混 amount（0=原色，1=白）。用于提亮月牙/光晕，保留一点蓝紫调。"""
    amount = max(0.0, min(1.0, amount))
    return QColor(int(color.red() + (255 - color.red()) * amount),
                  int(color.green() + (255 - color.green()) * amount),
                  int(color.blue() + (255 - color.blue()) * amount))


def _paint_theme_decor(painter: QPainter, rect: QRectF, color: str,
                       style: str = "columbina") -> None:
    """主题底层装饰的分发入口。

    style="columbina"（深色）：午夜深蓝夜空——四角星 + 月牙 + 漂浮羽饰。
    style="light"（浅色·薰衣草）：玻璃质感——细线羽饰 + 低透明度四角星点缀。

    都只取主题强调色（color），alpha 压住，做氛围不抢内容。
    """
    if style == "light":
        _paint_light_decor(painter, rect, color)
    else:
        _paint_columbina_decor(painter, rect, color)


def _paint_concave_star(painter: QPainter, cx: float, cy: float, r: float,
                        concave: float = 0.15) -> QPainterPath:
    """四角星，边向内凹（「魔法闪光」那种形）。返回 path 供调用方决定描边/填充。"""
    path = QPainterPath()
    path.moveTo(cx, cy - r)
    path.quadTo(cx + r * concave, cy - r * concave, cx + r, cy)
    path.quadTo(cx + r * concave, cy + r * concave, cx, cy + r)
    path.quadTo(cx - r * concave, cy + r * concave, cx - r, cy)
    path.quadTo(cx - r * concave, cy - r * concave, cx, cy - r)
    path.closeSubpath()
    return path


def _paint_soft_feather(painter: QPainter, cx: float, cy: float, length: float,
                        angle: float, ink: QColor, alpha: int = 70) -> None:
    """一片**柔和**的羽毛：横向渐变填充（边缘透明、中线有色）+ 一根亮羽轴。

    参考图的浮羽是柔焦的写实羽毛，不是线描 —— 用「轮廓 + 细线」画出来会变成
    线稿插图，气质完全不同。所以这里靠渐变做柔边，不画硬轮廓。
    """
    half = length * 0.135
    painter.save()
    painter.translate(cx, cy)
    painter.rotate(angle)

    def half_width(u: float) -> float:
        """基部窄、中段（约 4 成处）最宽、羽尖渐收 —— 对称的 sin 会读成刀片/树叶。"""
        u = min(1.0, max(0.0, u))
        return half * math.sin(math.pi * u ** 0.82) ** 0.72

    blade = QPainterPath()
    blade.moveTo(0, 0)
    steps = 26
    for i in range(1, steps + 1):
        u = i / steps
        blade.lineTo(length * u, -half_width(u))
    for i in range(steps, -1, -1):
        u = i / steps
        blade.lineTo(length * u, half_width(u))
    blade.closeSubpath()

    edge = QColor(ink)
    edge.setAlpha(0)
    mid = QColor(ink)
    mid.setAlpha(alpha)
    grad = QLinearGradient(0, -half, 0, half)      # 局部坐标：横跨羽片
    grad.setColorAt(0.0, edge)
    grad.setColorAt(0.42, mid)
    grad.setColorAt(0.58, mid)
    grad.setColorAt(1.0, edge)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(grad)
    painter.drawPath(blade)

    # 羽枝：只要极淡几根，让柔化的羽片还读得出「羽毛」而不是「刀片」
    barb = QColor(ink)
    barb.setAlpha(max(20, int(alpha * 0.7)))
    bpen = QPen(barb)
    bpen.setWidthF(0.9)
    painter.setPen(bpen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for i in range(10):
        u = 0.14 + 0.74 * i / 9
        x = length * u
        for sign in (1, -1):
            w_u = half_width(u) * 0.9
            painter.drawLine(QPointF(x, 0), QPointF(x + w_u * 0.75, sign * w_u))

    # 羽轴：基部最亮、朝羽尖渐隐（参考图的浮羽就是「羽根发光」）
    shaft_grad = QLinearGradient(0, 0, length * 0.9, 0)
    s0 = QColor(ink)
    s0.setAlpha(min(255, alpha + 110))
    s1 = QColor(ink)
    s1.setAlpha(max(0, int(alpha * 0.25)))
    shaft_grad.setColorAt(0.0, s0)
    shaft_grad.setColorAt(0.45, s0)
    shaft_grad.setColorAt(1.0, s1)
    pen = QPen(QBrush(shaft_grad), 1.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(0, 0), QPointF(length * 0.88, 0))
    painter.restore()


def _paint_columbina_decor(painter: QPainter, rect: QRectF, color: str) -> None:
    """深色夜空（image 2）：玻璃月牙 + 轨道环 + 罗盘星 + 漂浮柔羽。

    从下往上分五层：径向辉光 → 星尘 → 轨道环（带刻度）→ 月牙 → 罗盘星 → 浮羽。

    月牙是**半透明玻璃**：亮的是那圈 1.6px 冷白描边，内部是低 alpha 的渐变填充。
    上一版是 alpha 205 的实心冷白块，在深底上读成"贴纸"而不是"发光体"——
    发光感来自**边缘比内部亮**，不是整体涂白。

    元素取自《原神》「空月之歌」的视觉语言（月与星、头饰披风的白羽），只复刻
    形状气质、不嵌入官方立绘（版权素材不随程序分发）。主题对外名字是「深色」。
    """
    w, h = rect.width(), rect.height()
    if w <= 0 or h <= 0:
        return
    unit = min(w, h)
    accent = QColor(color)
    glow_ink = _lighten(accent, 0.72)
    rim_ink = _lighten(accent, 0.90)      # 月牙/星芒的边缘：近冷白

    diameter = unit * 0.44
    cx, cy = w * 0.77, h * 0.40
    r_moon = diameter * 0.5
    ring_r = r_moon * 1.32

    # ---- 1) 月亮背后的径向辉光：让月亮「照亮」周围，而不是贴上去 ----
    halo_r = ring_r * 2.55          # 参考图的月光是**大范围**洗亮右半侧，不是贴着月亮的圈
    grad = QRadialGradient(QPointF(cx, cy), halo_r)
    for pos, alpha in ((0.0, 58), (0.34, 26), (0.62, 10), (1.0, 0)):
        c = QColor(glow_ink)
        c.setAlpha(alpha)
        grad.setColorAt(pos, c)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(grad)
    painter.drawEllipse(QPointF(cx, cy), halo_r, halo_r)

    # ---- 2) 星尘：固定种子，缩放不乱跳 ----
    rnd = random.Random(_DECOR_SEED)
    for _ in range(24):
        x, y = rnd.uniform(0.02, 0.99) * w, rnd.uniform(0.03, 0.99) * h
        c = QColor(_lighten(accent, 0.60))
        c.setAlpha(rnd.randint(30, 85))
        painter.setBrush(c)
        _paint_four_point_star(painter, x, y, rnd.uniform(1.8, 5.5))
    for _ in range(36):
        x, y = rnd.uniform(0, 1) * w, rnd.uniform(0, 1) * h
        c = QColor(_lighten(accent, 0.60))
        c.setAlpha(rnd.randint(20, 55))
        painter.setBrush(c)
        rr = rnd.uniform(0.6, 1.5)
        painter.drawEllipse(QPointF(x, y), rr, rr)

    # ---- 3) 轨道环 + 刻度：参考图里月牙外面套着一圈很细的轨道 ----
    painter.setBrush(Qt.BrushStyle.NoBrush)
    ring_c = QColor(_lighten(accent, 0.55))
    ring_c.setAlpha(44)
    ring_pen = QPen(ring_c)
    ring_pen.setWidthF(1.0)
    painter.setPen(ring_pen)
    painter.drawEllipse(QPointF(cx, cy), ring_r, ring_r)
    tick_c = QColor(_lighten(accent, 0.70))
    tick_c.setAlpha(78)
    tick_pen = QPen(tick_c)
    tick_pen.setWidthF(1.2)
    painter.setPen(tick_pen)
    for i in range(24):
        ang = math.radians(i * 15)
        inner_r = ring_r * (0.945 if i % 2 == 0 else 0.965)
        painter.drawLine(QPointF(cx + math.cos(ang) * inner_r, cy + math.sin(ang) * inner_r),
                         QPointF(cx + math.cos(ang) * ring_r * 1.035,
                                 cy + math.sin(ang) * ring_r * 1.035))

    # ---- 4) 月牙：两圆的**差集** + 淡填充 + 软内带 + 亮边 ----
    # 用两段圆弧拼（arcTo）会在两个弧的端点之间留一条直线弦，月牙的尖角被削平；
    # addEllipse().subtracted() 直接求差集，尖角是两个圆真实相交处，天然锐利。
    left, top = cx - r_moon, cy - r_moon
    outer_disc = QPainterPath()
    outer_disc.addEllipse(QRectF(left, top, diameter, diameter))
    inner_scale = 0.86
    inner_disc = QPainterPath()
    inner_disc.addEllipse(QRectF(left + diameter * 0.32,
                                 top + diameter * (1 - inner_scale) / 2,
                                 diameter * inner_scale, diameter * inner_scale))
    moon = outer_disc.subtracted(inner_disc)

    # 软内带：宽笔沿轮廓走一遍，让边缘往里"化"开，形成一个发光带
    for band_w, band_a, band_light in ((0.030, 9, 0.55), (0.012, 40, 0.72)):
        band_c = _lighten(accent, band_light)
        band_c.setAlpha(band_a)
        band = QPen(band_c)
        band.setWidthF(unit * band_w)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(band)
        painter.drawPath(moon)

    moon_fill = QLinearGradient(QPointF(left, top), QPointF(left + diameter, top))
    for pos, alpha, light in ((0.0, 10, 0.62), (0.55, 7, 0.42), (1.0, 4, 0.30)):
        c = _lighten(accent, light)
        c.setAlpha(alpha)
        moon_fill.setColorAt(pos, c)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(moon_fill)
    painter.drawPath(moon)

    rim_pen_c = QColor(rim_ink)
    rim_pen_c.setAlpha(196)
    rim = QPen(rim_pen_c)
    rim.setWidthF(1.6)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(rim)
    painter.drawPath(moon)

    # ---- 5) 罗盘星：坐在轨道环正下方交点，带竖杆与刻度 ----
    # 参考图里它在环的**右侧**，但右侧整片都是列表列（时长/编辑），星会压在图标上；
    # 挪到环的正下方：同样"骑在轨道上"，那片是空的，竖杆还正好接上环的竖直轴。
    sx, sy = cx, cy + ring_r
    r_star = unit * 0.048
    staff_c = QColor(_lighten(accent, 0.68))
    staff_c.setAlpha(84)
    staff_pen = QPen(staff_c)
    staff_pen.setWidthF(1.0)
    painter.setPen(staff_pen)
    painter.drawLine(QPointF(sx, sy - r_star * 3.6), QPointF(sx, sy + r_star * 1.5))
    painter.drawLine(QPointF(sx - r_star * 2.3, sy), QPointF(sx + r_star * 1.7, sy))
    for k in (-3.0, -2.45, -1.9, -1.35):
        y = sy + r_star * k
        painter.drawLine(QPointF(sx - r_star * 0.17, y + r_star * 0.15),
                         QPointF(sx, y))
        painter.drawLine(QPointF(sx + r_star * 0.17, y + r_star * 0.15),
                         QPointF(sx, y))

    body = _paint_concave_star(painter, sx, sy, r_star, concave=0.14)
    body_c = QColor(rim_ink)
    body_c.setAlpha(140)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(body_c)
    painter.drawPath(body)
    edge_pen = QPen(QColor(_lighten(accent, 0.96)))
    edge_pen.setWidthF(1.2)
    painter.setPen(edge_pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(body)
    # 四个斜向短尖，读出「罗盘」而不是普通闪点
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        painter.drawLine(QPointF(sx + dx * r_star * 0.26, sy + dy * r_star * 0.26),
                         QPointF(sx + dx * r_star * 0.52, sy + dy * r_star * 0.52))

    # ---- 6) 漂浮柔羽：几片散在夜空里，位置固定（缩放不乱跳）----
    feather_ink = _lighten(accent, 0.55)
    for fx, fy, ln, ang, alpha in ((0.315, 0.215, 0.170, -45, 44),
                                   (0.635, 0.110, 0.100, -20, 32),
                                   (0.945, 0.700, 0.230, 58, 50),
                                   (0.500, 0.870, 0.130, 14, 36)):
        _paint_soft_feather(painter, w * fx, h * fy, unit * ln, ang, feather_ink, alpha)


def _paint_light_decor(painter: QPainter, rect: QRectF, color: str) -> None:
    """浅色装饰（image 1）：右侧一支细线大羽毛 + 一枚带光环的罗盘星。

    参考图的疏朗感来自「少而大」：一支约 3/4 窗高的羽毛、一枚星、几点微光，
    其余全是留白。之前撒几十颗碎星铺满全窗，读起来是噪点，反而不像。

    羽毛轴线由羽尖 (0.955w, 0.155h) 与羽根 (0.795w, 1.02h) 决定（羽根落在窗口外，
    裸羽轴伸出画面）。倾角 ≈ 16°、长度 ≈ 0.9h，按参考图逐点量出来的比例。

    **线色不是强调色本身**：把强调色压深到 75% 再配高 alpha。用强调色 + 低 alpha
    试过，最深的线只到 173（背景 244），参考图是 140 —— 差 1.4 倍浓度，看着"发虚"。
    浅底上「看得见但不抢字」靠**线细 + 颜色深**，不靠涂大块（记忆 #51）。
    """
    w, h = rect.width(), rect.height()
    if w <= 0 or h <= 0:
        return
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(Qt.PenStyle.NoPen)

    accent = QColor(color)
    ink = QColor(int(accent.red() * 0.75), int(accent.green() * 0.75),
                 int(accent.blue() * 0.75))
    tip = QPointF(w * 0.955, h * 0.155)
    root = QPointF(w * 0.795, h * 1.020)   # 羽根落在窗口外：裸羽轴伸出画面（参考图同）

    def pen_of(alpha: int, width: float = 1.0) -> QPen:
        c = QColor(ink)
        c.setAlpha(alpha)
        pen = QPen(c)
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pen

    # ---- 羽毛（局部坐标：原点 = 羽根，+x 指向羽尖）----
    length = math.hypot(tip.x() - root.x(), tip.y() - root.y())
    lean = math.degrees(math.atan2(root.y() - tip.y(), tip.x() - root.x()))
    half = length * 0.135          # 最宽处半宽（参考图 羽宽/羽长 ≈ 0.26）
    VANE_START = 0.14              # 这根轴的 14% 之前是裸羽轴，羽片从 0 宽度长起

    def half_width(t: float) -> float:
        """沿轴 t(0~1) 处的半宽。

        先把 t 重映射到「羽片自己的 0~1」再取形，这样羽片根部是**从 0 长起来**、
        收拢成裸羽轴；直接对全轴取形会在 t=0.14 处留一个 36% 宽的硬截断，
        两条边悬在空中像被剪过。
        指数 1.15 让羽根收得细（羽片 10% 处只有峰值 26%）——参考图的羽毛从根部
        渐宽、到 6 成处最宽再收尖；用 t^0.72 会在根部就撑开，读成叶子。
        """
        u = (t - VANE_START) / (1.0 - VANE_START)
        u = min(1.0, max(0.0, u))
        return half * math.sin(math.pi * u ** 1.15) ** 0.9

    painter.save()
    painter.translate(root)
    painter.rotate(-lean)

    def silhouette(sign: int, scale: float = 1.0, t0: float = 0.0,
                   t1: float = 1.0, steps: int = 48) -> QPainterPath:
        """沿轴生成一侧边缘。轮廓线与羽枝共用它 —— 各画一套贝塞尔会让
        「边」和「梳齿」对不上，读成梯子（踩过）。

        两侧不等宽（右侧 100% / 左侧 92%）：真实羽毛的羽片不是左右对称的，
        完全对称会读成树叶/胶囊。
        """
        bulge = 1.0 if sign > 0 else 0.92
        path = QPainterPath()
        path.moveTo(length * t0, sign * half_width(t0) * scale * bulge)
        for i in range(1, steps + 1):
            t = t0 + (t1 - t0) * i / steps
            path.lineTo(length * t, sign * half_width(t) * scale * bulge)
        return path

    # 轮廓：两侧分开，右侧更实（参考图右缘最清楚），左侧淡一档。
    # 羽片从 t=0.14 才开始 —— 根部那一段是裸羽轴。
    for sign, alpha in ((1, 100), (-1, 78)):
        painter.setPen(pen_of(alpha, 1.1))
        painter.drawPath(silhouette(sign, t0=0.14))

    # 内侧嵌套一道细弧（参考图的「蚀刻感」：边缘里面还有一条平行线）
    painter.setPen(pen_of(46, 0.9))
    painter.drawPath(silhouette(1, scale=0.62, t0=0.20, t1=0.97))
    painter.drawPath(silhouette(-1, scale=0.66, t0=0.20, t1=0.97))

    # 羽枝：从羽轴向羽尖方向**斜扫**，到轮廓前收住（不碰到边线，否则成横档）。
    # 疏密按参考图一侧约 16 根。
    painter.setPen(pen_of(66, 0.9))
    steps = 16
    for i in range(steps):
        t = 0.17 + 0.78 * i / (steps - 1)
        x = length * t
        for sign in (1, -1):
            w_t = half_width(t) * 0.88
            painter.drawLine(QPointF(x, 0), QPointF(x + w_t * 0.85, sign * w_t))

    # 羽轴：比羽枝实一档，从羽根（画外）通到羽尖；带一点弧度，笔直的轴有塑料感
    painter.setPen(pen_of(140, 1.3))
    shaft = QPainterPath()
    shaft.moveTo(0, 0)
    shaft.quadTo(length * 0.50, -length * 0.008, length * 0.99, 0)
    painter.drawPath(shaft)
    painter.restore()

    # ---- 罗盘星 + 光环（贴在羽毛左侧，那一带有面板盖不着）----
    # 位置教训：装饰层在控件**下面**，星若落在标题栏/排序下拉框/按钮后面就只剩
    # 一个孤零零的圆点（被不透明面板切掉一半）—— 必须挑「没有控件」的空档。
    cx, cy = w * 0.800, h * 0.580
    halo = h * 0.080
    painter.setPen(pen_of(40, 1.0))
    painter.drawEllipse(QPointF(cx, cy), halo, halo)
    # 十字准线：横线贯穿并伸出光环，上方一小段竖线 —— 读成「罗盘」而非闪点
    painter.setPen(pen_of(34, 1.0))
    painter.drawLine(QPointF(cx - halo * 1.5, cy), QPointF(cx + halo * 1.5, cy))
    painter.drawLine(QPointF(cx, cy - halo * 1.32), QPointF(cx, cy - halo * 0.52))

    # 星必须是**细长实心尖刺**（腰部 waist 只有 7%），不是「肥星描边」也不是
    # 「四角星填充」—— 后两者在 80px 尺度下会读成一坨菱形/蜘蛛网（都试过）。
    r_star = h * 0.052
    waist = 0.07

    def spike_path(r: float) -> QPainterPath:
        path = QPainterPath()
        path.moveTo(cx, cy - r)
        path.lineTo(cx + r * waist, cy - r * waist * 0.35)
        path.lineTo(cx + r, cy)
        path.lineTo(cx + r * waist, cy + r * waist * 0.35)
        path.lineTo(cx, cy + r)
        path.lineTo(cx - r * waist, cy + r * waist * 0.35)
        path.lineTo(cx - r, cy)
        path.lineTo(cx - r * waist, cy - r * waist * 0.35)
        path.closeSubpath()
        return path

    for tint, alpha in ((0.0, 130), (45.0, 70)):
        c = QColor(ink)
        c.setAlpha(alpha)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c)
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(tint)                 # 45° 那层是短的斜向刻度
        painter.translate(-cx, -cy)
        painter.drawPath(spike_path(r_star if not tint else r_star * 0.42))
        painter.restore()

    core = QColor(ink)
    core.setAlpha(190)
    painter.setBrush(core)
    painter.drawEllipse(QPointF(cx, cy), r_star * 0.10, r_star * 0.10)

    # ---- 几点微光：固定位置，不再撒满全窗 ----
    painter.setPen(pen_of(70, 1.0))
    for fx, fy, dashes, angle in ((0.905, 0.340, 6, 20), (0.965, 0.440, 5, -35),
                                 (0.945, 0.620, 7, 65), (0.975, 0.720, 5, 80),
                                 (0.885, 0.800, 4, -60)):
        painter.save()
        painter.translate(w * fx, h * fy)
        painter.rotate(angle)
        painter.drawLine(QPointF(-dashes / 2, 0), QPointF(dashes / 2, 0))
        painter.restore()


class BackgroundLayer(QWidget):
    """铺满窗口底层的背景画布。鼠标穿透，不影响任何交互。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BackgroundLayer")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._config = BackgroundConfig()
        self._pixmap: QPixmap | None = None
        self._decor = ""                       # 主题装饰名（目前只有 "columbina"）
        self._decor_color = "#7ec8e8"

    # ---------- 对外 ----------

    def set_decor(self, name: str, color: str = "#7ec8e8") -> None:
        """主题装饰。只在**没有自定义背景**时绘制，以免和用户选的背景打架。"""
        if (name, color) == (self._decor, self._decor_color):
            return
        self._decor = name
        self._decor_color = color
        self.update()

    def set_config(self, config: BackgroundConfig) -> None:
        self._config = config
        self._pixmap = None           # 尺寸/模糊变了要重算
        self.update()

    def config(self) -> BackgroundConfig:
        return self._config

    def is_active(self) -> bool:
        """纯色/渐变/图片任一为真就算开启——决定要不要把面板改成半透明。"""
        return self._config.type != "none"

    # ---------- 绘制 ----------

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._pixmap = None
        super().resizeEvent(event)

    def _resolved_pixmap(self) -> QPixmap | None:
        if self._config.type != "image":
            return None
        if self._pixmap is None:
            self._pixmap = prepare_pixmap(self._image_path(), self.width(),
                                          self.height(), self._config.blur)
        return self._pixmap

    def _image_path(self) -> str:
        """背景图实际路径：内置预设现解 resource_path，否则用用户图片路径。

        预设不能把 `_MEIPASS` 临时路径写进 data.json（下次启动失效），所以
        只存预设 id，画的时候才解成当前进程的绝对路径。
        """
        if self._config.preset:
            from ui.theme import preset_image_path
            path = preset_image_path(self._config.preset)
            if path:
                return path
        return self._config.image

    def paintEvent(self, event) -> None:  # noqa: N802
        cfg = self._config
        if self.width() <= 0 or self.height() <= 0:
            return
        if cfg.type == "none":
            # 没有自定义背景时，主题可以放自己的底层装饰（深色 / 浅色）
            if self._decor in ("columbina", "light"):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                _paint_theme_decor(painter, QRectF(self.rect()), self._decor_color,
                                   self._decor)
                painter.end()
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(max(0.0, min(1.0, cfg.opacity)))
        rect = QRectF(self.rect())

        if cfg.type == "color":
            painter.fillRect(rect, QColor(cfg.color))
        elif cfg.type == "gradient":
            gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
            gradient.setColorAt(0.0, QColor(cfg.color))
            gradient.setColorAt(1.0, QColor(cfg.color2))
            painter.fillRect(rect, QBrush(gradient))
        elif cfg.type == "image":
            pixmap = self._resolved_pixmap()
            if pixmap is not None and not pixmap.isNull():
                painter.drawPixmap(self.rect(), pixmap)
            else:
                # 图片丢了（被删/挪走）：退成主题底色，不要留一块纯黑
                return

        if cfg.dim > 0:
            painter.setOpacity(1.0)     # 暗化不受背景透明度影响，它是对成品的压制
            painter.fillRect(rect, QColor(0, 0, 0, int(255 * min(0.7, cfg.dim))))
        painter.end()


def blur_preview(path: str, width: int, height: int, blur: int) -> QImage | None:
    """给探针/测试用：直接拿派生后的 QImage（不建控件）。"""
    pixmap = prepare_pixmap(path, width, height, blur)
    return pixmap.toImage() if pixmap is not None else None
