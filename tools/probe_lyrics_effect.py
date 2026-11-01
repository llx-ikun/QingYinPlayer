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
    # v2.9.0 歌词颜色覆盖：启用后 4 格都叠加自定义双色渐变
    ap.add_argument("--color", action="store_true", help="启用歌词颜色覆盖")
    ap.add_argument("--trigger", default="progress", choices=["progress", "time"])
    ap.add_argument("--direction", default="horizontal",
                    choices=["horizontal", "vertical", "diagonal"])
    ap.add_argument("--color-a", default="#ff6b9d")
    ap.add_argument("--color-b", default="#7f7bff")
    ap.add_argument("--line-color", default="", help="给第二句单独指定颜色（如 #00e0a0）")
    ap.add_argument("--bilingual", action="store_true", help="使用带译文的双语歌词")
    args = ap.parse_args()

    app = QApplication(sys.argv[:1])
    from app.lyrics import LyricLine
    from app.models import LyricsColorConfig
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
    if args.bilingual:
        lines = [
            LyricLine(0, "故事的小黄花", "The little yellow flower of the story"),
            LyricLine(2000, "从出生那年就飘着", "It has been drifting since the year I was born"),
            LyricLine(4000, "童年的荡秋千", "The swing of my childhood"),
            LyricLine(6000, "随记忆一直晃到现在", "Sways in my memory to this day"),
        ]
    # 文案取自 ui/settings_dialog.LYRICS_EFFECT_OPTIONS，探针截图才和真实界面一致
    # （v3.0.9 起不再在工具里另写一份）。
    from ui.settings_dialog import LYRICS_EFFECT_OPTIONS
    effects = [(value, label) for label, value in LYRICS_EFFECT_OPTIONS]

    host = QWidget()
    host.setObjectName("ProbeCanvas")
    host.setStyleSheet(f"QWidget#ProbeCanvas {{ background: {t.BG}; }}")
    row = QHBoxLayout(host)
    row.setContentsMargins(PAD, PAD, PAD, PAD)
    row.setSpacing(PAD)

    panels = []
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
        if args.color:
            panel.set_color_config(LyricsColorConfig(
                enabled=True, trigger=args.trigger, color_a=args.color_a,
                color_b=args.color_b, direction=args.direction, speed=0.6))
            if args.line_color:
                panel.set_line_colors({2000: args.line_color})
        panel.set_synced(lines)
        panel.update_position(3000)  # 第二句 2000~4000ms 正中间 → 行内进度 0.5
        col.addWidget(panel)
        row.addWidget(cell)
        panels.append(panel)

    host.show()
    for _ in range(4):
        app.processEvents()
    # 时间模式在静态截图里也要能看到色带：直接给一个中间相位
    if args.color and args.trigger == "time":
        for panel in panels:
            panel._anim_phase = 0.45
            panel.list.viewport().update()
        for _ in range(3):
            app.processEvents()

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    host.grab().save(out, "PNG")
    print(f"截图: {out}")
    host.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
