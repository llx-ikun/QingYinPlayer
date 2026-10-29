# -*- coding: utf-8 -*-
"""浮动工具条视觉探针：真实平台渲染 FloatBar 并放大保存。

为什么需要它：浮动条只有 ~288x44，悬停/圆角/图标与文字的对齐这类 1-2px 细节
在整窗截图里根本看不出来。

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_float_bar.py --out shots/float.png
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_float_bar.py --theme columbina --scale 6

注意：
- 必须用真实平台（不要设 QT_QPA_PLATFORM=offscreen，否则字体库为空、中文全方块）
- 本脚本只渲染控件，不构造 MainWindow，因此不会写用户曲库
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

PAD = 12


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="shots/float_bar.png")
    ap.add_argument("--theme", default="columbina", choices=["columbina", "light"])
    ap.add_argument("--scale", type=int, default=4, help="放大倍数（最近邻，看边缘是否锐利）")
    ap.add_argument("--hover", default="", choices=["", "import", "dir", "settings", "theme"],
                    help="模拟某个按钮的悬停外观（直接灌底色，不触发真实 :hover）")
    args = ap.parse_args()

    app = QApplication(sys.argv[:1])
    from ui import theme as ui_theme
    from ui.float_bar import FloatBar

    ui_theme.apply_theme(app, args.theme)
    t = ui_theme.current_theme()

    # 用窗口底色做画布，才能看出托盘/圆钮是否真的浮起来了。
    # 注意必须带选择器：不带选择器的 setStyleSheet 会**级联到所有子控件**，
    # 把托盘/按钮自己的底色一起刷掉，渲染出来会变成「只有描边没有填充」。
    host = QWidget()
    host.setObjectName("ProbeCanvas")
    host.resize(300, 108)
    host.setStyleSheet(f"QWidget#ProbeCanvas {{ background: {t.BG}; }}")
    bar = FloatBar(host)
    bar.set_theme_icon(args.theme)   # 图标指向「点下去会切到哪个主题」
    bar.adjustSize()                           # 先定尺寸，再按真实高度居中（顺序反了会把齿轮切掉）
    bar.move(PAD, (host.height() - bar.height()) // 2)
    host.show()
    app.processEvents()

    # 悬停态**无法**在脚本里真触发：Qt 6.12 的 QSS :hover 取的是 State_MouseOver，
    # 手工 setAttribute(WA_UnderMouse) 不会进样式选项（最小用例已验证），
    # 沙箱里挪真实指针也不投递事件。所以这里退一步：直接把悬停底色灌给按钮，
    # 用来检查胶囊的圆角/左右留白/是否溢出卡片边界 —— 也就是只在意外观，不验交互。
    if args.hover:
        target = {"import": bar.import_btn, "dir": bar.dir_btn, "settings": bar.settings_btn,
                  "theme": bar.theme_toggle}[args.hover]
        is_circle = target in (bar.theme_toggle, bar.settings_btn)
        fill = t.SURFACE if is_circle else t.SURFACE_ACTIVE
        radius = 17 if is_circle else 12
        target.setStyleSheet(
            f"background: {fill}; border: none; border-radius: {radius}px;"
            f" color: {t.TEXT}; padding: 0px 4px;"
        )
        app.processEvents()

    app.processEvents()
    for _ in range(3):
        app.processEvents()

    shot = host.grab()
    big = shot.scaled(shot.width() * args.scale, shot.height() * args.scale,
                      Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.FastTransformation)
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    # 叠到棋盘格上，方便判断圆角是否真的透明（而不是被底色填成方的）
    canvas = QImage(big.size(), QImage.Format.Format_ARGB32)
    canvas.fill(QColor(t.BG))
    p = QPainter(canvas)
    p.drawPixmap(0, 0, big)
    p.end()
    canvas.save(out, "PNG")

    print(f"截图: {out}  ({shot.width()}x{shot.height()} -> {big.width()}x{big.height()})")
    print(f"FloatBar.sizeHint() = ({bar.sizeHint().width()}, {bar.sizeHint().height()})"
          f"  actual = ({bar.width()}, {bar.height()})")
    print(f"右缘 = 12(侧栏内容左) + {bar.sizeHint().width()} = {12 + bar.sizeHint().width()}"
          f"  (必须 <= 236，侧栏内容右边界)")
    host.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
