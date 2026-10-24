# -*- coding: utf-8 -*-
"""封面提供器：内嵌封面懒提取 + 磁盘缓存 + 无封面时生成渐变占位图。

- 磁盘缓存：%APPDATA%\\轻音播放器\\covers\\<track_id>.png（限制边长，控制体积）
- 内存缓存：{(track_id, size, radius): QPixmap}
- 注意：QPainter/QFont 需要 QApplication 实例（本类在应用运行时调用，天然满足）
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap

from app.metadata import extract_picture

CACHE_PX = 240  # 磁盘缓存封面边长


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
    def __init__(self, covers_dir: str):
        self._dir = covers_dir
        self._mem: dict[tuple, QPixmap] = {}

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
        self._mem[(track_id, px, radius)] = pixmap
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
                self._mem[key] = pixmap
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
                self._mem[key] = pixmap
                return pixmap

        # 3) 占位图
        return self._placeholder(track.id, size, radius)
