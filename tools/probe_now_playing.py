# -*- coding: utf-8 -*-
"""正在播放页分栏探针（v2.8.1）：封面多大、歌词还剩多宽。

为什么需要这个工具：用户报「左边显示太大，右边歌词显示不全」，但仓库里的
夹具曲目歌词都很短 —— 用 `tools/shot.py` 截图根本量不出问题（短句怎么都不会超宽）。
必须用「长标题 + 长双语歌词」才能复现：

- 长标题会把左列顶开（`QLabel.minimumSizeHint()` = 全文宽度，旧版没有 wordWrap）
- 长双语行会在窄面板里超出被硬裁（旧版 `_draw_line` 不折行也不省略）

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_now_playing.py \\
        --out shots/np_v281 --size 1044x639 1280x800 1400x900

必须真实平台（勿设 QT_QPA_PLATFORM=offscreen，否则字体库空、中文全方块）。
数据目录隔离到临时目录，不碰用户曲库。
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

TITLE = "唯有追赶风的方向 (Only By Chasing the Wind)"
ARTIST = "知更鸟/HOYO-MiX/Chevy"
META = "崩坏星穹铁道-唯有追赶风的方向 Only By Chasing the Wind · 2:03 · FLAC"

# 用户截图里的那几句，故意保留长句与长译文
LYRICS = [
    ("Hey! Worried 'bout it? Don't you doubt it", "嘿！还在纠结？把疑虑抛开"),
    ("Let's go, hit that pedal to the metal", "出发，油门踩到底，切入音色"),
    ("Emm~ Mend your pace and step it up!", "唔~ 调整步调，节奏加快！"),
    ("The ace, power it on, let's amp it up", "出绝招，全速启动，音浪推高！"),
    ("Lights on our star, supercharge it!", "点亮星芒，引擎攀高！"),
    ("Electrify, our ending line is right in sight", "电光激荡，终点线近在眼前"),
    ("Birds of a feather, together, now", "振翅齐飞的鸟儿们，在此刻集结"),
]


def _isolate() -> None:
    tmp = tempfile.mkdtemp(prefix="qy_probe_np_")
    os.environ["APPDATA"] = tmp
    os.environ["QY_DATA_DIR"] = os.path.join(tmp, "data")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="shots/np_probe", help="输出文件名前缀（不含扩展名）")
    ap.add_argument("--size", nargs="*", default=["1044x639"],
                    help="要截的窗口尺寸，可给多个，如 1044x639 1280x800")
    ap.add_argument("--theme", default="columbina")
    args = ap.parse_args()

    _isolate()
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])

    from app.lyrics import LyricLine
    from ui import theme as ui_theme
    from ui.main_window import MainWindow

    ui_theme.apply_theme(app, args.theme)
    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    for spec in args.size:
        w, h = (int(v) for v in spec.lower().split("x", 1))
        window = MainWindow()
        window.resize(w, h)
        window.show()
        window._apply_appearance(save=False)
        for _ in range(4):
            app.processEvents()

        view = window.now_playing.audio_view
        view.title.setText(TITLE)
        view.artist.setText(ARTIST)
        view.meta.setText(META)
        # 塞一张真实照片当封面占位：夹具封面只有 64×64，放大到 200+ 会糊成一片，
        # 看不出「封面到底占多大」。借主题背景图（真照片、够大）当占位。
        cover_path = os.path.join(_ROOT, "assets", "theme_dark.jpg")
        if os.path.isfile(cover_path):
            from PySide6.QtGui import QPixmap
            view.cover.setPixmap(QPixmap(cover_path))
        lines = [LyricLine(i * 12000, main, sub) for i, (main, sub) in enumerate(LYRICS)]
        view.lyrics.set_synced(lines)
        view.lyrics.set_source("来源：本地对齐")
        window._show_page(1)
        for _ in range(12):
            app.processEvents()

        path = f"{args.out}-{spec}.png"
        window.grab().save(path)

        # 关键几何：封面多大、歌词多宽、有没有哪句超出可用宽（会被省略号截掉）
        vp = view.lyrics.list.viewport().width()
        metrics = view.lyrics.fontMetrics()
        widest = max(metrics.horizontalAdvance(main) for main, _ in LYRICS)
        widest_sub = max(metrics.horizontalAdvance(sub) for _, sub in LYRICS)
        print(f"{spec}: 封面 {view.cover.width()} / 左列 {view.left_box.width()} / "
              f"歌词 {view.lyrics.width()}（视口 {vp}）/ "
              f"最长原文 {widest}px 最长译文 {widest_sub}px "
              f"{'→ 会省略' if max(widest, widest_sub) > vp - 12 else '→ 完整'}")
        print(f"  截图 {path}")
        window.player.stop()
        window.close()
        del window

    return 0


if __name__ == "__main__":
    sys.exit(main())
