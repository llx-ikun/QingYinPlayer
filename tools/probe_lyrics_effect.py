# -*- coding: utf-8 -*-
"""歌词播放动效视觉探针：真实平台渲染 4 种动效并排保存。

用于验收 v2.6.4 的「歌词动效」：无特效 / 放大 / 打字机 / 颜色覆盖。
把当前行停在第二句的正中间（行内进度 0.5），逐字效果最容易看出差异。

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_lyrics_effect.py \
        --out shots/lyrics_effect.png --theme light

注意：
- 必须真实平台（勿设 QT_QPA_PLATFORM=offscreen，否则字体库空、中文全方块）
- 只渲染 LyricsPanel，不构造 MainWindow，不写用户曲库
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget  # noqa: E402

PAD = 16
PANEL_W, PANEL_H = 300, 340


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="shots/lyrics_effect.png")
    ap.add_argument("--theme", default="columbina", choices=["columbina", "light"])
    args = ap.parse_args()

    app = QApplication(sys.argv[:1])
    from app.lyrics import LyricLine
    from ui import theme as ui_theme
    from ui.lyrics_panel import LyricsPanel

    ui_theme.apply_theme(app, args.theme)
    t = ui_theme.current_theme()

    lines = [
        LyricLine(0, "故事的小黄花"),
        LyricLine(2000, "从出生那年就飘着"),
        LyricLine(4000, "童年的荡秋千"),
        LyricLine(6000, "随记忆一直晃到现在"),
    ]
    effects = [
        ("none", "无特效"),
        ("zoom", "放大"),
        ("typewriter", "打字机"),
        ("karaoke", "颜色覆盖"),
    ]

    host = QWidget()
    host.setObjectName("ProbeCanvas")
    host.setStyleSheet(f"QWidget#ProbeCanvas {{ background: {t.BG}; }}")
    row = QHBoxLayout(host)
    row.setContentsMargins(PAD, PAD, PAD, PAD)
    row.setSpacing(PAD)

    for effect, label in effects:
        cell = QWidget()
        col = QVBoxLayout(cell)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        title = QLabel(label)
        title.setObjectName("PageTitle")
        title.setAlignment(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.AlignmentFlag.AlignCenter)
        col.addWidget(title)
        panel = LyricsPanel()
        panel.setFixedSize(PANEL_W, PANEL_H)
        panel.set_effect(effect)
        panel.set_synced(lines)
        panel.update_position(3000)  # 第二句 2000~4000ms 正中间 → 行内进度 0.5
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
