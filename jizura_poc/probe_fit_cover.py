# -*- coding: utf-8 -*-
"""探针（v3.4.3）：验证视觉面板的 contain / cover 两种铺满方式。

在真实平台上跑（不带 QT_QPA_PLATFORM=offscreen）——WebEngine 在 offscreen 下
grab() 常常是空白，看不出黑边。窗口刻意取 1400x800（1.75，非 16:9），
这样 contain 一定会露上下黑边、cover 一定没有，两种模式才有区分度。

输出：jizura_poc/fit_contain.png / fit_cover.png，并打印左上角像素颜色。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer                       # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from app.lyrics import LyricLine                        # noqa: E402
from ui import jizura_panel as jp                       # noqa: E402

LINES = [
    LyricLine(0, "唯有追赶风的方向"),
    LyricLine(3000, "Only By Chasing the Wind"),
    LyricLine(6000, "加入这场竞演，准备开场"),
    LyricLine(9000, "像不协和音一样"),
]

OUT = HERE


def main() -> int:
    app = QApplication(sys.argv[:1])
    win = QWidget()
    win.resize(1400, 800)
    lay = QVBoxLayout(win)
    lay.setContentsMargins(0, 0, 0, 0)
    panel = jp.JizuraLyricsPanel()
    lay.addWidget(panel)
    win.show()

    def wait_ready() -> None:
        if not panel._ready:
            QTimer.singleShot(200, wait_ready)
            return
        panel.set_meta("测试曲目", "测试歌手", "测试专辑")
        panel.set_synced(LINES)
        panel.set_fit("contain")
        QTimer.singleShot(800, shot_contain)

    def shot_contain() -> None:
        panel._view.grab().save(os.path.join(OUT, "fit_contain.png"))
        panel.set_fit("cover")
        QTimer.singleShot(800, shot_cover)

    def shot_cover() -> None:
        img = panel._view.grab()
        img.save(os.path.join(OUT, "fit_cover.png"))
        qimg = img.toImage()
        w, h = qimg.width(), qimg.height()
        for name, (x, y) in (("左上", (2, 2)), ("上中", (w // 2, 2)),
                             ("中左", (2, h // 2)), ("正中", (w // 2, h // 2))):
            c = qimg.pixelColor(x, y)
            print(f"cover {name}: rgb({c.red()},{c.green()},{c.blue()})")
        print("窗口尺寸:", w, "x", h)
        panel.set_fit("contain")
        QTimer.singleShot(800, shot_restore)

    def shot_restore() -> None:
        """回到 contain：画布必须搬回原祖先链，并重新露出 16:9 留边。"""
        img = panel._view.grab()
        img.save(os.path.join(OUT, "fit_restore.png"))
        qimg = img.toImage()
        c = qimg.pixelColor(2, 2)
        print(f"restore 左上: rgb({c.red()},{c.green()},{c.blue()})")
        app.quit()

    QTimer.singleShot(300, wait_ready)
    QTimer.singleShot(30000, app.quit)      # 兜底：别把探针挂死
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
