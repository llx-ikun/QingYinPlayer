# -*- coding: utf-8 -*-
"""探针（v3.4.3）：视觉面板搬进全屏浮层后**还能不能正常出画**。

这是本次改动最大的风险点：QtWebEngine 的 QWebEngineView 被 setParent 到另一个
顶层窗口后，某些环境会重建渲染进程 —— 表现是**全屏后一片白/一片黑，且零报错**。
单元测试用的是普通 QWidget，测不到这一层，必须在真实平台跑一次并抓图。

输出：jizura_poc/fullscreen_overlay.png / back_to_window.png
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
from ui.lyrics_fullscreen import LyricsFullscreenWindow  # noqa: E402

LINES = [
    LyricLine(0, "唯有追赶风的方向"),
    LyricLine(3000, "Only By Chasing the Wind"),
    LyricLine(6000, "加入这场竞演，准备开场"),
    LyricLine(9000, "像不协和音一样"),
]

OUT = HERE


def _stats(img) -> str:
    """粗判「有没有出画」：统计非纯背景色的采样点比例。"""
    q = img.toImage()
    w, h = q.width(), q.height()
    hit = 0
    total = 0
    for y in range(0, h, max(1, h // 20)):
        for x in range(0, w, max(1, w // 20)):
            c = q.pixelColor(x, y)
            total += 1
            if c.red() + c.green() + c.blue() > 60:      # 比底色亮就算有内容
                hit += 1
    return f"{hit}/{total} 采样点有内容"


def main() -> int:
    app = QApplication(sys.argv[:1])
    host = QWidget()
    host.resize(1200, 700)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    panel = jp.JizuraLyricsPanel()
    lay.addWidget(panel)
    host.show()

    fs = LyricsFullscreenWindow()

    def wait_ready() -> None:
        if not panel._ready:
            QTimer.singleShot(200, wait_ready)
            return
        panel.set_meta("测试曲目", "测试歌手", "测试专辑")
        panel.set_synced(LINES)
        panel.set_playing(False)
        QTimer.singleShot(700, enter)

    def enter() -> None:
        panel.set_fit("cover")
        fs.enter(panel, lambda p: (p.set_fit("contain"), p.setParent(None),
                                   lay.addWidget(p)))
        QTimer.singleShot(1200, shot_fs)      # 给 Chromium 一点时间重新合成

    def shot_fs() -> None:
        print("fs:", fs.size(), "panel:", panel.size(), "view:", panel._view.size())
        img = fs.grab()
        img.save(os.path.join(OUT, "fullscreen_overlay.png"))
        print("全屏浮层:", img.width(), "x", img.height(), "|", _stats(img))
        fs.leave()
        QTimer.singleShot(1000, shot_back)

    def shot_back() -> None:
        img = host.grab()
        img.save(os.path.join(OUT, "back_to_window.png"))
        print("搬回窗口:", img.width(), "x", img.height(), "|", _stats(img))
        app.quit()

    QTimer.singleShot(300, wait_ready)
    QTimer.singleShot(45000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
