# -*- coding: utf-8 -*-
"""一次性验证：指定 flac 能否被 QMediaPlayer 解码（offline，不写用户数据）。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PATH = r"C:\Users\西\Music\Chrissy Costanza _ HOYO-MiX - Blazing Heart (英文版).flac"


def main() -> int:
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    player = QMediaPlayer()
    errors = []
    player.errorOccurred.connect(lambda e, s: errors.append((int(e), s)))
    player.setSource(QUrl.fromLocalFile(PATH))
    deadline = time.time() + 20
    status = player.mediaStatus()
    while time.time() < deadline:
        app.processEvents()
        status = player.mediaStatus()
        if status in (QMediaPlayer.MediaStatus.LoadedMedia,
                      QMediaPlayer.MediaStatus.BufferedMedia,
                      QMediaPlayer.MediaStatus.InvalidMedia):
            break
        time.sleep(0.05)
    print("mediaStatus:", status, flush=True)
    print("duration(ms):", player.duration(), flush=True)
    print("errorString:", player.errorString() or "(none)", flush=True)
    print("errors:", errors or "(none)", flush=True)
    print("可解码:", status in (QMediaPlayer.MediaStatus.LoadedMedia,
                              QMediaPlayer.MediaStatus.BufferedMedia), flush=True)
    player.stop()
    player.setSource(QUrl())
    return 0


if __name__ == "__main__":
    sys.exit(main())
