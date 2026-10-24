# -*- coding: utf-8 -*-
"""E2E 全链路测试（offscreen + 隔离 AppData）。

覆盖：导入 -> 列表 -> 播放 -> seek/音量 -> 切歌 -> 歌单 -> 歌词联动 -> 重启恢复。
注意：沙箱无音频渲染，position 不自动推进（已探明），歌词联动用 update_position 直接驱动。
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.make_fixtures import ensure_fixtures

MUSIC_DIR = ensure_fixtures()


def setUpModule():
    # 隔离数据目录：必须在任何 app.paths 调用前设置
    global _tmp_appdata
    _tmp_appdata = tempfile.mkdtemp(prefix="qy_e2e_appdata_")
    os.environ["APPDATA"] = _tmp_appdata

    from PySide6.QtWidgets import QApplication
    global _app
    _app = QApplication.instance() or QApplication(sys.argv[:1])

    # 用假对话框替换模态导入进度框（避免 exec 阻塞）
    import ui.main_window as mw
    from PySide6.QtCore import QObject, Signal

    class FakeImportDialog(QObject):
        cancelled = Signal()

        def __init__(self, parent=None):
            super().__init__()

        def update_progress(self, *a, **k):
            pass

        def set_current_file(self, *a, **k):
            pass

        def finish(self, *a, **k):
            pass

        def reject(self):
            pass

        def exec(self):
            return 0

    mw.ImportProgressDialog = FakeImportDialog


def _spin(predicate, timeout_ms=15000, interval_ms=20):
    from PySide6.QtCore import QCoreApplication
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(interval_ms / 1000)
    return predicate()


class TestE2E(unittest.TestCase):
    def setUp(self):
        from ui.main_window import MainWindow
        self.window = MainWindow()
        self.window.show()
        self.store = self.window.store

    def tearDown(self):
        self.window.player.stop()
        self.window.close()

    # ---------- 导入与列表 ----------

    def test_import_populates_list(self):
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        self.assertEqual(len(self.store.all_tracks()), 5)
        self.assertEqual(self.window.track_list.list.count(), 5)
        self.assertEqual(self.window.track_list.count_label.text(), "共 5 首")
        # 列表首行标题来自 ID3
        first_row = self.window.track_list.list.itemWidget(self.window.track_list.list.item(0))
        self.assertIsNotNone(first_row)

    def test_search_filters(self):
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        self.window._on_search_changed("周杰伦")
        titles = [t.title for t in self.window._displayed]
        self.assertEqual(sorted(titles), ["夜曲", "晴天"])

    # ---------- 播放控制 ----------

    def test_play_seek_volume_mode(self):
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        ids = [t.id for t in self.window._displayed]
        # 双击列表第一行播放
        self.window._on_track_activated(ids[0], 0)
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        self.assertIsNotNone(self.window.player.current_track)
        # seek -> 播放栏时间标签更新
        self.window.player.seek(1000)
        self.assertEqual(self.window.player_bar.time_cur.text(), "0:01")
        # 音量
        self.window.player.set_volume(0.5)
        self.assertEqual(self.window.player_bar.volume_slider.value(), 50)
        # 模式循环
        self.window.player.cycle_mode()
        self.assertEqual(self.window.player.mode, "sequential")
        self.assertIn("顺序播放", self.window.player_bar.mode_btn.toolTip())

    def test_next_previous_via_bar(self):
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(ids[0], 0)
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        self.window.player_bar.next_clicked.emit()
        self.assertEqual(self.window.player.current_track.id, ids[1])
        self.window.player_bar.prev_clicked.emit()
        self.assertEqual(self.window.player.current_track.id, ids[0])

    # ---------- 歌单管理 ----------

    def test_playlist_flow(self):
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        playlist = self.store.create_playlist("E2E 歌单")
        tracks = self.store.all_tracks()
        self.store.add_to_playlist(playlist.id, [t.id for t in tracks[:3]])
        self.window.set_view(playlist.id)
        self.assertEqual(self.window.track_list.list.count(), 3)
        self.assertEqual(self.window.track_list.title_label.text(), "E2E 歌单")
        # 侧边栏显示歌单与数量
        self.assertIn("E2E 歌单", [self.window.sidebar.playlist_list.itemWidget(
            self.window.sidebar.playlist_list.item(i)).layout().itemAt(0).widget().text()
            for i in range(self.window.sidebar.playlist_list.count())])
        # 重命名 + 删除
        self.store.rename_playlist(playlist.id, "改名后")
        self.window.set_view(playlist.id)
        self.assertEqual(self.window.track_list.title_label.text(), "改名后")
        self.store.delete_playlist(playlist.id)
        self.window.set_view(self.store.settings.last_view)
        self.assertEqual(self.window._view_id, playlist.id)
        self.window.set_view("__library__")

    # ---------- 歌词 ----------

    def test_lyrics_sync(self):
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        # 找到带同名 LRC 的「晴天」
        target = next(t for t in self.store.all_tracks() if t.title == "晴天")
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(target.id, ids.index(target.id))
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        panel = self.window.now_playing.lyrics
        self.assertEqual(panel._mode, "synced")
        self.assertEqual(panel.list.count(), 8)  # LRC 共 8 个时间戳行
        # 模拟播放到 4000ms -> 第 2 行高亮
        self.window.now_playing.update_position(4000)
        self.assertEqual(panel._current_index, 1)
        # 点击歌词 -> seek 信号
        panel.seek_requested.emit(3000)
        self.assertGreaterEqual(self.window.player.position_ms, 0)

    def test_embedded_lyrics_fallback(self):
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        target = next(t for t in self.store.all_tracks() if t.title == "夜曲")
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(target.id, ids.index(target.id))
        panel = self.window.now_playing.lyrics
        self.assertEqual(panel._mode, "synced")  # FLAC 内嵌带时间戳歌词
        self.assertEqual(panel.list.count(), 2)

    # ---------- 持久化 ----------

    def test_restart_restores_state(self):
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(ids[1], 1)
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        self.window.player.set_volume(0.33)
        self.window.player.set_mode("shuffle")
        self.window.close()
        self.assertTrue(os.path.isfile(os.path.join(_tmp_appdata, "轻音播放器", "data.json")))

        from ui.main_window import MainWindow
        window2 = MainWindow()
        try:
            self.assertEqual(len(window2.store.all_tracks()), 5)
            self.assertAlmostEqual(window2.store.settings.volume, 0.33, places=3)
            self.assertEqual(window2.store.settings.play_mode, "shuffle")
            self.assertEqual(window2.store.settings.last_track_id, ids[1])
            self.assertEqual(window2.track_list.list.count(), 5)
        finally:
            window2.player.stop()
            window2.close()


if __name__ == "__main__":
    unittest.main()
