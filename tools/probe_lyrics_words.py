# -*- coding: utf-8 -*-
"""逐字时间轴视觉探针（v3.0.0）：同一句、同一进度，对比「线性插值」与「逐字时间窗」。

第一行：无逐字数据（v2.9.2 口径，字与字匀速）
第二行：带逐字时间轴（前 6 个字挤在 0~1500ms，后面三个字拖到 4000ms）

两行的扫光分界在同一进度下必然不同 —— 这正是「拖腔 / 一字一顿」时旧算法错位的地方。

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_lyrics_words.py \
        --out shots/lyrics_words.png

注意：必须真实平台（勿设 QT_QPA_PLATFORM=offscreen，否则字体库空、中文全方块）。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QGridLayout, QLabel, QVBoxLayout, QWidget,
)

PAD = 14
PANEL_W, PANEL_H = 380, 130

TEXT = "随记忆一直晃到现在"
# 前 6 个字 0~1500ms（每字 250ms），「到」500ms，「现」1000ms，「在」500ms
WORDS = (
    (0, 250, "随"), (250, 500, "记"), (500, 750, "忆"),
    (750, 1000, "一"), (1000, 1250, "直"), (1250, 1500, "晃"),
    (1500, 2500, "到"), (2500, 3500, "现"), (3500, 4000, "在"),
)
POSITIONS = (1000, 2000, 3000)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="shots/lyrics_words.png")
    ap.add_argument("--theme", default="columbina", choices=["columbina", "light"])
    ap.add_argument("--effect", default="karaoke", choices=["karaoke", "typewriter"])
    ap.add_argument("--font-size", type=int, default=26, help="歌词字号（px），截图要看得清就调大")
    ap.add_argument("--positions", default="",
                    help="只渲染这几档进度，逗号分隔（如 2000）。图小才能 1:1 看清分界")
    args = ap.parse_args()

    app = QApplication(sys.argv[:1])

    from app.lyrics import LyricLine, WordSpan
    from ui import theme as ui_theme
    from ui.lyrics_panel import LyricsPanel, _typed_from_words

    ui_theme.apply_theme(app, args.theme)
    theme = ui_theme.current_theme()

    positions = (tuple(int(x) for x in args.positions.split(",") if x.strip())
                 or POSITIONS)
    spans = tuple(WordSpan(*w) for w in WORDS)
    assert "".join(w.text for w in spans) == TEXT, "词元拼接必须等于整句"

    print(f"整句 {len(TEXT)} 字，句窗 0~4000ms，动效={args.effect}")
    for pos in positions:
        exact = _typed_from_words(spans, TEXT, pos, 4000)
        linear = round(len(TEXT) * pos / 4000)
        print(f"  {pos:>4}ms  线性={linear:<2} 逐字={exact:<2} "
              f"线性「{TEXT[:linear]}」 / 逐字「{TEXT[:exact]}」")

    host = QWidget()
    host.setObjectName("ProbeCanvas")
    host.setStyleSheet(f"QWidget#ProbeCanvas {{ background: {theme.BG}; }}")
    grid = QGridLayout(host)
    grid.setContentsMargins(PAD, PAD, PAD, PAD)
    grid.setSpacing(PAD)

    rows = (("线性插值（无逐字数据）", ()), ("逐字时间窗（v3.0.0）", spans))
    for r, (title, words) in enumerate(rows):
        head = QLabel(title)
        head.setObjectName("PageTitle")
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(head, r * 2, 0, 1, len(positions))
        for c, pos in enumerate(positions):
            cell = QWidget()
            col = QVBoxLayout(cell)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(4)
            cap = QLabel(f"{pos}ms · 进度 {pos / 4000:.0%}")
            cap.setObjectName("SubText")
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(cap)
            panel = LyricsPanel()
            panel.setFixedSize(PANEL_W, PANEL_H)
            panel.set_effect(args.effect)
            font = panel.list.font()
            font.setPixelSize(args.font_size)
            panel.list.setFont(font)
            panel.set_synced([LyricLine(0, TEXT, words=words),
                              LyricLine(4000, "下一句占位")])
            panel.update_position(pos)
            col.addWidget(panel)
            grid.addWidget(cell, r * 2 + 1, c)

    host.show()
    for _ in range(5):
        app.processEvents()

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    host.grab().save(out, "PNG")
    print(f"截图: {out}")
    host.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
