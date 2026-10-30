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
APP_VERSION = "2.7.3"


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
        #
        # v2.6 起还有两条会绕过 APPDATA 的路径：便携模式（软件目录的 data/）和
        # 指针文件（用户改过数据位置）。两者优先级都高于 APPDATA，所以这里必须再设
        # QY_DATA_DIR —— 它是最高优先级，能把自检牢牢钉在临时目录里。
        import atexit
        import shutil
        import tempfile
        import time

        _smoke_appdata = tempfile.mkdtemp(prefix="qy_smoke_")
        os.environ["APPDATA"] = _smoke_appdata
        os.environ["QY_DATA_DIR"] = os.path.join(_smoke_appdata, "data")
        atexit.register(shutil.rmtree, _smoke_appdata, True)

        from PySide6.QtCore import QCoreApplication, QTimer
        from PySide6.QtMultimedia import QMediaPlayer
        from PySide6.QtWidgets import QApplication

        from app.metadata import read_track
        from ui.main_window import MainWindow

        # 本地歌词对齐依赖 miniaudio（_miniaudio.pyd 在 C 层 import _cffi_backend）。
        # 打包最常见的事故就是漏收 _cffi_backend：界面一切正常，用户点「本地对齐」
        # 才报缺组件（v2.6.9 实测）。自检里显式探一次，让问题在构建阶段就暴露，
        # 而不是带着坏功能出厂。
        try:
            import miniaudio  # noqa: F401
        except Exception as exc:  # noqa: BLE001 - 任何加载失败都算打包残缺
            print(f"smoke fail: 本地对齐解码器不可用（{type(exc).__name__}: {exc}）")
            return 1
        print("smoke decoder: miniaudio OK")

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

    from app.paths import app_data_dir, current_root, mode
    from ui.main_window import MainWindow

    # 先确定数据目录并建好，再开窗口：路径解析要读指针/探测便携模式，
    # 出问题（比如指向了已拔掉的 U 盘）应该在窗口出现前就降级处理。
    app_data_dir()
    # 打包成 windowed 后双击启动时 sys.stdout 是 None，直接 print 会抛异常
    if sys.stdout is not None:
        print(f"数据目录: {current_root()} ({mode()})")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    _apply_app_icon(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
