# -*- coding: utf-8 -*-
"""窗口缩放探针（v2.8.3）：拖动边缘改尺寸时，背景层 / 浮动条 / 遮罩 / 耗时是否正常。

为什么需要它：内置背景预设（星空/云海）把一张 1920×853 的照片铺满整个窗口，而
`BackgroundLayer.paintEvent` 每次尺寸变化都要重新做一次「按比例扩大 + 居中裁切 +
平滑缩放」（`prepare_pixmap`，缓存只留最近一张）。拖动窗口边缘时这会按帧发生，
是「缩放卡顿 / 图片抖动」最可能的来源 —— 但只有量了才知道是不是它。

用法（真实桌面平台，--preset 选内置背景以触发图片重建路径）：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_resize.py --preset starry

输出：每个尺寸一行几何断言 + 每次 resize 的耗时（ms），末尾给 p50/p95。
判据：几何（背景层铺满 root-2、浮动条在窗口内）必须全 OK；
resize 单次耗时 p95 若 > 30ms，说明平滑缩放这条链路拖不动 60fps，需要做缓存分层。
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)


def _prepare(appdata: str, theme: str) -> None:
    os.environ["APPDATA"] = appdata
    os.environ["QY_DATA_DIR"] = appdata
    os.makedirs(appdata, exist_ok=True)
    import shot

    shot._prepare_data(appdata, with_tracks=True, theme=theme)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="columbina")
    parser.add_argument("--preset", default="",
                        help="内置背景预设（starry/clouds），触发图片重建路径")
    parser.add_argument("--rounds", type=int, default=24)
    args = parser.parse_args()

    appdata = tempfile.mkdtemp(prefix="qy_probe_resize_")
    _prepare(appdata, args.theme)

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    from ui.main_window import MainWindow

    window = MainWindow()
    if args.preset:
        from ui.theme import background_preset_config
        window.store.settings.set_bg_config("all", background_preset_config(args.preset))
    window.resize(1185, 800)
    window.show()
    window._apply_appearance(save=False)
    for _ in range(20):
        app.processEvents()

    bad = []

    def check(tag: str) -> None:
        root = window._root
        bg = window.background
        bar = window.float_bar
        # ① 背景层必须铺满 root（内缩 1px 给圆角描边）
        if (bg.x(), bg.y(), bg.width(), bg.height()) != (1, 1, root.width() - 2, root.height() - 2):
            bad.append(f"{tag}: 背景层 {bg.geometry()} != root {root.width()}x{root.height()}")
        # ② 浮动条必须完整落在窗口内
        if bar.x() < 0 or bar.y() < 0 or bar.x() + bar.width() > root.width() \
                or bar.y() + bar.height() > root.height():
            bad.append(f"{tag}: 浮动条越界 x={bar.x()} y={bar.y()} {bar.width()}x{bar.height()}"
                       f" root={root.width()}x{root.height()}")
        # ③ 有背景图时，pixmap 必须已经按当前尺寸重建（否则边缘会露一条白/黑）
        cfg = bg.config()
        if cfg.type == "image":
            pm = bg._resolved_pixmap()
            if pm is None or pm.width() != bg.width() or pm.height() != bg.height():
                got = "None" if pm is None else f"{pm.width()}x{pm.height()}"
                bad.append(f"{tag}: 背景图未按新尺寸重建 {got} vs {bg.width()}x{bg.height()}")

    check("初始")

    sizes = []
    for i in range(args.rounds):
        w = 1100 + i * 5
        h = 720 + i * 3
        sizes.append((w, h))

    timings = []
    for w, h in sizes:
        t0 = time.perf_counter()
        window.resize(w, h)
        app.processEvents()
        # 强制 paint 发生（否则耗时只算到布局，白白少算真正的大头）
        window.background.repaint()
        app.processEvents()
        timings.append((time.perf_counter() - t0) * 1000)
    check("缩放后")

    # 回到最小尺寸再测一次：最大→最小最容易暴露「没重建」
    window.resize(1100, 700)
    for _ in range(10):
        app.processEvents()
    window.background.repaint()
    app.processEvents()
    check("最小尺寸")
    window.resize(1600, 950)
    for _ in range(10):
        app.processEvents()
    window.background.repaint()
    app.processEvents()
    check("最大尺寸")

    p50 = statistics.median(timings)
    p95 = sorted(timings)[max(0, int(len(timings) * 0.95) - 1)]
    print(f"主题 {args.theme}  次数 {len(timings)}")
    print(f"resize 单次耗时: p50={p50:.1f}ms  p95={p95:.1f}ms  max={max(timings):.1f}ms")
    if bad:
        print("几何/重建问题:")
        for item in bad:
            print("  BAD", item)
    else:
        print("几何与背景重建: 全部 OK")

    window.player.stop()
    window.close()
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
