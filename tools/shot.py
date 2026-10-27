# -*- coding: utf-8 -*-
"""开发工具：真实平台开窗截图（offscreen 中文字体全是方块，不能用于审图）。

用法：
    python tools/shot.py --out ./shots                 # 全部状态 × 当前主题
    python tools/shot.py --out ./shots --theme light   # 浅色
    python tools/shot.py --out ./shots --state playing # 单个状态

状态：library / playing / lyrics / queue / settings / empty / maximized / video / video_fullscreen
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


def parse_bg_spec(spec: str):
    """解析 --bg 简写：`type=gradient;color=#1e3a8a;color2=#7c3aed;blur=10;dim=0.3`"""
    from app.models import BackgroundConfig

    cfg = BackgroundConfig()
    for chunk in (spec or "").split(";"):
        if not chunk.strip() or "=" not in chunk:
            continue
        key, _, value = chunk.partition("=")
        key, value = key.strip(), value.strip()
        if key == "type":
            cfg.type = value
        elif key in ("color", "color2", "image"):
            setattr(cfg, key, value)
        elif key == "blur":
            cfg.blur = int(float(value))
        elif key == "dim":
            cfg.dim = float(value)
        elif key == "opacity":
            cfg.opacity = float(value)
    return cfg


def _prepare_data(appdata: str, with_tracks: bool = True, theme: str = "dark",
                  with_video: bool = False, accent: str = "",
                  font_scale: float = 1.0, bg_spec: str = "") -> None:
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
    if with_video:
        from tests.make_fixtures import ensure_video_fixture
        video_path = ensure_video_fixture()
        if os.path.isfile(video_path):
            store.add_or_update(read_track(video_path), video_path)
    store.settings.theme = theme
    store.settings.accent_color = accent
    store.settings.font_scale = font_scale
    if bg_spec:
        store.settings.bg_all = parse_bg_spec(bg_spec)
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


def _spin_frames(window, timeout_ms: int = 8000) -> int:
    """等视频画面真的送到 sink（否则截出来是一块黑）。"""
    import time
    from PySide6.QtCore import QCoreApplication
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if window.now_playing.video_host.frames > 0:
            # 再多转几圈，确保画面控件完成一次 paint
            for _ in range(10):
                QCoreApplication.processEvents()
            return window.now_playing.video_host.frames
        time.sleep(0.05)
    return window.now_playing.video_host.frames


def _play_first_video(window) -> bool:
    """在当前列表里找第一个视频并播放，返回是否成功。"""
    from app.models import Track
    ids = [t.id for t in window._displayed if isinstance(t, Track) and t.is_video]
    if not ids:
        return False
    window.player.play_tracks(ids, 0)
    _spin_loaded(window)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="./shots")
    parser.add_argument("--theme", default=None, choices=["columbina", "dark", "light"])
    parser.add_argument("--accent", default="", help="自定义强调色，如 #ff7a45（默认跟随主题）")
    parser.add_argument("--font-scale", type=float, default=1.0, dest="font_scale")
    parser.add_argument("--tag", default="", help="文件名后缀，便于同主题多套外观对比")
    parser.add_argument("--settings-tab", type=int, default=0, dest="settings_tab",
                        help="设置对话框默认显示第几页（0 外观 / 1 背景 / 2 歌词与统计）")
    parser.add_argument("--bg", default="",
                        help="自定义背景：type=gradient;color=#1e3a8a;color2=#7c3aed;"
                             "blur=10;dim=0.3;opacity=1（type 可为 color/gradient/image）")
    parser.add_argument("--state", default=None,
                        choices=["library", "playing", "lyrics", "queue", "settings", "empty",
                                 "maximized", "video", "video_fullscreen"])
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    theme = args.theme or "columbina"
    states = [args.state] if args.state else \
        ["library", "playing", "lyrics", "queue", "settings", "maximized", "empty",
         "video", "video_fullscreen"]

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName("轻音播放器")

    from ui.main_window import MainWindow

    shots = []
    for state in states:
        with_tracks = state != "empty"
        with_video = state in ("video", "video_fullscreen")
        appdata = tempfile.mkdtemp(prefix="qy_shot_")
        _prepare_data(appdata, with_tracks=with_tracks, theme=theme, with_video=with_video,
                      accent=args.accent, font_scale=args.font_scale,
                      bg_spec=args.bg)
        window = MainWindow()
        window.resize(1280, 800)
        window.show()
        # 走应用自己的外观入口：它会把「有没有背景 => 面板要不要半透明」一起算上。
        # 直接调 set_appearance 会漏掉 scrim，导致截图里背景被面板完全盖住。
        window._apply_appearance(save=False)

        name = f"{theme}-{state}{('-' + args.tag) if args.tag else ''}.png"
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
        elif state == "video":
            if _play_first_video(window):
                window._show_page(1)
                print("   video frames:", _spin_frames(window))
        elif state == "video_fullscreen":
            if _play_first_video(window):
                window._show_page(1)
                _spin_frames(window)
                window._set_video_fullscreen(True)
                _spin_frames(window)
                overlay = window._fullscreen
                _capture_to_desktop_bg(overlay, path)
                shots.append(path)
                window._exit_video_fullscreen()
                window.close()
                continue
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
            settings = window.store.settings
            dialog = SettingsDialog(
                settings.theme, settings.nickname, stats_for(window.store), window,
                online_lyrics=settings.online_lyrics,
                accent_color=settings.accent_color,
                font_scale=settings.font_scale,
                bg_configs={"all": settings.bg_all, "library": settings.bg_library,
                            "now_playing": settings.bg_now})
            dialog.tabs.setCurrentIndex(args.settings_tab)
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
