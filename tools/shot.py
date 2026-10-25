# -*- coding: utf-8 -*-
"""开发工具：真实平台开窗截图（offscreen 中文字体全是方块，不能用于审图）。

用法：
    python tools/shot.py --out ./shots                 # 全部状态 × 当前主题
    python tools/shot.py --out ./shots --theme light   # 浅色
    python tools/shot.py --out ./shots --state playing # 单个状态

状态：library / playing / lyrics / queue / settings / empty / maximized
数据：APPDATA 指向隔离临时目录，自动注入夹具曲目 + 示例歌单 + 收藏。
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

DESKTOP_BG = "#dcdcdc"


def _prepare_data(appdata: str, with_tracks: bool = True, theme: str = "dark") -> None:
    """在隔离 APPDATA 中构造演示数据。"""
    os.environ["APPDATA"] = appdata
    os.makedirs(appdata, exist_ok=True)

    from app.metadata import read_track
    from app.paths import data_file
    from app.store import LibraryStore

    store = LibraryStore(data_file())
    if with_tracks:
        from tests.make_fixtures import ensure_fixtures
        music_dir = ensure_fixtures()
        names = ["晴天 - 周杰伦.mp3", "夜曲.flac", "晨间轻音乐.wav", "海浪的声音.ogg", "无标签音频.mp3"]
        ids = []
        for name in names:
            path = os.path.join(music_dir, name)
            if os.path.isfile(path):
                track = store.add_or_update(read_track(path), path)
                ids.append(track.id)
        if len(ids) >= 2:
            pl = store.create_playlist("通勤路上")
            store.add_to_playlist(pl.id, ids[:3])
            pl2 = store.create_playlist("睡前白噪音")
            store.add_to_playlist(pl2.id, ids[3:])
            store.toggle_favorite(ids[0])
            store.toggle_favorite(ids[1])
        store.settings.nickname = "音乐爱好者"
    store.settings.theme = theme
    store.save()


def _capture_to_desktop_bg(widget, path: str) -> None:
    """把控件渲染到桌面灰底 PNG（半透明圆角窗直接 grab 会是透明底）。"""
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QColor, QImage

    for _ in range(20):
        QCoreApplication.processEvents()
    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(DESKTOP_BG))
    widget.render(img)
    img.save(path, "PNG")


def _spin_loaded(window, timeout_ms: int = 8000) -> None:
    import time
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtMultimedia import QMediaPlayer
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if window.player.media_status in (QMediaPlayer.MediaStatus.LoadedMedia,
                                          QMediaPlayer.MediaStatus.BufferedMedia):
            return
        time.sleep(0.05)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="./shots")
    parser.add_argument("--theme", default=None, choices=["dark", "light"])
    parser.add_argument("--state", default=None,
                        choices=["library", "playing", "lyrics", "queue", "settings", "empty", "maximized"])
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    theme = args.theme or "dark"
    states = [args.state] if args.state else \
        ["library", "playing", "lyrics", "queue", "settings", "maximized", "empty"]

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName("轻音播放器")

    from ui import theme as ui_theme
    from ui.main_window import MainWindow

    shots = []
    for state in states:
        with_tracks = state != "empty"
        appdata = tempfile.mkdtemp(prefix="qy_shot_")
        _prepare_data(appdata, with_tracks=with_tracks, theme=theme)
        window = MainWindow()
        window.resize(1280, 800)
        window.show()
        ui_theme.apply_theme(app, theme)

        name = f"{theme}-{state}.png"
        path = os.path.join(args.out, name)

        if state == "playing":
            ids = [t.id for t in window._displayed]
            if ids:
                window.player.play_tracks(ids, 1)
                _spin_loaded(window)
        elif state == "lyrics":
            ids = [t.id for t in window._displayed]
            if ids:
                window.player.play_tracks(ids, 0)
                _spin_loaded(window)
            window._show_page(1)
        elif state == "queue":
            ids = [t.id for t in window._displayed]
            if ids:
                window.player.play_tracks(ids, 0)
                _spin_loaded(window)
            from ui.queue_panel import QueuePanel
            panel = QueuePanel(window.player.queue_ids, window.player.queue_index,
                               window._queue_track_text, window)
            panel.show()
            _capture_to_desktop_bg(panel, path)
            panel.close()
            shots.append(path)
            window.close()
            continue
        elif state == "settings":
            from ui.settings_dialog import SettingsDialog, stats_for
            dialog = SettingsDialog(window.store.settings.theme, window.store.settings.nickname,
                                    stats_for(window.store), window)
            dialog.show()
            _capture_to_desktop_bg(dialog, path)
            dialog.close()
            shots.append(path)
            window.close()
            continue
        elif state == "maximized":
            window.showMaximized()

        _capture_to_desktop_bg(window, path)
        shots.append(path)
        window.close()

    print("截图完成：")
    for p in shots:
        print(" ", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
