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
from unittest import mock

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

    def test_import_list_row_fields(self):
        """导入后列表行字段逐项断言：标题/艺人·专辑/时长。"""
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        rows = {}
        for i in range(self.window.track_list.list.count()):
            row = self.window.track_list.list.itemWidget(self.window.track_list.list.item(i))
            rows[row.title.text()] = row
        self.assertEqual(rows["晴天"].sub.text(), "周杰伦 · 叶惠美")
        self.assertEqual(rows["晴天"].duration.text(), "0:02")
        self.assertEqual(rows["夜曲"].sub.text(), "周杰伦 · 十一月的萧邦")
        # 无标签文件：标题回退文件名，艺人/专辑回退默认值
        self.assertEqual(rows["无标签音频"].sub.text(), "未知艺人 · 未知专辑")

    def test_drag_import(self):
        """拖拽文件夹到窗口 -> 走 dropEvent -> 导入入库。"""
        from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
        from PySide6.QtGui import QDropEvent
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(MUSIC_DIR)])
        event = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        self.window.dropEvent(event)
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        self.assertEqual(len(self.store.all_tracks()), 5)
        self.assertEqual(self.window.track_list.list.count(), 5)

    def test_cancel_import_stops_partially(self):
        """取消导入：扫描器停止、窗口句柄清理、不会扫完整个目录。"""
        import numpy as np
        import soundfile as sf
        tmp = tempfile.mkdtemp(prefix="qy_e2e_cancel_")
        for i in range(30):
            path = os.path.join(tmp, f"歌{i:02d}.wav")
            sf.write(path, np.zeros(2205, dtype=np.int16), 44100, format="WAV")
        self.window._start_import([tmp])
        self.window._scanner.cancel()  # 立即取消，不可能扫完 30 个文件
        self.assertTrue(_spin(lambda: self.window._scanner is None, timeout_ms=10000))
        self.assertLess(len(self.store.all_tracks()), 30)

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

    def test_rename_current_playlist_refreshes_header(self):
        """回归：重命名当前正在浏览的歌单时，列表头部标题必须同步更新。"""
        import ui.main_window as mw
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        playlist = self.store.create_playlist("旧名字")
        self.store.add_to_playlist(playlist.id, [t.id for t in self.store.all_tracks()[:2]])
        self.window.set_view(playlist.id)
        self.assertEqual(self.window.track_list.title_label.text(), "旧名字")
        # 走 UI 链路：patch 模态输入框，直接触发 _playlist_action
        with mock.patch.object(mw.QInputDialog, "getText",
                               return_value=("新名字", True)):
            self.window._playlist_action(playlist.id, "rename")
        self.assertEqual(self.store.get_playlist(playlist.id).name, "新名字")
        self.assertEqual(self.window.track_list.title_label.text(), "新名字")
        # 侧边栏同样同步新名称
        names = [self.window.sidebar.playlist_list.itemWidget(
            self.window.sidebar.playlist_list.item(i)).layout().itemAt(0).widget().text()
            for i in range(self.window.sidebar.playlist_list.count())]
        self.assertIn("新名字", names)
        # 还原视图，避免影响后续用例（与 test_playlist_flow 同一约定）
        self.window.set_view("__library__")

    def test_rename_playlist_cancelled(self):
        """取消重命名对话框时不应改名，界面保持原状。"""
        import ui.main_window as mw
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        playlist = self.store.create_playlist("保持原名")
        self.window.set_view(playlist.id)
        with mock.patch.object(mw.QInputDialog, "getText",
                               return_value=("", False)):
            self.window._playlist_action(playlist.id, "rename")
        self.assertEqual(self.store.get_playlist(playlist.id).name, "保持原名")
        self.assertEqual(self.window.track_list.title_label.text(), "保持原名")
        self.window.set_view("__library__")

    def test_playlist_drag_reorder(self):
        """歌单内拖拽重排：store 顺序与 UI 列表顺序同步更新。"""
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        playlist = self.store.create_playlist("排序歌单")
        tracks = self.store.all_tracks()
        self.store.add_to_playlist(playlist.id, [t.id for t in tracks])
        self.window.set_view(playlist.id)
        original = list(self.store.get_playlist(playlist.id).track_ids)
        # 模拟 QListWidget 行移动：第 0 行拖到索引 2 处（start=0, end=0, destination=2）
        self.window.track_list._on_rows_moved(None, 0, 0, 2)
        moved = self.store.get_playlist(playlist.id).track_ids
        self.assertEqual(moved, [original[1], original[0]] + original[2:])
        # UI 同步：列表首行变为原第二首
        first_row = self.window.track_list.list.itemWidget(self.window.track_list.list.item(0))
        self.assertEqual(first_row.title.text(), tracks[1].display_title)
        self.window.set_view("__library__")

    def test_add_to_playlist_via_menu(self):
        """右键「添加到歌单」菜单：选中歌单后入库，重复添加不重复。

        注意：QMenu 必须替换模块级名字（mw.QMenu）而不是 patch 类的 exec——
        Qt 对象的实例级方法调用不经过类字典（Shiboken 特性），patch 类属性无效。
        """
        import ui.main_window as mw
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        playlist = self.store.create_playlist("待添加")
        target = self.store.all_tracks()[0]

        class FakeAction:
            def __init__(self, text):
                self._text = text

            def text(self):
                return self._text

            def setEnabled(self, _enabled):
                pass

        class FakeMenu:
            def __init__(self, parent=None):
                self._actions = []

            def addAction(self, text):
                act = FakeAction(text)
                self._actions.append(act)
                return act

            def addSeparator(self):
                pass

            def actions(self):
                return list(self._actions)

            def exec(self, *_args):
                for act in self._actions:
                    if act.text() == "待添加":
                        return act
                return None

        with mock.patch.object(mw, "QMenu", FakeMenu):
            self.window._on_context_action(target.id, "add_to_playlist")
        self.assertEqual(self.store.get_playlist(playlist.id).track_ids, [target.id])
        # 再次添加同一首：不入队，状态栏提示已存在
        with mock.patch.object(mw, "QMenu", FakeMenu):
            self.window._on_context_action(target.id, "add_to_playlist")
        self.assertEqual(self.store.get_playlist(playlist.id).track_ids, [target.id])
        self.assertIn("已存在", self.window.statusBar().currentMessage())
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
        # 点击歌词 -> seek 信号 -> 播放器真正跳到对应位置
        panel.seek_requested.emit(1500)
        self.assertEqual(self.window.player.position_ms, 1500)

    def test_bind_lyrics_manually(self):
        """手动绑定 .lrc：优先级最高，播放时歌词面板显示绑定内容。"""
        import ui.main_window as mw
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        # 选一首本身没有任何歌词的曲子，排除同名/内嵌歌词干扰
        target = next(t for t in self.store.all_tracks() if t.title == "无标签音频")
        lrc = os.path.join(tempfile.mkdtemp(prefix="qy_e2e_lrc_"), "手动歌词.lrc")
        with open(lrc, "w", encoding="utf-8") as f:
            f.write("[00:01.00]手动绑定第一行\n[00:02.00]手动绑定第二行\n")
        with mock.patch.object(mw.QFileDialog, "getOpenFileName",
                               return_value=(lrc, "")):
            self.window._on_context_action(target.id, "bind_lyrics")
        self.assertEqual(self.store.get_track(target.id).lrc_path, lrc)
        # 播放该曲 -> 歌词来自手动绑定的文件
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(target.id, ids.index(target.id))
        panel = self.window.now_playing.lyrics
        self.assertEqual(panel._mode, "synced")
        self.assertEqual(panel.list.count(), 2)

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

    def test_restart_restores_last_position(self):
        """重启后恢复上次曲目与播放断点，且不自动播放。"""
        from PySide6.QtMultimedia import QMediaPlayer
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(ids[2], 2)
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        # 等媒体加载完成再 seek，否则 setPosition 会被丢弃
        self.assertTrue(_spin(lambda: self.window.player._player.mediaStatus() in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        )))
        self.window.player.seek(1200)
        self.assertEqual(self.window.player.position_ms, 1200)
        self.window.close()
        self.assertEqual(self.store.settings.last_track_id, ids[2])
        self.assertEqual(self.store.settings.last_position_ms, 1200)

        from ui.main_window import MainWindow
        window2 = MainWindow()
        try:
            self.assertEqual(window2.player.current_track.id, ids[2])
            # 恢复播放但不自动播放
            self.assertEqual(window2.player._player.playbackState(),
                             QMediaPlayer.PlaybackState.StoppedState)
            # 断点在媒体加载后真正生效
            self.assertTrue(_spin(lambda: window2.player.position_ms == 1200, timeout_ms=5000))
        finally:
            window2.player.stop()
            window2.close()

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
