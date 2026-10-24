# -*- coding: utf-8 -*-
"""轻音播放器 —— 本地音乐播放器入口。

用法：
    python main.py          启动应用
    python main.py --check  环境自检（不加载 GUI）
"""
import os
import sys

APP_NAME = "轻音播放器"
APP_VERSION = "1.0.0"


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

    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)

    from PySide6.QtWidgets import QApplication

    from app.paths import app_data_dir  # noqa: F401  （确保数据目录存在）
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
