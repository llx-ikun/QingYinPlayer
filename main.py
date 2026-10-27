# -*- coding: utf-8 -*-
"""轻音播放器 —— 本地音乐播放器入口。

用法：
    python main.py          启动应用
    python main.py --check  环境自检（不加载 GUI）
"""
import os
import sys

from PySide6.QtGui import QIcon

APP_NAME = "轻音播放器"
APP_VERSION = "2.3.0"


def _resolve_app_icon() -> str | None:
    """定位应用图标：打包后随 --add-data 进入 sys._MEIPASS，开发态用本地 assets。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "assets", "app.ico")
    return path if os.path.exists(path) else None


def _apply_app_icon(app) -> None:
    icon = _resolve_app_icon()
    if icon:
        app.setWindowIcon(QIcon(icon))


def main() -> int:
    if "--check" in sys.argv:
        print(f"{APP_NAME} v{APP_VERSION} (Python {sys.version.split()[0]})")
        try:
            import PySide6  # noqa: F401
            import mutagen  # noqa: F401
            print("依赖检查: PySide6 OK / mutagen OK")
        except ImportError as e:
            print(f"依赖检查失败: {e}")
            return 1
        return 0

    if "--smoke" in sys.argv:
        # 打包产物自检：创建主窗口；若附带音频文件则验证可解码播放
        #
        # 关键：smoke 会走 MainWindow → LibraryStore(add_or_update)，而 store 默认
        # 落在 %APPDATA%\轻音播放器\data.json —— 也就是**用户真实曲库**。若不隔离，
        # 每次 build.py 自检都会把合成夹具「晴天」写进用户库，退出时还会覆盖
        # last_view / last_track_id。这里在创建窗口之前把 APPDATA 指向临时目录。
        import atexit
        import shutil
        import tempfile
        import time

        _smoke_appdata = tempfile.mkdtemp(prefix="qy_smoke_")
        os.environ["APPDATA"] = _smoke_appdata
        atexit.register(shutil.rmtree, _smoke_appdata, True)

        from PySide6.QtCore import QCoreApplication, QTimer
        from PySide6.QtMultimedia import QMediaPlayer
        from PySide6.QtWidgets import QApplication

        from app.metadata import read_track
        from ui.main_window import MainWindow

        app = QApplication(sys.argv[:1])
        app.setApplicationName(APP_NAME)
        _apply_app_icon(app)
        window = MainWindow()
        window.show()

        audio_file = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
        if audio_file:
            meta = read_track(audio_file)
            if meta is None:
                print(f"smoke fail: 无法读取音频 {audio_file}")
                return 1
            track = window.store.add_or_update(meta, audio_file)
            window.player.play_single(track.id, autoplay=True)
            deadline = time.time() + 10
            status = None
            while time.time() < deadline:
                QCoreApplication.processEvents()
                status = window.player.media_status
                if status in (QMediaPlayer.MediaStatus.LoadedMedia,
                              QMediaPlayer.MediaStatus.BufferedMedia,
                              QMediaPlayer.MediaStatus.EndOfMedia,
                              QMediaPlayer.MediaStatus.InvalidMedia):
                    break
                time.sleep(0.05)
            loaded = status in (QMediaPlayer.MediaStatus.LoadedMedia,
                                QMediaPlayer.MediaStatus.BufferedMedia,
                                QMediaPlayer.MediaStatus.EndOfMedia)
            duration = window.player.duration_ms
            print(f"smoke media: status={status.name if status else None} duration={duration}ms")
            if not loaded or duration <= 0:
                print("smoke fail: 音频解码异常")
                return 1
            QTimer.singleShot(300, app.quit)
            app.exec()
            print("smoke ok (含音频解码)")
            return 0

        QTimer.singleShot(600, app.quit)
        code = app.exec()
        print("smoke ok")
        return code

    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)

    from PySide6.QtWidgets import QApplication

    from app.paths import app_data_dir  # noqa: F401  （确保数据目录存在）
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    _apply_app_icon(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
