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

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from app.models import BackgroundConfig

# 图片背景的缓存上限：换歌/切页会反复刷新，只缓存最近一张，避免吃内存
_PIXMAP_CACHE: dict[tuple, QPixmap] = {}


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


class BackgroundLayer(QWidget):
    """铺满窗口底层的背景画布。鼠标穿透，不影响任何交互。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BackgroundLayer")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._config = BackgroundConfig()
        self._pixmap: QPixmap | None = None

    # ---------- 对外 ----------

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
        if cfg.type == "none" or self.width() <= 0 or self.height() <= 0:
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
