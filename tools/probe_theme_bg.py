# -*- coding: utf-8 -*-
"""内置背景预设的可读性探针（v2.8.3）。

内置背景预设是**一张照片铺满整个窗口**，而列表/列头是透明的 —— 字直接压在图上。
所以「图好不好看」和「字看不看得清」是两件事，必须看实际渲染，不能只看配色表。

用法（真实桌面平台，offscreen 下字体库为空会截出一片方块）：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_theme_bg.py \
        --preset starry --opacity 0.7 --dim 0.3 --out shots_tmp

输出：`<out>/<preset>-<opacity>-<dim>/library.png`、`playing.png`，以及
`crop_cols.png`（右侧时长/大小列放大 2 倍，专门看灰字压在亮部上）。

读图判据：列头「大小 / 时长」与行内数值压在亮部（如星空的月亮）上时，仍要能
一眼读出数字；读不出就加暗化或降不透明度，别去改主题配色。
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)


def _render(theme: str, preset: str, opacity: float, dim: float, out_dir: str) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    import shot                       # tools/shot.py：复用它的数据准备与桌面底合成
    from ui import theme as ui_theme

    appdata = tempfile.mkdtemp(prefix="qy_probe_bg_")
    shot._prepare_data(appdata, with_tracks=True, theme=theme)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    from ui.main_window import MainWindow

    window = MainWindow()
    # 把内置背景预设当背景应用上去（可覆盖暗化/不透明度）
    cfg = ui_theme.background_preset_config(preset)
    cfg.opacity = opacity
    cfg.dim = dim
    window.store.settings.set_bg_config("all", cfg)
    window.resize(1280, 800)
    window.show()
    window._apply_appearance(save=False)

    jobs = [("library", 0), ("playing", 1)]
    made = []
    for name, page in jobs:
        window._show_page(page)
        for _ in range(30):
            app.processEvents()
        path = os.path.join(out_dir, f"{name}.png")
        shot._capture_to_desktop_bg(window, path)
        made.append(path)

    img = QImage(made[0])
    if not img.isNull():
        w, h = img.width(), img.height()
        crop = img.copy(int(w * 0.62), int(h * 0.08), int(w * 0.38), int(h * 0.42))
        crop = crop.scaled(int(crop.width() * 2), int(crop.height() * 2),
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        crop.save(os.path.join(out_dir, "crop_cols.png"), "PNG")

    window.player.stop()
    window.close()
    for path in made:
        print(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", default="starry",
                        choices=["starry", "clouds"])
    parser.add_argument("--theme", default="columbina",
                        choices=["columbina", "light"])
    parser.add_argument("--opacity", type=float, default=None)
    parser.add_argument("--dim", type=float, default=None)
    parser.add_argument("--out", default=os.path.join(ROOT, "shots_tmp"))
    args = parser.parse_args()

    from ui.theme import background_preset_config
    base = background_preset_config(args.preset)
    opacity = base.opacity if args.opacity is None else args.opacity
    dim = base.dim if args.dim is None else args.dim
    out_dir = os.path.join(args.out, f"{args.preset}-o{opacity:g}-d{dim:g}")
    os.makedirs(out_dir, exist_ok=True)
    print(f"渲染 {args.preset}（主题 {args.theme}）: opacity={opacity} dim={dim} -> {out_dir}")
    _render(args.theme, args.preset, opacity, dim, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
