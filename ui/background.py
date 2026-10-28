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

import os
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
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


def _paint_theme_decor(painter: QPainter, rect: QRectF, color: str) -> None:
    """画「空月」主题的底层装饰：星点 + 符文圆环 + 羽饰 + 月牙。

    元素全部取自哥伦比娅（《原神》空月之歌）的视觉语言：
      符文圆环 —— 她背后那枚多层法阵，抽象成三层同心圆 + 八枚刻度 + 中心淡点；
      羽饰     —— 头饰与披风上的白羽，抽象成左上三片斜向羽片；
      月牙星点 —— 夜空与月光。

    为什么不用官方立绘：那是版权素材，不该随程序分发。这里只复刻形状与气质。

    alpha 定档经过一轮返工：初版圆环 13 / 羽饰 11 / 月牙 14，在真实底色上
    （BG #120e22 → BG_ALT #0a1220）**几乎完全看不见**，等于白画。现在外环 30 /
    刻度 34 / 中心 40 / 羽饰 22 / 月牙 28 —— 形状必须锐利（细线 + 清晰轮廓），
    亮度靠 alpha 而不是靠「涂一大块」，才既看得出又不会糊成污渍（记忆 #56）。
    """
    import math

    w, h = rect.width(), rect.height()
    if w <= 0 or h <= 0:
        return
    painter.setPen(Qt.PenStyle.NoPen)

    # ---- 星点：位置/大小/亮度都由固定种子决定，窗口缩放时不会乱跳 ----
    rnd = random.Random(_DECOR_SEED)
    star = QColor(color)
    for _ in range(56):
        x, y = rnd.uniform(0, 1) * w, rnd.uniform(0, 1) * h
        r = rnd.uniform(0.6, 1.9)
        star.setAlpha(rnd.randint(22, 72))
        painter.setBrush(star)
        painter.drawEllipse(QPointF(x, y), r, r)

    # ---- 符文圆环：右上半区，三层同心圆 + 八枚刻度 + 中心淡点 ----
    # 圆环放右上半区、月牙放右下半区（v2.3.1 把月牙下移到「行下空白带」是有意为之），
    # 两者在 y 方向故意错开 —— 两个淡圆一旦叠在一起，就会糊成一团说不清是什么的
    # 「污渍」。圆环半径因此要收着点（0.23min），否则下沿会伸进月牙那一带。
    cx, cy = w * 0.78, h * 0.26
    ring_r = min(w, h) * 0.23
    ring = QColor(color)
    ring.setAlpha(30)
    pen = QPen(ring)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for radius, width, alpha in ((ring_r, 1.8, 30), (ring_r * 0.76, 1.1, 22),
                                 (ring_r * 0.52, 1.1, 18)):
        ring.setAlpha(alpha)
        pen.setColor(ring)
        pen.setWidthF(max(0.7, width))
        painter.setPen(pen)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
    # 八枚刻度：沿最外一圈均布的短线段，读作「法阵的刻度」
    ring.setAlpha(34)
    pen.setColor(ring)
    pen.setWidthF(1.6)
    painter.setPen(pen)
    for i in range(8):
        a = math.pi * i / 4
        ca, sa = math.cos(a), math.sin(a)
        painter.drawLine(QPointF(cx + ring_r * 0.90 * ca, cy + ring_r * 0.90 * sa),
                         QPointF(cx + ring_r * 1.12 * ca, cy + ring_r * 1.12 * sa))
    # 中心一枚淡点（月之心）
    ring.setAlpha(40)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ring)
    painter.drawEllipse(QPointF(cx, cy), ring_r * 0.09, ring_r * 0.09)

    # ---- 羽饰：内容区右上三片斜向羽片，羽尖朝右下，与圆环组成「光环 + 羽翼」 ----
    # 位置两次返工：① 放左上（侧栏内）→ 被半透明面板（不透明度 0.78）盖得几乎
    # 看不见，alpha 26 透过去只剩 5；② 骑侧栏/内容区分界线 → 仍有一半在面板下。
    # 最终放内容区右上空白处（页头标题与「播放全部」之间），与圆环同侧呼应 ——
    # 只有**没有面板盖着**的区域，装饰才真的看得见。
    # 画法也用「描边叶片 + 羽轴中线」而不是实心填充：实心淡块在深底上会糊成一
    # 片说不清是什么的影（首版就这样），线条才有「羽」的辨识度。
    feather = QColor(color)
    feather.setAlpha(50)
    fpen = QPen(feather)
    fpen.setWidthF(1.5)
    fpen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(fpen)
    unit = min(w, h)
    for fx, fy, ln, ang in ((0.520, 0.130, 0.100, -38),
                            (0.565, 0.080, 0.070, -54),
                            (0.535, 0.215, 0.055, -22)):
        painter.save()
        painter.translate(w * fx, h * fy)
        painter.rotate(ang)
        s = unit * ln
        blade = QPainterPath()
        blade.moveTo(0, 0)
        blade.cubicTo(s * 0.30, -s * 0.34, s * 0.86, -s * 0.30, s, 0)
        blade.cubicTo(s * 0.86, s * 0.30, s * 0.30, s * 0.34, 0, 0)
        blade.closeSubpath()
        painter.drawPath(blade)
        painter.drawLine(QPointF(0, 0), QPointF(s * 0.90, 0))   # 羽轴
        painter.restore()

    # ---- 月牙：右下半区的「行下空白带」上，与圆环在 y 方向错开 ----
    # 位置三次试错：① 贴右下角被 84px 播放栏压成残弧；② 右上角裁掉弧的缺口；
    # ③ 移到行下空白带（v2.3.1，alpha 同时 18→14）。尺寸/alpha 沿用那一版，
    # 这里只把它和圆环的占位错开，不重复调氛围浓度。
    diameter = min(w, h) * 0.38
    cx2, cy2 = w * 0.87, h * 0.70
    left = cx2 - diameter * 0.5
    top = cy2 - diameter * 0.5
    outer = QRectF(left, top, diameter, diameter)
    path = QPainterPath()
    path.arcMoveTo(outer, 75)
    path.arcTo(outer, 75, 210)
    inner = QRectF(left + diameter * 0.30, top + diameter * 0.10,
                   diameter * 0.82, diameter * 0.94)
    path.arcTo(inner, 285, -210)
    path.closeSubpath()

    moon_color = QColor(color)
    moon_color.setAlpha(14)
    painter.setBrush(moon_color)
    painter.drawPath(path)


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
            self._pixmap = prepare_pixmap(self._config.image, self.width(),
                                          self.height(), self._config.blur)
        return self._pixmap

    def paintEvent(self, event) -> None:  # noqa: N802
        cfg = self._config
        if self.width() <= 0 or self.height() <= 0:
            return
        if cfg.type == "none":
            # 没有自定义背景时，主题可以放自己的底层装饰（空月）
            if self._decor == "columbina":
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                _paint_theme_decor(painter, QRectF(self.rect()), self._decor_color)
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
