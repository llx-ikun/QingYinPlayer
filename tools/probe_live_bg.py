# -*- coding: utf-8 -*-
"""动态背景性能探针（v3.2.1 调研用，不参与打包）。

只回答一个问题：**全窗口程序化重绘每秒 30 次，单帧要多久？**

为什么先探针：背景层在播放时是最底层、每帧都要整块重绘的东西。如果一帧要 20ms，
那 33ms 的预算里只剩 13ms 给播放器其余部分，拖窗口/滚动歌词就会掉帧。
这类「看起来只是加个动画」的功能最容易在这里翻车，且翻车后难以靠肉眼判断原因。

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_live_bg.py
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_live_bg.py --size 1280x760 --frames 90
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient

# 与真实窗口默认尺寸接近（ui/main_window.py 的 initial_window_size 在同量级）
DEFAULT_W, DEFAULT_H = 1280, 760

# 预算是 30fps → 33.3ms/帧；背景层本不应吃掉超过 1/3，否则整机余量不足
BUDGET_MS = 33.3


def _make_particles(n: int, w: int, h: int) -> list[tuple[float, float, float, float]]:
    """固定种子生成粒子 (x, y, r, phase)，每帧按 phase 算亮度，位置不动。"""
    rnd = random.Random(20261103)
    return [(rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(0.8, 3.4),
             rnd.uniform(0, math.tau)) for _ in range(n)]


def paint_frame(painter: QPainter, w: int, h: int, t: float,
                particles, accent: QColor) -> None:
    """画一帧「典型」动态背景：底渐变 + 3 团呼吸光晕 + N 粒子 + 环形音频条 + 暗角。

    刻意包含四类不同开销：大块渐变填充（像素量大）、径向渐变（插值）、
    大量小图元（调用次数多）、全窗口半透明叠加（再一遍像素）。真实实现大概也是这些。
    """
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # 1) 底色：一次全窗口填充
    painter.fillRect(QRectF(0, 0, w, h), QColor(12, 14, 22))

    # 2) 三团呼吸光晕（径向渐变，开销随半径平方增长）
    for i, (fx, fy, base_r, speed) in enumerate(
            ((0.30, 0.35, 0.42, 0.9), (0.72, 0.62, 0.32, 1.3), (0.50, 0.86, 0.24, 0.7))):
        pulse = 0.85 + 0.15 * math.sin(t * speed + i * 2.1)
        r = min(w, h) * base_r * pulse
        c = QColor(accent)
        grad = QRadialGradient(QPointF(w * fx, h * fy), r)
        for pos, alpha in ((0.0, 46), (0.45, 18), (1.0, 0)):
            cc = QColor(c)
            cc.setAlpha(alpha)
            grad.setColorAt(pos, cc)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawEllipse(QPointF(w * fx, h * fy), r, r)

    # 3) 粒子：闪烁（每次 update 都要重设 brush）
    painter.setPen(Qt.PenStyle.NoPen)
    for x, y, r, phase in particles:
        c = QColor(accent)
        c.setAlpha(int(40 + 150 * (0.5 + 0.5 * math.sin(t * 2.2 + phase))))
        painter.setBrush(c)
        painter.drawEllipse(QPointF(x, y), r, r)

    # 4) 环形音频条：48 段圆弧，模拟频谱
    cx, cy = w * 0.5, h * 0.5
    base = min(w, h) * 0.22
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for i in range(48):
        ang = math.radians(i * 7.5)
        amp = base * (1.06 + 0.20 * abs(math.sin(t * 3.0 + i * 0.35)))
        c = QColor(accent)
        c.setAlpha(120)
        pen = painter.pen()
        pen.setColor(c)
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.drawLine(QPointF(cx + math.cos(ang) * base, cy + math.sin(ang) * base),
                         QPointF(cx + math.cos(ang) * amp, cy + math.sin(ang) * amp))

    # 5) 暗角：再一遍全窗口半透明（保证前景文字可读的那层）
    grad = QRadialGradient(QPointF(cx, cy), math.hypot(w, h) * 0.62)
    grad.setColorAt(0.0, QColor(0, 0, 0, 0))
    grad.setColorAt(1.0, QColor(0, 0, 0, 150))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(grad)
    painter.drawRect(QRectF(0, 0, w, h))


def bench(w: int, h: int, frames: int, scale: float = 1.0) -> tuple[float, float]:
    """直接画到 QImage 上计时（等价于 paintEvent 画到后缓冲）。

    scale < 1 时先画到缩小画布再平滑放大 —— 用分辨率换帧率的标准手段，一并量出来。
    返回 (平均 ms/帧, 最差 ms/帧)。
    """
    small_w, small_h = max(1, int(w * scale)), max(1, int(h * scale))
    canvas = QImage(small_w, small_h, QImage.Format.Format_ARGB32_Premultiplied)
    target = None if scale >= 1.0 else QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    particles = _make_particles(160, small_w, small_h)
    accent = QColor("#7ec8e8")

    samples: list[float] = []
    for i in range(frames):
        t = i * 0.033
        start = time.perf_counter()
        painter = QPainter(canvas)
        paint_frame(painter, small_w, small_h, t, particles, accent)
        painter.end()
        if target is not None:
            p2 = QPainter(target)
            p2.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p2.drawImage(QRectF(0, 0, w, h), canvas, QRectF(0, 0, small_w, small_h))
            p2.end()
        samples.append((time.perf_counter() - start) * 1000.0)
    return sum(samples) / len(samples), max(samples)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default=f"{DEFAULT_W}x{DEFAULT_H}")
    ap.add_argument("--frames", type=int, default=90)
    args = ap.parse_args(argv)

    w, h = (int(v) for v in args.size.lower().split("x"))
    print(f"画布 {w}x{h}，采样 {args.frames} 帧，预算 {BUDGET_MS:.1f}ms/帧（30fps）")
    print("-" * 62)

    ok = True
    for label, scale in (("全分辨率", 1.0), ("半分辨率 + 平滑放大", 0.5),
                         ("三分一分辨率 + 平滑放大", 1 / 3)):
        avg, worst = bench(w, h, args.frames, scale)
        pct = avg / BUDGET_MS * 100
        verdict = "可接受" if avg < BUDGET_MS * 0.35 else ("偏高" if avg < BUDGET_MS * 0.6 else "不可接受")
        if scale == 1.0 and avg >= BUDGET_MS * 0.6:
            ok = False
        print(f"{label:<22} 平均 {avg:6.2f}ms  最差 {worst:6.2f}ms  占预算 {pct:5.1f}%  → {verdict}")

    print("-" * 62)
    print("结论：" + ("全分辨率可用，无需降采样" if ok else
                     "全分辨率过重，应改用降采样画布（看上面两行的下降幅度）"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
