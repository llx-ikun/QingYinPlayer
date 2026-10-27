# -*- coding: utf-8 -*-
"""E2E 全链路测试（offscreen + 隔离 AppData）。

覆盖：导入 -> 列表 -> 播放 -> seek/音量 -> 切歌 -> 歌单 -> 歌词联动 -> 重启恢复；
v2.0 增量：双主题、我喜欢、无边框标题栏、视图历史、全局搜索、队列浮层、昵称、toast。
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

# 本模块所有测试用过的隔离 APPDATA 目录（tearDownModule 统一清理）
_tmp_dirs: list[str] = []


def setUpModule():
    # 隔离数据目录：必须在任何 app.paths 调用前设置
    global _tmp_appdata
    _tmp_appdata = tempfile.mkdtemp(prefix="qy_e2e_appdata_")
    _tmp_dirs.append(_tmp_appdata)
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


def tearDownModule():
    import shutil
    for d in _tmp_dirs:
        shutil.rmtree(d, ignore_errors=True)
    _tmp_dirs.clear()


def _fresh_appdata():
    """每个测试换一个干净的 APPDATA：data.json（收藏/last_view/主题设置）不会
    泄漏到下一个测试，用例与执行顺序彻底解耦。"""
    global _tmp_appdata
    _tmp_appdata = tempfile.mkdtemp(prefix="qy_e2e_appdata_")
    _tmp_dirs.append(_tmp_appdata)
    os.environ["APPDATA"] = _tmp_appdata


def _spin(predicate, timeout_ms=15000, interval_ms=20):
    from PySide6.QtCore import QCoreApplication
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(interval_ms / 1000)
    return predicate()


def _row(track_list, index: int):
    return track_list.list.itemWidget(track_list.list.item(index))


def _sidebar_playlist_names(sidebar) -> list[str]:
    """侧边栏歌单行名称（行结构：封面 + 文本列[名称, 数量]）。"""
    names = []
    for i in range(sidebar.playlist_list.count()):
        row = sidebar.playlist_list.itemWidget(sidebar.playlist_list.item(i))
        text_col = row.layout().itemAt(1).layout()
        names.append(text_col.itemAt(0).widget().text())
    return names


class TestE2E(unittest.TestCase):
    def setUp(self):
        _fresh_appdata()
        from ui.main_window import MainWindow
        self.window = MainWindow()
        self.window.show()
        self.store = self.window.store

    def tearDown(self):
        self.window.player.stop()
        self.window.close()

    def _import(self):
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))

    # ---------- 导入与列表 ----------

    def test_import_populates_list(self):
        self._import()
        self.assertEqual(len(self.store.all_tracks()), 5)
        self.assertEqual(self.window.track_list.list.count(), 5)
        self.assertEqual(self.window.track_list.count_label.text(), "共 5 首")
        first_row = _row(self.window.track_list, 0)
        self.assertIsNotNone(first_row)

    def test_import_copies_files_into_library(self):
        """v2.1.9：导入 = 把文件复制进软件曲库，曲目与原文件解耦。"""
        from app.library import is_in_library
        from app.models import MEDIA_EXTENSIONS
        from app.paths import library_dir

        self._import()
        lib = library_dir()
        tracks = self.store.all_tracks()
        self.assertEqual(len(tracks), 5)
        for t in tracks:
            self.assertTrue(is_in_library(t.path, lib), f"未落进曲库: {t.path}")
            self.assertTrue(os.path.isfile(t.path), f"曲库副本不存在: {t.path}")
        # 曲库目录里的媒体文件数应与曲目数一致（.lrc 歌词不算媒体）
        media = [n for n in os.listdir(lib) if n.lower().endswith(MEDIA_EXTENSIONS)]
        self.assertEqual(len(media), 5)
        # 同名歌词也被一并带进曲库（否则自动歌词失效）
        self.assertTrue(any(n.lower().endswith(".lrc") for n in os.listdir(lib)))

    def test_search_filters(self):
        self._import()
        self.window._on_search_changed("周杰伦")
        titles = [t.title for t in self.window._displayed]
        self.assertEqual(sorted(titles), ["夜曲", "晴天"])

    def test_search_from_title_bar(self):
        """v2.0：全局搜索框在标题栏，输入即过滤当前视图。"""
        self._import()
        self.window.title_bar.search_box.setText("周杰伦")
        self.assertEqual(len(self.window._displayed), 2)
        self.window.title_bar.search_box.setText("")
        self.assertEqual(len(self.window._displayed), 5)

    def test_import_list_row_fields(self):
        """导入后列表行字段逐项断言：标题/艺人/专辑/时长/格式徽标。"""
        self._import()
        rows = {}
        for i in range(self.window.track_list.list.count()):
            row = _row(self.window.track_list, i)
            rows[row.title.text()] = row
        self.assertEqual(rows["晴天"].artist.text(), "周杰伦")
        self.assertEqual(rows["晴天"].album.text(), "叶惠美")
        self.assertEqual(rows["晴天"].duration.text(), "0:02")
        self.assertEqual(rows["晴天"].fmt.text(), "MP3")
        self.assertEqual(rows["夜曲"].fmt.text(), "无损")  # FLAC -> 无损徽标
        self.assertEqual(rows["海浪的声音"].fmt.text(), "OGG")
        # 无标签文件：标题回退文件名，艺人/专辑回退默认值
        self.assertEqual(rows["无标签音频"].artist.text(), "未知艺人")
        self.assertEqual(rows["无标签音频"].album.text(), "未知专辑")

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
        self._import()
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(ids[0], 0)
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        self.window.player.seek(1000)
        self.assertEqual(self.window.player_bar.time_cur.text(), "0:01")
        self.window.player.set_volume(0.5)
        self.assertEqual(self.window.player_bar.volume_slider.value(), 50)
        self.window.player.cycle_mode()
        self.assertEqual(self.window.player.mode, "sequential")
        self.assertIn("顺序播放", self.window.player_bar.mode_btn.toolTip())

    def test_next_previous_via_bar(self):
        self._import()
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(ids[0], 0)
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        self.window.player_bar.next_clicked.emit()
        self.assertEqual(self.window.player.current_track.id, ids[1])
        self.window.player_bar.prev_clicked.emit()
        self.assertEqual(self.window.player.current_track.id, ids[0])

    # ---------- 歌单管理 ----------

    def test_playlist_flow(self):
        self._import()
        playlist = self.store.create_playlist("E2E 歌单")
        tracks = self.store.all_tracks()
        self.store.add_to_playlist(playlist.id, [t.id for t in tracks[:3]])
        self.window.set_view(playlist.id)
        self.assertEqual(self.window.track_list.list.count(), 3)
        self.assertEqual(self.window.track_list.title_label.text(), "E2E 歌单")
        self.assertIn("E2E 歌单", _sidebar_playlist_names(self.window.sidebar))
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
        self._import()
        playlist = self.store.create_playlist("旧名字")
        self.store.add_to_playlist(playlist.id, [t.id for t in self.store.all_tracks()[:2]])
        self.window.set_view(playlist.id)
        self.assertEqual(self.window.track_list.title_label.text(), "旧名字")
        with mock.patch.object(mw.QInputDialog, "getText",
                               return_value=("新名字", True)):
            self.window._playlist_action(playlist.id, "rename")
        self.assertEqual(self.store.get_playlist(playlist.id).name, "新名字")
        self.assertEqual(self.window.track_list.title_label.text(), "新名字")
        self.assertIn("新名字", _sidebar_playlist_names(self.window.sidebar))
        # 还原视图，避免影响后续用例（与 test_playlist_flow 同一约定）
        self.window.set_view("__library__")

    def test_rename_playlist_cancelled(self):
        """取消重命名对话框时不应改名，界面保持原状。"""
        import ui.main_window as mw
        self._import()
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
        self._import()
        playlist = self.store.create_playlist("排序歌单")
        tracks = self.store.all_tracks()
        self.store.add_to_playlist(playlist.id, [t.id for t in tracks])
        self.window.set_view(playlist.id)
        original = list(self.store.get_playlist(playlist.id).track_ids)
        # 模拟 QListWidget 行移动：第 0 行拖到索引 2 处（start=0, end=0, destination=2）
        self.window.track_list._on_rows_moved(None, 0, 0, 2)
        moved = self.store.get_playlist(playlist.id).track_ids
        self.assertEqual(moved, [original[1], original[0], *original[2:]])
        first_row = _row(self.window.track_list, 0)
        self.assertEqual(first_row.title.text(), tracks[1].display_title)
        self.window.set_view("__library__")

    def test_add_to_playlist_via_menu(self):
        """右键「添加到歌单」菜单：选中歌单后入库，重复添加不重复。

        注意：QMenu 必须替换模块级名字（mw.QMenu）而不是 patch 类的 exec——
        Qt 对象的实例级方法调用不经过类字典（Shiboken 特性），patch 类属性无效。
        """
        import ui.main_window as mw
        self._import()
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
        # 再次添加同一首：不入队，toast 提示已存在（v2.0 起状态栏改为 toast）
        with mock.patch.object(mw, "QMenu", FakeMenu):
            self.window._on_context_action(target.id, "add_to_playlist")
        self.assertEqual(self.store.get_playlist(playlist.id).track_ids, [target.id])
        self.assertIn("已存在", self.window._toast_label.text())
        self.window.set_view("__library__")

    # ---------- 歌词 ----------

    def test_lyrics_sync(self):
        self._import()
        target = next(t for t in self.store.all_tracks() if t.title == "晴天")
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(target.id, ids.index(target.id))
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        panel = self.window.now_playing.lyrics
        self.assertEqual(panel._mode, "synced")
        self.assertEqual(panel.list.count(), 8)  # LRC 共 8 个时间戳行
        self.window.now_playing.update_position(4000)
        self.assertEqual(panel._current_index, 1)
        panel.seek_requested.emit(1500)
        self.assertEqual(self.window.player.position_ms, 1500)

    def test_bind_lyrics_manually(self):
        """手动绑定 .lrc：优先级最高，播放时歌词面板显示绑定内容。"""
        import ui.main_window as mw
        self._import()
        target = next(t for t in self.store.all_tracks() if t.title == "无标签音频")
        lrc = os.path.join(tempfile.mkdtemp(prefix="qy_e2e_lrc_"), "手动歌词.lrc")
        with open(lrc, "w", encoding="utf-8") as f:
            f.write("[00:01.00]手动绑定第一行\n[00:02.00]手动绑定第二行\n")
        with mock.patch.object(mw.QFileDialog, "getOpenFileName",
                               return_value=(lrc, "")):
            self.window._on_context_action(target.id, "bind_lyrics")
        self.assertEqual(self.store.get_track(target.id).lrc_path, lrc)
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(target.id, ids.index(target.id))
        panel = self.window.now_playing.lyrics
        self.assertEqual(panel._mode, "synced")
        self.assertEqual(panel.list.count(), 2)

    def test_embedded_lyrics_fallback(self):
        self._import()
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
        self._import()
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
            self.assertEqual(window2.player._player.playbackState(),
                             QMediaPlayer.PlaybackState.StoppedState)
            self.assertTrue(_spin(lambda: window2.player.position_ms == 1200, timeout_ms=5000))
        finally:
            window2.player.stop()
            window2.close()

    def test_restart_restores_state(self):
        self._import()
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


class TestE2EV2(unittest.TestCase):
    """v2.0 UI 改版增量：主题 / 我喜欢 / 标题栏 / 视图历史 / 队列 / 昵称 / toast。"""

    def setUp(self):
        _fresh_appdata()
        from ui.main_window import MainWindow
        self.window = MainWindow()
        self.window.show()
        self.store = self.window.store

    def tearDown(self):
        self.window.player.stop()
        self.window.close()

    def _import(self):
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))

    # ---------- 主题 ----------

    def test_theme_switch_applies_and_persists(self):
        from PySide6.QtWidgets import QApplication
        from ui.theme import DARK, LIGHT
        app = QApplication.instance()
        self._import()
        self.assertEqual(self.store.settings.theme, "dark")
        self.window._apply_theme("light")
        self.assertEqual(self.store.settings.theme, "light")
        self.assertIn(LIGHT.ACCENT, app.styleSheet())  # 浅色强调色进入 QSS
        self.window._apply_theme("dark")
        self.assertIn(DARK.ACCENT, app.styleSheet())
        # 重启后主题保持
        self.window.close()
        from ui.main_window import MainWindow
        window2 = MainWindow()
        try:
            self.assertEqual(window2.store.settings.theme, "dark")
        finally:
            window2.player.stop()
            window2.close()

    def test_float_bar_theme_toggle(self):
        self._import()
        self.window._toggle_theme()
        self.assertEqual(self.store.settings.theme, "light")
        self.assertIn("切换到深色主题", self.window.float_bar.theme_toggle.toolTip())
        # v2.2.2 布局：左列主题圆钮 + 齿轮设置，右侧导入音乐 / 数据目录两个独立按钮
        fb = self.window.float_bar
        self.assertTrue(fb.theme_toggle.isCheckable())
        self.assertTrue(fb.theme_toggle.isChecked())  # 浅色主题 = 开关打开
        self.assertEqual(fb.settings_btn._kind, "gear")
        self.assertEqual(fb.import_btn.text(), "导入音乐")
        self.assertEqual(fb.dir_btn.text(), "数据目录")
        self.window._toggle_theme()
        self.assertEqual(self.store.settings.theme, "dark")
        self.assertFalse(self.window.float_bar.theme_toggle.isChecked())  # 深色主题 = 开关关闭

    # ---------- 我喜欢 ----------

    def test_row_heart_toggles_favorite(self):
        self._import()
        ids = [t.id for t in self.window._displayed]
        # 行内心：信号目标状态 -> store -> 侧边栏计数
        self.window.track_list.favorite_toggled.emit(ids[0], True)
        self.assertTrue(self.store.is_favorite(ids[0]))
        self.assertIn("1", self.window.sidebar._nav_buttons["__favorites__"].toolTip())
        # 行 UI 同步：第一行爱心为激活态
        row = _row(self.window.track_list, 0)
        self.assertEqual(row.fav_btn.property("active"), "true")
        # 再点一次取消
        self.window.track_list.favorite_toggled.emit(ids[0], False)
        self.assertFalse(self.store.is_favorite(ids[0]))
        row = _row(self.window.track_list, 0)
        self.assertEqual(row.fav_btn.property("active"), "false")

    def test_favorites_view_and_player_bar_heart(self):
        from app.models import PLAYLIST_FAVORITES
        self._import()
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(ids[0], 0)
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        # 播放栏心：加入我喜欢
        self.window._toggle_current_favorite()
        self.assertTrue(self.store.is_favorite(ids[0]))
        self.assertEqual(self.window.player_bar.fav_btn.property("active"), "true")
        # 「我喜欢」视图：仅含收藏曲目
        self.window.set_view(PLAYLIST_FAVORITES)
        self.assertEqual(self.window.track_list.title_label.text(), "我喜欢")
        self.assertEqual(self.window.track_list.list.count(), 1)
        self.assertEqual(self.window._displayed[0].id, ids[0])
        self.window.set_view("__library__")

    def test_favorites_survive_restart(self):
        self._import()
        ids = [t.id for t in self.window._displayed]
        self.window._on_favorite_toggled(ids[1], True)
        self.window.close()
        from ui.main_window import MainWindow
        window2 = MainWindow()
        try:
            self.assertTrue(window2.store.is_favorite(ids[1]))
            self.assertIn("1", window2.sidebar._nav_buttons["__favorites__"].toolTip())
        finally:
            window2.player.stop()
            window2.close()

    # ---------- 标题栏 / 无边框窗口 ----------

    def test_titlebar_close_button(self):
        self._import()
        self.assertTrue(self.window.isVisible())
        self.window.title_bar.close_clicked.emit()
        self.assertFalse(self.window.isVisible())

    def test_titlebar_maximize_toggle(self):
        self._import()
        self.window.title_bar.maximize_clicked.emit()
        self.assertTrue(_spin(lambda: self.window.isMaximized()))
        self.assertEqual(self.window.title_bar.max_btn.toolTip(), "还原")
        self.assertEqual(self.window._root.property("is_maximized"), "true")
        self.window.title_bar.maximize_clicked.emit()
        self.assertTrue(_spin(lambda: not self.window.isMaximized()))
        self.assertEqual(self.window.title_bar.max_btn.toolTip(), "最大化")

    def test_title_bar_has_no_back_forward_buttons(self):
        """v2.1.5：按用户要求移除标题栏的 ← / → 按钮，刷新 ↻ 保留。"""
        self._import()
        self.assertFalse(hasattr(self.window.title_bar, "back_btn"))
        self.assertFalse(hasattr(self.window.title_bar, "fwd_btn"))
        self.assertTrue(self.window.title_bar.refresh_btn.isEnabled())

    def test_view_history_shortcuts_still_bound(self):
        """按钮删了，但视图历史的 Alt+← / Alt+→ 快捷键必须还在（功能不能丢）。"""
        from PySide6.QtGui import QKeySequence, QShortcut
        self._import()
        bound = {s.key().toString() for s in self.window.findChildren(QShortcut)}
        self.assertIn(QKeySequence("Alt+Left").toString(), bound)
        self.assertIn(QKeySequence("Alt+Right").toString(), bound)

    # ---------- 视图历史 ----------

    def test_view_history_back_forward(self):
        self._import()
        playlist = self.store.create_playlist("历史歌单")
        self.window.set_view("__recent__")
        self.window.set_view(playlist.id)
        self.assertEqual(self.window._view_id, playlist.id)
        self.window.go_back()
        self.assertEqual(self.window._view_id, "__recent__")
        self.window.go_back()
        self.assertEqual(self.window._view_id, "__library__")
        # 已到历史起点：再后退不动
        self.assertEqual(self.window._history_pos, 0)
        self.window.go_back()
        self.assertEqual(self.window._view_id, "__library__")
        self.window.go_forward()
        self.assertEqual(self.window._view_id, "__recent__")
        self.window.go_forward()
        self.assertEqual(self.window._view_id, playlist.id)
        # 已到历史终点：再前进不动
        self.assertEqual(self.window._history_pos, len(self.window._history) - 1)
        self.window.go_forward()
        self.assertEqual(self.window._view_id, playlist.id)

    # ---------- 队列浮层 ----------

    def test_queue_panel_jump(self):
        self._import()
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(ids[0], 0)
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        chosen = ids[2]

        class FakeQueuePanel:
            def __init__(self, ids_arg, index, text_getter, parent=None):
                self.ids = ids_arg

            def exec_at(self, _pos):
                return chosen

        with mock.patch("ui.queue_panel.QueuePanel", FakeQueuePanel):
            self.window._show_queue_panel()
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None
                              and self.window.player.current_track.id == chosen))

    # ---------- 昵称 / toast / 设置 ----------

    def test_nickname_change(self):
        import ui.main_window as mw
        self._import()
        with mock.patch.object(mw.QInputDialog, "getText",
                               return_value=("原神启动", True)):
            self.window._change_nickname()
        self.assertEqual(self.store.settings.nickname, "原神启动")
        self.assertEqual(self.window.sidebar.nickname_label.text(), "原神启动")
        self.assertEqual(self.window.sidebar.avatar.text(), "原")

    def test_toast(self):
        self._import()
        self.window._toast("测试提示", 5000)
        self.assertEqual(self.window._toast_label.text(), "测试提示")
        self.assertTrue(self.window._toast_label.isVisible())

    def test_settings_dialog_signals(self):
        from ui.settings_dialog import SettingsDialog, stats_for
        self._import()
        dialog = SettingsDialog("dark", "音乐爱好者", stats_for(self.store), self.window)
        themes = []
        dialog.theme_changed.connect(themes.append)
        dialog.light_radio.setChecked(True)
        self.assertEqual(themes, ["light"])
        names = []
        dialog.nickname_changed.connect(names.append)
        dialog.nickname_edit.setText("新昵称")
        self.assertEqual(names, ["新昵称"])

    def test_float_bar_inside_window(self):
        self._import()
        fb = self.window.float_bar
        geom = fb.geometry()
        self.assertGreaterEqual(geom.x(), 0)
        self.assertLessEqual(geom.y() + geom.height(), self.window._root.height())
        # 位于播放栏左上角区域
        self.assertGreater(geom.y(), self.window._root.height() - 120)
        # 右缘对齐侧边栏内容右边界（不跨进内容区）
        self.assertLessEqual(geom.x() + geom.width(), 236)

    def test_version_label_at_bottom_right(self):
        """版本号从侧边栏底部挪到窗口右下角（v2.1.8）。"""
        self._import()
        lbl = self.window.version_label
        self.assertTrue(lbl.text().startswith("v"))
        self.assertTrue(lbl.isVisible(), "版本号应可见")
        g = lbl.geometry()
        root_w, root_h = self.window._root.width(), self.window._root.height()
        self.assertGreater(g.left(), root_w * 0.6, "版本号应靠窗口右侧")
        self.assertGreater(g.top(), root_h - 40, "版本号应贴窗口底部")
        # 侧边栏底部不再挂版本号
        from PySide6.QtWidgets import QLabel
        for lab in self.window.sidebar.findChildren(QLabel):
            self.assertFalse(lab.text().startswith("v2."),
                             "侧边栏里不应再有版本号")

    def test_now_playing_page_switch(self):
        self._import()
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(ids[0], 0)
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        self.window._show_page(1)
        self.assertEqual(self.window.stack.currentIndex(), 1)
        self.assertEqual(self.window.track_list.np_btn.property("active"), "true")
        self.window._show_page(0)
        self.assertEqual(self.window.track_list.np_btn.property("active"), "false")

    # ---------- 排序（v2.1.4） ----------

    def test_sort_by_size_desc(self):
        """按文件大小降序：列表顺序 = 实际体积逆序，且「大小」列有值。"""
        import os
        self._import()
        self.window._on_sort_changed("size:desc")
        sizes = [os.path.getsize(t.path) for t in self.window._displayed]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        # 行内「大小」列与真实体积一致（首行必为最大文件）
        first = _row(self.window.track_list, 0)
        self.assertNotEqual(first.size.text(), "--")

    def test_sort_by_duration_asc_then_desc(self):
        self._import()
        self.window._on_sort_changed("duration:asc")
        asc = [t.duration_ms for t in self.window._displayed]
        self.assertEqual(asc, sorted(asc))
        self.window._on_sort_changed("duration:desc")
        desc = [t.duration_ms for t in self.window._displayed]
        self.assertEqual(desc, sorted(desc, reverse=True))

    def test_recent_import_is_default_and_newest_first(self):
        """默认排序 = 「最近导入」：新增时间倒序，下拉框文案即当前排序方式。"""
        self._import()
        combo = self.window.track_list.sort_combo
        self.assertEqual(combo.currentData(), "added:desc")
        self.assertEqual(combo.currentText(), "最近导入")
        added = [t.added_at for t in self.window._displayed]
        self.assertEqual(added, sorted(added, reverse=True))

    def test_sort_choice_survives_view_switch(self):
        """各视图分别记住排序：切走再切回资料库，不会被重置回默认值。"""
        from app.models import PLAYLIST_FAVORITES, PLAYLIST_LIBRARY
        self._import()
        self.window._on_sort_changed("size:asc")
        self.window.set_view(PLAYLIST_FAVORITES)   # 另一个视图用各自默认
        self.assertEqual(self.window._sort_id, "added:desc")
        self.window.set_view(PLAYLIST_LIBRARY)     # 切回资料库
        self.assertEqual(self.window._sort_id, "size:asc")
        self.assertEqual(self.window.track_list.sort_combo.currentData(), "size:asc")

    def test_playlist_default_sort_keeps_custom_order(self):
        """歌单默认「自定义顺序」：允许拖拽，不被排序打乱。"""
        self._import()
        pid = self.store.create_playlist("排序测试").id
        ids = [t.id for t in self.store.all_tracks()]
        self.store.add_to_playlist(pid, ids)
        self.window.set_view(pid)
        self.assertEqual(self.window._sort_id, "custom:asc")
        self.assertTrue(self.window.track_list._drag_enabled)
        self.window._on_sort_changed("title:asc")
        self.assertFalse(self.window.track_list._drag_enabled,
                         "非自定义排序下应关闭拖拽，否则拖完会被排序覆盖")

    def test_header_shows_total_duration(self):
        self._import()
        total = sum(t.duration_ms for t in self.window._displayed)
        self.assertIn("总时长", self.window.track_list.stats_label.text())
        self.assertEqual(self.window.track_list.count_label.text(), f"共 {len(self.window._displayed)} 首")
        self.assertGreater(total, 0)


class TestE2ELyricsOnline(unittest.TestCase):
    """v2.2 联网补歌词接线：本地优先、只请求一次、结果落缓存、切歌不串词。

    为什么单独成类而不是塞进 TestE2EV2：同一进程内每建一次 MainWindow 就多一个
    QMediaPlayer，累积到 ~15-20 个后 offscreen 下 Qt 多媒体后端会 C++ 层死锁
    （调用随机 hang）。TestE2EV2 已经 21 项，再加 5 项实测会在
    test_theme_switch_applies_and_persists 处卡满 600s。逐类独立进程即可规避。

    一律不联网：`ui.main_window.LyricsFetchWorker` 换成只记一笔的假线程；
    真解析/打分/缓存逻辑在 tests/test_lyrics_online.py 里覆盖。
    """

    def setUp(self):
        _fresh_appdata()
        from ui.main_window import MainWindow
        self.window = MainWindow()
        self.window.show()
        self.store = self.window.store

    def tearDown(self):
        self.window.player.stop()
        self.window.close()

    def _import(self):
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))

    @staticmethod
    def _fake_worker(starts):
        from PySide6.QtCore import QObject, Signal

        class FakeWorker(QObject):
            found = Signal(str, str)
            finished = Signal()

            def __init__(self, track_id, title, artist, duration_ms=0, parent=None):
                super().__init__(parent)
                self.track_id = track_id
                self.title = title
                self.artist = artist

            def start(self):
                starts.append(self.track_id)

            # 假线程也要长得像 QThread，否则 closeEvent 里的 wait() 会炸
            def isRunning(self):  # noqa: N802
                return False

            def wait(self, *args):
                return True

            def quit(self):
                pass

        return FakeWorker

    @staticmethod
    def _bare_track(title="晴天", artist="周杰伦"):
        """造一首「磁盘上不存在、本地肯定没有歌词」的曲目，不写库。"""
        from app.models import Track, make_track_id

        tmp = tempfile.mkdtemp(prefix="qy_online_")
        _tmp_dirs.append(tmp)
        path = os.path.join(tmp, "no-lyrics.mp3")
        return Track(id=make_track_id(path), path=path, title=title,
                     artist=artist, duration_ms=269_000)

    def test_local_lyrics_win_over_online(self):
        """本地已有 .lrc 时一次网络都不该打——联网只是兜底。"""
        import ui.main_window as mw
        from app.lyrics_online import read_cache

        self._import()
        track = next(t for t in self.store.all_tracks()
                     if os.path.isfile(os.path.splitext(t.path)[0] + ".lrc"))
        starts = []
        with mock.patch.object(mw, "LyricsFetchWorker", self._fake_worker(starts)):
            self.window._load_lyrics(track)
        self.assertEqual(starts, [])
        self.assertIsNone(read_cache(track.id))
        self.assertGreater(self.window.now_playing.lyrics.list.count(), 0,
                           "本地 .lrc 应该直接渲染出歌词行")

    def test_online_lyrics_fetched_once_then_cached(self):
        """无本地歌词 → 只请求一次；结果写进缓存，之后完全离线可用。"""
        import ui.main_window as mw
        from app.lyrics_online import read_cache

        track = self._bare_track()
        starts = []
        with mock.patch.object(mw, "LyricsFetchWorker", self._fake_worker(starts)):
            self.window._load_lyrics(track)
            self.window._load_lyrics(track)      # 同一首再进一次不该重复打网络
        self.assertEqual(starts, [track.id])
        self.assertEqual(self.window.now_playing.lyrics.empty_label.text(),
                         "正在联网匹配歌词…")

        # 假装后台线程抓到了歌词
        self.window._on_online_lyrics(track.id, "[00:01.00]故事的小黄花")
        self.assertEqual(read_cache(track.id), "[00:01.00]故事的小黄花")
        synced, _ = self.window._lyrics_cache[track.id]
        self.assertEqual([line.text for line in synced], ["故事的小黄花"])

        # 清掉内存缓存后重新加载：走「本地缓存」这一级，面板能显示歌词
        self.window._lyrics_cache.pop(track.id)
        self.window._load_lyrics(track)
        self.assertEqual(self.window.now_playing.lyrics.list.count(), 1)
        self.assertEqual(self.window.now_playing.lyrics.list.item(0).text(), "故事的小黄花")

    def test_online_result_ignored_for_other_track(self):
        """异步结果回来时用户已切歌：不能把歌词串到当前这首上。"""
        track = self._bare_track()
        self.window._on_online_lyrics(track.id, "[00:01.00]别的歌的歌词")
        # 当前没有在播的曲目 → 面板保持空状态（缓存仍会写，但不会显示）
        self.assertEqual(self.window.now_playing.lyrics.empty_label.text(),
                         "暂无歌词\n支持同名 .lrc 文件与内嵌歌词")

    def test_online_lyrics_respects_setting_and_skips_video(self):
        import ui.main_window as mw

        starts = []
        track = self._bare_track()
        self.store.settings.online_lyrics = False
        with mock.patch.object(mw, "LyricsFetchWorker", self._fake_worker(starts)):
            self.assertFalse(self.window._start_online_lyrics(track))

        self.store.settings.online_lyrics = True
        video = self._bare_track()
        video.fmt = "mp4"                     # 视频不配歌词
        with mock.patch.object(mw, "LyricsFetchWorker", self._fake_worker(starts)):
            self.assertFalse(self.window._start_online_lyrics(video))
        self.assertEqual(starts, [])

    def test_settings_dialog_online_lyrics_toggle_persists(self):
        from app.paths import data_file
        from app.store import LibraryStore
        from ui.settings_dialog import SettingsDialog, stats_for

        self.assertTrue(self.store.settings.online_lyrics)
        dialog = SettingsDialog("dark", "音乐爱好者", stats_for(self.store), self.window,
                                online_lyrics=True)
        dialog.online_lyrics_changed.connect(self.window._on_settings_online_lyrics)
        dialog.online_lyrics_box.setChecked(False)
        self.assertFalse(self.store.settings.online_lyrics)
        self.assertFalse(LibraryStore(data_file()).settings.online_lyrics,
                         "开关必须落盘，重启后仍然生效")
        dialog.deleteLater()


class TestE2EAppearance(unittest.TestCase):
    """v2.2 外观自定义：强调色 / 字号缩放的应用、持久化与布局安全。

    单独成类同样是规避 QMediaPlayer 累积死锁（见 TestE2ELyricsOnline 说明）。
    """

    def setUp(self):
        _fresh_appdata()
        from ui.main_window import MainWindow
        self.window = MainWindow()
        self.window.show()
        self.store = self.window.store

    def tearDown(self):
        self.window.player.stop()
        self.window.close()

    def _import(self):
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))

    def test_accent_applies_and_persists(self):
        from PySide6.QtWidgets import QApplication
        from app.paths import data_file
        from app.store import LibraryStore

        self.window._on_settings_accent("#ff7a45")
        self.assertIn("#ff7a45", QApplication.instance().styleSheet(),
                      "强调色必须真的进到 QSS 里，否则换了也白换")
        self.assertEqual(self.store.settings.accent_color, "#ff7a45")
        self.assertEqual(LibraryStore(data_file()).settings.accent_color, "#ff7a45",
                         "外观设置要落盘，重启后保持")

    def test_reset_accent_returns_to_theme_default(self):
        from ui.theme import DARK, current_theme

        self.window._on_settings_accent("#ff7a45")
        self.window._on_settings_accent("")
        self.assertEqual(self.store.settings.accent_color, "")
        self.assertEqual(current_theme().ACCENT, DARK.ACCENT)

    def test_accent_survives_theme_switch(self):
        """切主题不该把手选的颜色丢掉——只有"跟随主题"才回到默认色。"""
        from ui.theme import current_theme

        self.window._on_settings_accent("#22c55e")
        self.window._apply_theme("light")
        self.assertEqual(current_theme().ACCENT, "#22c55e")

    def test_font_scale_rebuilds_qss_and_keeps_layout(self):
        """字号放大后 QSS 要真变，且播放栏最小宽度不得突破 1100（窗口最小宽）。"""
        from PySide6.QtWidgets import QApplication

        self._import()
        self.window._on_settings_font_scale(1.28)
        sheet = QApplication.instance().styleSheet()
        self.assertIn("font-size: 17px", sheet)     # 基础 13px × 1.28 ≈ 17
        self.assertLessEqual(self.window.player_bar.minimumSizeHint().width(), 1100)
        geom = self.window.float_bar.geometry()
        self.assertLessEqual(geom.x() + geom.width(), 236,
                             "字号变大后浮动条不能越进内容区")

    def test_font_scale_is_clamped(self):
        from ui.theme import FONT_SCALE_MAX, FONT_SCALE_MIN

        self.window._on_settings_font_scale(9.0)
        self.assertAlmostEqual(self.store.settings.font_scale, FONT_SCALE_MAX)
        self.window._on_settings_font_scale(0.1)
        self.assertAlmostEqual(self.store.settings.font_scale, FONT_SCALE_MIN)

    def test_settings_dialog_reflects_current_appearance(self):
        from ui.settings_dialog import SettingsDialog, stats_for

        self.window._on_settings_accent("#22c55e")
        self.window._on_settings_font_scale(1.15)
        dialog = SettingsDialog(
            self.store.settings.theme, self.store.settings.nickname,
            stats_for(self.store), self.window,
            online_lyrics=self.store.settings.online_lyrics,
            accent_color=self.store.settings.accent_color,
            font_scale=self.store.settings.font_scale)
        selected = [s for s in dialog.swatches if s.color == "#22c55e"]
        self.assertTrue(selected, "预设色板里应有绿色")
        self.assertTrue(selected[0]._selected, "当前强调色必须标出来")
        self.assertAlmostEqual(dialog.font_combo.currentData(), 1.15)
        dialog.deleteLater()

    def test_unknown_font_scale_snaps_to_nearest_option(self):
        from ui.settings_dialog import SettingsDialog, stats_for

        dialog = SettingsDialog("dark", "音乐爱好者", stats_for(self.store), self.window,
                                font_scale=1.1)      # 1.1 不是任何一档
        self.assertAlmostEqual(dialog.font_combo.currentData(), 1.15)
        self.assertEqual(dialog.font_combo.currentText(), "较大")
        dialog.deleteLater()

    # ---------- 自定义背景（v2.2） ----------

    def test_background_applies_and_persists(self):
        from PySide6.QtWidgets import QApplication
        from app.models import BackgroundConfig
        from app.paths import data_file
        from app.store import LibraryStore
        from ui.theme import BG_SCRIM

        config = BackgroundConfig(type="gradient", color="#1e3a8a", color2="#7c3aed",
                                  blur=4, dim=0.2)
        self.window._on_settings_background("all", config)
        self.assertTrue(self.window.background.is_active())
        self.assertAlmostEqual(self.window._bg_scrim, BG_SCRIM)
        self.assertIn("rgba(", QApplication.instance().styleSheet(),
                      "有背景时面板必须半透明，否则背景被盖住")
        self.assertEqual(LibraryStore(data_file()).settings.bg_all.type, "gradient",
                         "背景设置要落盘")
        # 背景层铺满窗口根容器（内缩 1px 留给圆角描边）
        geom = self.window.background.geometry()
        self.assertEqual(geom.x(), 1)
        self.assertEqual(geom.width(), self.window._root.width() - 2)

    def test_background_off_restores_opaque(self):
        from PySide6.QtWidgets import QApplication
        from app.models import BackgroundConfig

        self.window._on_settings_background("all", BackgroundConfig(type="color",
                                                                   color="#123456"))
        self.window._on_settings_background("all", BackgroundConfig(type="none"))
        self.assertFalse(self.window.background.is_active())
        self.assertIsNone(self.window._bg_scrim)
        self.assertNotIn("rgba(", QApplication.instance().styleSheet(),
                         "关掉背景后必须回到不透明样式，否则界面会透出桌面")

    def test_background_per_page_override(self):
        """两页各自一套背景：切页时背景跟着换，没单独设的页跟随「全部页面」。"""
        from app.models import BackgroundConfig

        self.window._on_settings_background(
            "all", BackgroundConfig(type="color", color="#111111"))
        self.window._on_settings_background(
            "now_playing", BackgroundConfig(type="color", color="#123456", inherit=False))

        self.window._show_page(1)
        self.assertEqual(self.window.background.config().color, "#123456")
        self.window._show_page(0)
        self.assertEqual(self.window.background.config().color, "#111111")

    def test_background_page_without_override_follows_all(self):
        from app.models import BackgroundConfig

        self.window._on_settings_background(
            "all", BackgroundConfig(type="gradient", color="#0f172a", color2="#334155"))
        self.window._show_page(1)      # now_playing 没设过
        self.assertEqual(self.window.background.config().type, "gradient")

    def test_background_survives_theme_switch(self):
        from app.models import BackgroundConfig

        self.window._on_settings_background(
            "all", BackgroundConfig(type="color", color="#123456"))
        self.window._apply_theme("light")
        self.assertTrue(self.window.background.is_active())
        self.assertIsNotNone(self.window._bg_scrim)


    def test_toast_is_centered_after_show(self):
        """toast 必须在窗口水平居中、位于标题栏下方。

        曾经 `_toast()` 先定位再 show()，而 `_position_toast()` 对不可见控件直接
        早退 → toast 永远停在 (0,0)，压住左上角的搜索框。
        """
        self.window._toast("测试提示")
        label = self.window._toast_label
        self.assertTrue(label.isVisible())
        root = self.window._root
        expected_x = (root.width() - label.width()) // 2
        self.assertAlmostEqual(label.x(), expected_x, delta=2)
        self.assertEqual(label.y(), 64)
        self.assertGreaterEqual(label.x(), 0)

    def test_settings_dialog_background_controls(self):
        from app.models import BackgroundConfig
        from ui.settings_dialog import SettingsDialog, stats_for

        configs = {"all": BackgroundConfig(type="gradient", color="#1e3a8a",
                                           color2="#7c3aed"),
                   "library": BackgroundConfig(),
                   "now_playing": BackgroundConfig()}
        dialog = SettingsDialog("dark", "音乐爱好者", stats_for(self.store), self.window,
                                bg_configs=configs, bg_scope="all")
        self.assertEqual(dialog.bg_type_combo.currentData(), "gradient")
        # 用 isHidden()：非当前页签的控件本来就不"可见"，isVisibleTo 会误报
        self.assertTrue(dialog.bg_inherit_box.isHidden(),
                        "「全部页面」不该显示跟随开关")
        # 切到「正在播放页」：出现跟随开关，且默认跟随
        dialog.bg_scope_combo.setCurrentIndex(2)
        self.assertEqual(dialog._bg_scope, "now_playing")
        self.assertFalse(dialog.bg_inherit_box.isHidden())
        self.assertTrue(dialog._current_bg().inherit)
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
