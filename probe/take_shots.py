# -*- coding: utf-8 -*-
"""离屏渲染抓图：验证深色主题/布局/封面/歌词的实际视觉效果（开发辅助脚本）。"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="qy_shot_")
# 真实 Windows 平台渲染（离屏模式字体库为空，中文会变方块，仅用于布局检查）
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tests.make_fixtures import ensure_fixtures  # noqa: E402

MUSIC_DIR = ensure_fixtures()
OUT = os.path.join(HERE, "shots")
os.makedirs(OUT, exist_ok=True)


def spin(predicate, timeout_ms=15000):
    import time
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


app = QApplication(sys.argv)

from ui.main_window import MainWindow  # noqa: E402

window = MainWindow()
window.resize(1280, 800)
window.show()

# 直接驱动扫描器（避免模态导入框阻塞）
from app.scanner import ScannerWorker  # noqa: E402

worker = ScannerWorker([MUSIC_DIR])
worker.track_ready.connect(lambda meta: window.store.add_or_update(meta, meta.path))


def _on_import_done(_total):
    window.store.save()
    window.sidebar.refresh_playlists(window.store.user_playlists())
    window.refresh_list()


worker.finished_ok.connect(_on_import_done)
worker.start()
spin(lambda: not worker.isRunning())
spin(lambda: window.track_list.list.count() == 5, 5000)

# 播放第一首（带 LRC 的晴天）
target = next(t for t in window.store.all_tracks() if t.title == "晴天")
ids = [t.id for t in window._displayed]
window._on_track_activated(target.id, ids.index(target.id))
spin(lambda: window.player.current_track is not None)
window.player.seek(4000)
window.now_playing.update_position(4000)

# 图 1：列表视图
window._show_page(0)
window.track_list.set_current_track(target.id)
app.processEvents()
window.grab().save(os.path.join(OUT, "1_list_view.png"), "PNG")

# 图 2：正在播放 + 歌词
window._show_page(1)
app.processEvents()
window.grab().save(os.path.join(OUT, "2_now_playing.png"), "PNG")

# 图 3：歌单视图（建一个歌单放两首）
pl = window.store.create_playlist("跑步歌单")
window.store.add_to_playlist(pl.id, [t.id for t in window.store.all_tracks()[:2]])
window.set_view(pl.id)
window._show_page(0)
app.processEvents()
window.grab().save(os.path.join(OUT, "3_playlist_view.png"), "PNG")

print("shots saved to", OUT)
