# -*- coding: utf-8 -*-
"""双语歌词排版视觉探针：验证「一句 = 原文 + 译文」两行同块的观感。

用于验收 v2.6.10 的双语歌词：原文大字、译文小字，两行作为一个整体高亮/滚动，
逐字动效按两行字符总数推进（原文唱完自然轮到译文）。

四格对比：
1. 单语对照（旧行为）
2. 双语 none（当前句整块高亮）
3. 双语 karaoke（进度 0.75：原文已唱完、译文唱到一半）
4. 双语 typewriter（进度 0.5：原文打到一半）

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_bilingual_lyrics.py \
        --out shots/bilingual_lyrics.png --theme light

注意：必须真实平台（勿设 QT_QPA_PLATFORM=offscreen，否则字体库空、中文全方块）。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget  # noqa: E402

PAD = 16
PANEL_W, PANEL_H = 300, 340

# 当前句高亮在第二句（2000~4000ms）
CURRENT_MS = 3000


def _cells(app, ui_theme):
    from app.lyrics import LyricLine
    from ui.lyrics_panel import LyricsPanel

    monolingual = [
        LyricLine(0, "Who can surely know"),
        LyricLine(2000, "How the wind blows,"),
        LyricLine(4000, "When showers of notes"),
        LyricLine(6000, "Fall like sparkles"),
    ]
    bilingual = [
        LyricLine(0, "Who can surely know", "风将吹向何方"),
        LyricLine(2000, "How the wind blows,", "谁也捉摸不透"),
        LyricLine(4000, "When showers of notes", "当音符的骤雨"),
        LyricLine(6000, "Fall like sparkles", "如星辉般洒落"),
    ]
    specs = [
        ("单语对照", "none", monolingual, CURRENT_MS),
        ("双语 · 无特效", "none", bilingual, CURRENT_MS),
        # 行内进度 0.5：原文唱了一半，karaoke 能看清深浅分界
        ("双语 · 颜色覆盖", "karaoke", bilingual, CURRENT_MS),
        # 行内进度 0.85：原文打完、译文刚出两个字（验证逐字跨两行）
        ("双语 · 打字机", "typewriter", bilingual, CURRENT_MS + 700),
    ]
    out = []
    for label, effect, lines, position in specs:
        panel = LyricsPanel()
        panel.setFixedSize(PANEL_W, PANEL_H)
        panel.set_effect(effect)
        panel.set_synced(lines)
        panel.update_position(position)
        out.append((label, panel))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="shots/bilingual_lyrics.png")
    ap.add_argument("--theme", default="light", choices=["columbina", "light"])
    args = ap.parse_args()

    app = QApplication(sys.argv[:1])
    from ui import theme as ui_theme

    ui_theme.apply_theme(app, args.theme)
    t = ui_theme.current_theme()

    host = QWidget()
    host.setObjectName("ProbeCanvas")
    host.setStyleSheet(f"QWidget#ProbeCanvas {{ background: {t.BG}; }}")
    row = QHBoxLayout(host)
    row.setContentsMargins(PAD, PAD, PAD, PAD)
    row.setSpacing(PAD)

    for label, panel in _cells(app, ui_theme):
        cell = QWidget()
        col = QVBoxLayout(cell)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        title = QLabel(label)
        title.setObjectName("PageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(title)
        col.addWidget(panel)
        row.addWidget(cell)

    host.show()
    for _ in range(4):
        app.processEvents()

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    host.grab().save(out, "PNG")
    print(f"截图: {out}")
    host.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
