# -*- coding: utf-8 -*-
"""歌词自动滚动探针：逐句推进播放位置，打印滚动条实际值与动画目标值。

用来定位「歌词播放时一直往上滚动」：如果目标值不随句号单调增大，而是回跳，
说明目标算成了**视口坐标**而不是**内容坐标**（`visualItemRect` 返回的是前者）。

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_lyrics_scroll.py
    # 加 --bilingual 看双语条目（每项两层，行高更大，偏差更明显）
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

PANEL_W, PANEL_H = 300, 340
LINE_MS = 3000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bilingual", action="store_true")
    ap.add_argument("--rows", type=int, default=16)
    args = ap.parse_args()

    app = QApplication(sys.argv[:1])
    from app.lyrics import LyricLine
    from ui import theme as ui_theme
    from ui.lyrics_panel import LyricsPanel

    ui_theme.apply_theme(app, "light")

    lines = []
    for i in range(args.rows):
        sub = f"第 {i} 句译文" if args.bilingual else ""
        lines.append(LyricLine(i * LINE_MS, f"Lyric line number {i}", sub))

    host = QWidget()
    host.setObjectName("ProbeCanvas")
    host.setStyleSheet(f"QWidget#ProbeCanvas {{ background: {ui_theme.current_theme().BG}; }}")
    panel = LyricsPanel(host)
    panel.setGeometry(0, 0, PANEL_W, PANEL_H)
    host.resize(PANEL_W, PANEL_H)
    host.show()
    panel.set_synced(lines)

    bar = panel.list.verticalScrollBar()
    print(f"行数={len(lines)} 视口高={panel.list.viewport().height()} "
          f"scrollMax={bar.maximum()} 行高={panel.list.visualItemRect(panel.list.item(0)).height()}")
    print(f"{'句':>3} {'bar.value':>9} {'rect.top':>8} {'目标':>6} {'应有':>6}  判定")

    prev_target = None
    bad = 0
    for i in range(len(lines)):
        # 真实播放节奏：每句之间隔 3 秒，260ms 的滚动动画早就结束了
        at = bar.value()
        rect = panel.list.visualItemRect(panel.list.item(i))
        expected = (at + rect.top() + rect.height() // 2
                    - panel.list.viewport().height() // 2)
        expected = max(bar.minimum(), min(bar.maximum(), expected))
        panel.update_position(i * LINE_MS + 200)
        end = int(panel._anim.endValue()) if panel._anim is not None else bar.value()
        mono = "OK" if prev_target is None or end >= prev_target else "回跳!"
        if mono != "OK":
            bad += 1
        print(f"{i:>3} {at:>9} {rect.top():>8} {end:>6} {expected:>6}  {mono}")
        if i and end == expected and end < bar.maximum():
            # 动画结束后该项是否垂直居中（容差 2px）
            QTest.qWait(300)   # 等 260ms 动画真正走完
            r = panel.list.visualItemRect(panel.list.item(i))
            offset = r.top() + r.height() // 2 - panel.list.viewport().height() // 2
            if abs(offset) > 2:
                print(f"    ↑ 居中偏差 {offset}px（应为 0）")
        prev_target = end
        QTest.qWait(320)   # 等滚动动画真正跑完

    print(f"\n回跳次数: {bad}（>0 说明目标算错，表现为歌词一直往上滚）")
    host.close()
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
