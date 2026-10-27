# -*- coding: utf-8 -*-
"""播放栏视觉探针：真实平台渲染 PlayerBar 并放大保存，用于逐个像素比对改前/改后。

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_player_bar.py --out shots/bar_after.png
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_player_bar.py --out shots/bar.png --scale 3

注意：
- 必须用真实平台（不要设 QT_QPA_PLATFORM=offscreen，否则字体库为空、中文全方块）
- 本脚本只渲染控件，不构造 MainWindow，因此不会写用户曲库
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

BAR_W, BAR_H = 960, 84


def _fake_cover(size: int = 96, radius: int = 12) -> QPixmap:
    """模拟封面提供器产出的圆角封面（真实应用里圆角由 app.covers._rounded 烘焙）。"""
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    p.fillRect(0, 0, size, size // 2, QColor("#7b6cff"))
    p.fillRect(0, size // 2, size, size // 2, QColor("#5b8cff"))
    p.end()
    return QPixmap.fromImage(img)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="shots/player_bar.png")
    ap.add_argument("--theme", default="light", choices=["light", "dark"])
    ap.add_argument("--scale", type=int, default=2, help="放大倍数（便于看清 1-2px 细节）")
    args = ap.parse_args()

    app = QApplication(sys.argv[:1])
    from ui import theme as ui_theme
    from ui.player_bar import PlayerBar

    ui_theme.apply_theme(app, args.theme)

    bar = PlayerBar()
    bar.resize(BAR_W, BAR_H)
    bar.update_track("Blazing Heart (英文版)", "Chrissy Costanza/HOYO-MiX", _fake_cover())
    bar.set_format("flac")
    bar.set_favorite_active(True)
    bar.update_state("playing")
    bar.update_position(49_000, 177_976)
    bar.show()
    app.processEvents()
    for _ in range(3):
        app.processEvents()

    shot = bar.grab()
    big = shot.scaled(shot.width() * args.scale, shot.height() * args.scale,
                      Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    big.save(out, "PNG")

    print(f"截图: {out}  ({shot.width()}x{shot.height()} -> {big.width()}x{big.height()})")
    print(f"PlayerBar.minimumSizeHint().width() = {bar.minimumSizeHint().width()}  (必须 <= 1100)")
    bar.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
