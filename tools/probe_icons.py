# -*- coding: utf-8 -*-
"""图标验收表：72px 原尺寸 + 16px 最近邻放大 8 倍，浅/深两种底色各一张。

为什么必须单独出表：16px 在整窗截图里只有几个像素，方向画反、齿轮糊成太阳
这类问题在里面「看起来没问题」。做法沿用 v2.1.1 的图标验收流程。

用法（必须真实平台，不要 offscreen）：
    env -u PYTHONPATH .venv/Scripts/python.exe build/probe_icons.py --out shots/icons.png
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.icons import _paint, device_ratio  # noqa: E402

# 顺序按「界面上相邻关系」排：齿轮紧挨主题钮，主题两态（羽毛/太阳）连成一排，
# 这样 16px 那一行能直接看出相邻图标会不会撞形。（moon 已不被主题使用，仍列出备查。）
KINDS = ["gear", "settings", "feather", "moon", "sun", "folder", "plus"]
DPR = 1.0
BIG, SMALL, ZOOM = 72, 16, 8
# 16px 只是逻辑尺寸；真实界面按 16×DPR 渲染（DPR 1.25 → 20 设备像素）。
# 只验 16px 会漏掉「小尺寸糊掉」这类问题，所以多出一行设备像素版。
PAD = 14
LABEL_H = 16


def render(bg: str, fg: str) -> QImage:
    cols = len(KINDS)
    # 格宽要跟最宽的那一行走：设备像素行是 round(16×DPR)×ZOOM，比 72px 还宽。
    # 早期按 BIG+PAD 算，放大行会溢出到隔壁列、互相压住（看着像图标被裁了）。
    zoom_w = max(SMALL, round(SMALL * DPR)) * ZOOM
    cell_w = max(BIG, zoom_w) + PAD
    width = PAD + cols * cell_w
    small_h = SMALL * ZOOM
    dev_h = round(SMALL * DPR) * ZOOM
    height = PAD + BIG + PAD + small_h + PAD + dev_h + LABEL_H + PAD
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(QColor(bg))

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)   # 放大部分要看清像素
    color = QColor(fg)
    font = QFont()
    font.setPixelSize(11)
    p.setFont(font)

    for i, kind in enumerate(KINDS):
        x = PAD + i * cell_w
        # 上：72px 原尺寸
        big = _paint(kind, BIG, color)
        p.drawPixmap(x, PAD, big)
        # 下：16px 原图 -> 最近邻放大 8 倍
        small = _paint(kind, SMALL, color)
        zoomed = small.scaled(SMALL * ZOOM, SMALL * ZOOM,
                              Qt.AspectRatioMode.IgnoreAspectRatio,
                              Qt.TransformationMode.FastTransformation)
        p.drawPixmap(x, PAD + BIG + PAD, zoomed)
        # 第三行：设备像素渲染（16 × DPR），放大同样倍数
        dev = _paint(kind, SMALL, color, DPR)
        dev_zoomed = dev.scaled(int(dev.width() * ZOOM), int(dev.height() * ZOOM),
                                Qt.AspectRatioMode.IgnoreAspectRatio,
                                Qt.TransformationMode.FastTransformation)
        p.drawPixmap(x, PAD + BIG + PAD + SMALL * ZOOM + PAD, dev_zoomed)
        # 标签
        p.setPen(color)
        p.drawText(x, height - PAD, kind)
    p.end()
    return img


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="shots/icons.png")
    args = ap.parse_args()

    app = QApplication(sys.argv[:1])  # noqa: F841  渲染图标需要 QApplication
    global DPR
    DPR = device_ratio()
    print(f"当前屏幕缩放比 {DPR}，第三行按 {round(SMALL * DPR)} 设备像素渲染")
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    light = render("#f2f3f5", "#202020")
    dark = render("#1b1d22", "#e8eaf0")
    combined = QImage(light.width(),
                      light.height() * 2 + 8,
                      QImage.Format.Format_ARGB32)
    combined.fill(QColor("#7f7f7f"))
    cp = QPainter(combined)
    cp.drawImage(0, 0, light)
    cp.drawImage(0, light.height() + 8, dark)
    cp.end()
    combined.save(out, "PNG")
    print(f"图标验收表: {out}  ({combined.width()}x{combined.height()})")
    print("顺序:", " / ".join(KINDS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
