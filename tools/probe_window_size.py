# -*- coding: utf-8 -*-
"""窗口尺寸探针（v2.8.0）：量出「窗口能开多小」的真实下限。

为什么需要这个工具：v2.8.0 之前窗口尺寸是拍脑袋写死的
`resize(1280, 800)` / `setMinimumSize(1100, 720)`，在 1920×1080@125%
的屏幕上（逻辑可用区只有 1536×816）一开就占宽 83%、高 98%，而最小高
720 = 可用高的 88% —— 用户根本拉不小。

改尺寸前必须先量清楚两条约束：
  1. `PlayerBar.minimumSizeHint().width()` —— 播放栏是横向最挤的一条，
     它的最小宽就是窗口最小宽的地板（低于它信息列会被挤到 0）；
  2. 侧栏 + 内容区的最小宽 —— 别只盯着播放栏。

**必须在真实平台跑**：offscreen 的字体库是空的，中文字宽全部失真，
minimumSizeHint 会给出完全不同的数字（见 MEMORY 环境铁律 #2）。

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_window_size.py
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_window_size.py --scales 1.0 1.15 1.30
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _isolate() -> None:
    """把数据目录钉进临时目录：探针绝不能读写用户真实曲库。"""
    tmp = tempfile.mkdtemp(prefix="qy_probe_size_")
    os.environ["APPDATA"] = tmp
    os.environ["QY_DATA_DIR"] = os.path.join(tmp, "data")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scales", nargs="*", type=float, default=[1.0, 1.30],
                    help="要试的字号缩放（默认 1.0 与上限 1.30）")
    args = ap.parse_args()

    _isolate()
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])

    screen = app.primaryScreen()
    avail = screen.availableGeometry()
    dpr = screen.devicePixelRatio()
    print(f"屏幕：可用区 {avail.width()}×{avail.height()} 逻辑像素 "
          f"（DPR {dpr}，物理 {screen.geometry().width()}×{screen.geometry().height()}）")

    from app.version import APP_VERSION
    from ui.main_window import (
        WINDOW_H_RATIO, WINDOW_MAX_HEIGHT, WINDOW_MAX_WIDTH,
        WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH, WINDOW_W_RATIO,
        MainWindow, initial_window_size,
    )

    plan = initial_window_size(avail.size())
    print(f"\n版本 {APP_VERSION}")
    print(f"常量：最小 {WINDOW_MIN_WIDTH}×{WINDOW_MIN_HEIGHT} / "
          f"上限 {WINDOW_MAX_WIDTH}×{WINDOW_MAX_HEIGHT} / "
          f"系数 {WINDOW_W_RATIO:.2f}×{WINDOW_H_RATIO:.2f}")
    print(f"计划初始尺寸 {plan.width()}×{plan.height()}  "
          f"= 可用区 {plan.width() / avail.width():.0%} 宽 / "
          f"{plan.height() / avail.height():.0%} 高")

    bad = 0
    for scale in args.scales:
        w = MainWindow()
        w._on_settings_font_scale(scale)
        w.show()
        app.processEvents()
        app.processEvents()

        pb = w.player_bar
        pb_w = pb.minimumSizeHint().width()
        win_min = w.minimumSizeHint()
        win_w, win_h = w.width(), w.height()
        margins = pb.layout().contentsMargins()
        print(f"\n字号 ×{scale:.2f}")
        print(f"  实际窗口     {win_w}×{win_h}"
              f"（可用区 {win_w / avail.width():.0%} × {win_h / avail.height():.0%}）")
        print(f"  窗口最小提示 {win_min.width()}×{win_min.height()}")
        print(f"  setMinimum   {w.minimumWidth()}×{w.minimumHeight()}")
        print(f"  播放栏最小宽 {pb_w}（左缩进 {margins.left()} / 右 {margins.right()}）")
        print(f"  侧栏宽       {w.sidebar.width()}")

        # 断言 1：播放栏最小宽不得超过窗口最小宽，否则信息列被挤到 0
        if pb_w > w.minimumWidth():
            print(f"  !! 播放栏最小宽 {pb_w} > 窗口最小宽 {w.minimumWidth()}")
            bad += 1
        # 断言 2：窗口最小尺寸不得小于最小提示，否则布局被反向挤压
        if (w.minimumWidth(), w.minimumHeight()) < (win_min.width(), win_min.height()):
            print(f"  !! setMinimum 小于 minimumSizeHint "
                  f"{win_min.width()}×{win_min.height()}")
            bad += 1
        # 断言 3：浮动条右缘不得压到播放栏左缩进
        fb = w.float_bar.geometry()
        if fb.x() + fb.width() > margins.left():
            print(f"  !! 浮动条右缘 {fb.x() + fb.width()} > 播放栏左缩进 {margins.left()}")
            bad += 1
        # 断言 4：初始尺寸不得小于最小尺寸
        if (plan.width(), plan.height()) < (w.minimumWidth(), w.minimumHeight()):
            print(f"  !! 初始尺寸 {plan.width()}×{plan.height()} 小于最小尺寸")
            bad += 1

        w.close()
        del w

    print(f"\n{'尺寸约束全部成立' if bad == 0 else f'{bad} 项不成立'}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
