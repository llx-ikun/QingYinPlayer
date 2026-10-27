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
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
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
    """画「星月」主题的底层装饰：右下角一枚极淡的月牙 + 固定星点。

    为什么不用官方立绘：那是版权素材，不该随程序分发。这里只用角色的
    **视觉语言**（月牙、星点、冰蓝冷光）重现同样的气质，且透明度压到 3%~10%，
    只在最底层当氛围，不抢内容的注意力。
    """
    w, h = rect.width(), rect.height()
    if w <= 0 or h <= 0:
        return
    painter.setPen(Qt.PenStyle.NoPen)

    # 星点：位置/大小/亮度都由固定种子决定，窗口缩放时不会乱跳
    rnd = random.Random(_DECOR_SEED)
    star = QColor(color)
    for _ in range(56):
        x, y = rnd.uniform(0, 1) * w, rnd.uniform(0, 1) * h
        r = rnd.uniform(0.6, 1.9)
        star.setAlpha(rnd.randint(22, 72))
        painter.setBrush(star)
        painter.drawEllipse(QPointF(x, y), r, r)

    # 月牙位置的三次试错值得记下来：
    #   ① 贴右下角 → 被 84px 播放栏压成一道残弧，横穿音量条，像渲染脏点；
    #   ② 右上角裁出画面 → 弧的缺口被切掉，只剩一大块淡圆盘，像污渍；
    #   ③ 现在这版：**完整月牙**、细一点、放在右半区竖向 56% 处。
    #      形状完整才读得出是月亮，alpha 压到 18 又不会抢列表里的字。
    diameter = min(w, h) * 0.38
    cx, cy = w * 0.87, h * 0.70
    left = cx - diameter * 0.5
    top = cy - diameter * 0.5
    outer = QRectF(left, top, diameter, diameter)
    path = QPainterPath()
    path.arcMoveTo(outer, 75)
    path.arcTo(outer, 75, 210)
    # 内弧半径更大 → 月牙更细，不再是胖圆环
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
        self._decor = ""                       # 主题装饰名（目前只有 "moon"）
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
            # 没有自定义背景时，主题可以放自己的底层装饰（星月）
            if self._decor == "moon":
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
