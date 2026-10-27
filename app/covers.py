# -*- coding: utf-8 -*-
"""封面提供器：内嵌封面懒提取 + 磁盘缓存 + 无封面时生成渐变占位图。

- 磁盘缓存：%APPDATA%\\轻音播放器\\covers\\<track_id>.png（限制边长，控制体积）
- 内存缓存：{(track_id, size, radius): QPixmap}
- 注意：QPainter/QFont 需要 QApplication 实例（本类在应用运行时调用，天然满足）
"""
from __future__ import annotations

import os
from collections import OrderedDict

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap

from app.metadata import extract_picture

CACHE_PX = 240  # 磁盘缓存封面边长
# 内存缓存像素预算：40px 封面 1600px/张、280px 大图 78400px/张（约 49 倍）。
# 10M px ≈ 40MB(ARGB32)，能放下整个 5000 首列表 + 一批「正在播放」大图，且不会无上限增长。
CACHE_MAX_PIXELS = 10_000_000


class _LruPixmapCache:
    """按像素预算的 LRU 缓存：大图一张顶几十张小图，按像素而非条目数淘汰。"""

    def __init__(self, max_pixels: int = CACHE_MAX_PIXELS):
        self._max = max_pixels
        self._items: "OrderedDict[tuple, tuple[QPixmap, int]]" = OrderedDict()
        self._pixels = 0

    def get(self, key):
        hit = self._items.get(key)
        if hit is None:
            return None
        self._items.move_to_end(key)
        return hit[0]

    def put(self, key, pixmap: QPixmap) -> None:
        px = pixmap.width() * pixmap.height()
        if px <= 0:
            return
        self._items[key] = (pixmap, px)
        self._items.move_to_end(key)
        self._pixels += px
        # 淘汰最久未用，直到回到预算内；至少保留一张，避免刚请求的图被立刻扔掉
        while self._pixels > self._max and len(self._items) > 1:
            _, (_, evicted) = self._items.popitem(last=False)
            self._pixels -= evicted

    def __len__(self) -> int:
        return len(self._items)

    @property
    def pixels(self) -> int:
        """当前缓存的总像素（测试/探针用）。"""
        return self._pixels


def _hue_of(track_id: str) -> int:
    try:
        return int(track_id[:8], 16) % 360
    except ValueError:
        return 210


def _square_scaled(img: QImage, px: int) -> QImage:
    """居中裁剪为正方形并缩放到 px。"""
    side = min(img.width(), img.height())
    if side <= 0:
        return img
    cropped = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
    if cropped.width() != px:
        cropped = cropped.scaled(px, px, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
    return cropped


def _rounded(pixmap: QPixmap, radius: int) -> QPixmap:
    if radius <= 0:
        return pixmap
    out = QPixmap(pixmap.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    path = QPainterPath()
    path.addRoundedRect(out.rect(), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return out


class CoverProvider:
    def __init__(self, covers_dir: str, max_pixels: int = CACHE_MAX_PIXELS):
        self._dir = covers_dir
        self._mem = _LruPixmapCache(max_pixels)

    def _placeholder(self, track_id: str, px: int, radius: int) -> QPixmap:
        hue = _hue_of(track_id)
        img = QImage(px, px, QImage.Format.Format_ARGB32)
        grad = QLinearGradient(QPointF(0, 0), QPointF(px, px))
        grad.setColorAt(0.0, QColor.fromHsl(hue, 55, 45))
        grad.setColorAt(1.0, QColor.fromHsl((hue + 60) % 360, 60, 30))
        painter = QPainter(img)
        painter.fillRect(img.rect(), grad)
        painter.setPen(QColor(255, 255, 255, 235))
        font = QFont()
        font.setPixelSize(int(px * 0.52))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(img.rect(), int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignHCenter), "♫")
        painter.end()
        pixmap = QPixmap.fromImage(img)
        if radius:
            pixmap = _rounded(pixmap, radius)
        self._mem.put((track_id, px, radius), pixmap)
        return pixmap

    def _disk_path(self, track_id: str) -> str:
        return os.path.join(self._dir, f"{track_id}.png")

    def get_pixmap(self, track, size: int = 48, radius: int = 6) -> QPixmap:
        """获取曲目封面（size 为显示边长）；无内嵌封面返回渐变占位图。"""
        key = (track.id, size, radius)
        cached = self._mem.get(key)
        if cached is not None:
            return cached

        # 1) 磁盘缓存
        disk = self._disk_path(track.id)
        if os.path.isfile(disk):
            img = QImage(disk)
            if not img.isNull():
                pixmap = QPixmap.fromImage(_square_scaled(img, size))
                if radius:
                    pixmap = _rounded(pixmap, radius)
                self._mem.put(key, pixmap)
                return pixmap

        # 2) 从音频文件提取内嵌封面
        try:
            data = extract_picture(track.path)
        except Exception:  # noqa: BLE001
            data = None
        if data:
            img = QImage.fromData(data)
            if not img.isNull():
                try:
                    os.makedirs(self._dir, exist_ok=True)
                    _square_scaled(img, CACHE_PX).save(disk, "PNG")
                except Exception:  # noqa: BLE001
                    pass
                pixmap = QPixmap.fromImage(_square_scaled(img, size))
                if radius:
                    pixmap = _rounded(pixmap, radius)
                self._mem.put(key, pixmap)
                return pixmap

        # 3) 占位图
        return self._placeholder(track.id, size, radius)
