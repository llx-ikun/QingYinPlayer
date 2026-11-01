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

    # ---------- 拖拽排序（v3.2.0） ----------

    def test_library_drag_switches_to_custom_and_saves(self):
        """音乐库拖一下：自动切「自定义顺序」+ 顺序落盘 + 重启后还在。

        这是 v3.2.0 的主验收点：拖完不能弹回去（切预设），关软件不能丢（落盘）。
        """
        self._import()
        self.window.set_view("__library__")
        self.assertNotEqual(self.window._sort_id, "custom:asc",
                            "默认是「最近导入」，先确认起点不是自定义序")
        before = [t.id for t in self.window._displayed]
        self.assertTrue(self.window.track_list._drag_enabled, "音乐库也该能拖了")

        # 把第 0 行拖到末尾
        last = len(before) - 1
        self.window.track_list._on_rows_moved(None, 0, 0, last + 1)

        self.assertEqual(self.window._sort_id, "custom:asc", "拖完必须切到自定义顺序")
        after = [t.id for t in self.window._displayed]
        self.assertEqual(after, [*before[1:], before[0]], "界面顺序要跟着变")
        self.assertEqual(self.store.settings.view_orders["__library__"], after)

        # 新实例读同一个 data.json（模拟重启）
        from app.paths import data_file
        from app.store import LibraryStore
        again = LibraryStore(data_file())
        self.assertEqual(again.settings.view_orders["__library__"], after)
        self.window.set_view("__library__")

    def test_library_drag_disabled_while_searching(self):
        """搜索时显示的是子集，按可见顺序落盘会把没显示的曲子挤走 → 禁拖。"""
        self._import()
        self.window.set_view("__library__")
        self.assertTrue(self.window.track_list._drag_enabled)
        self.window._on_search_changed("晴")
        self.assertFalse(self.window.track_list._drag_enabled,
                         "搜索状态下不能拖")
        self.window._on_search_changed("")
        self.assertTrue(self.window.track_list._drag_enabled, "清空搜索要恢复")

    def test_recent_view_never_drag_reorderable(self):
        """「最近播放」按播放时间动态排，拖了也会被重算打乱 → 直接不给拖。"""
        self._import()
        self.window.set_view("__recent__")
        self.assertFalse(self.window.track_list._drag_enabled)
        self.window.set_view("__library__")

    def test_context_menu_has_no_move_up_down(self):
        """v3.2.0 删掉「上移/下移」，避免和拖拽两条路并存。"""
        self._import()
        menu, actions = self.window.track_list._build_menu(
            self.store.all_tracks()[0].id)
        try:
            self.assertNotIn("move_up", actions)
            self.assertNotIn("move_down", actions)
        finally:
            menu.deleteLater()

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
        from ui.theme import COLUMBINA, LIGHT
        app = QApplication.instance()
        self._import()
        # 新装默认「浅色」主题
        self.assertEqual(self.store.settings.theme, "light")
        self.assertIn(LIGHT.ACCENT, app.styleSheet())
        self.window._apply_theme("columbina")
        self.assertEqual(self.store.settings.theme, "columbina")
        self.assertIn(COLUMBINA.ACCENT, app.styleSheet())
        # 重启后主题保持
        self.window.close()
        from ui.main_window import MainWindow
        window2 = MainWindow()
        try:
            self.assertEqual(window2.store.settings.theme, "columbina")
        finally:
            window2.player.stop()
            window2.close()

    def test_float_bar_theme_toggle(self):
        """主题钮按 THEME_ORDER 轮转，图标/提示指向「点下去会切到哪个」。

        v3.1.0：配色从两套变四套（深→浅交替），所以断言**全部从真相源推导**
        （THEME_NEXT / THEME_ICON / THEME_LABEL），不写死「深色/浅色」这种两态语义
        —— 否则再加主题时这例会假失败，而且失败信息会误导成「切换逻辑坏了」。
        """
        from ui.theme import (THEME_ICON, THEME_LABEL, THEME_NEXT,
                              THEME_ORDER)
        self._import()
        fb = self.window.float_bar

        def check(cur: str) -> None:
            nxt = THEME_NEXT[cur]
            self.assertEqual(self.store.settings.theme, cur)
            # 图标/提示都指向下一个目标，而不是当前主题
            self.assertEqual(fb.theme_toggle._kind, THEME_ICON[nxt])
            self.assertIn(f"切换到{THEME_LABEL[nxt]}主题",
                          fb.theme_toggle.toolTip())
            # checked 纯装饰位：当前是浅色系（太阳）才点亮
            self.assertEqual(fb.theme_toggle.isChecked(),
                             THEME_ICON[cur] == "sun")

        cur = self.store.settings.theme
        self.assertEqual(cur, "light")   # 新装默认
        check(cur)

        # 连点一整圈：每步都从 THEME_NEXT 推期望值，末了必须闭环回起点
        for _ in range(len(THEME_ORDER)):
            self.window._toggle_theme()
            cur = THEME_NEXT[cur]
            check(cur)
        self.assertEqual(cur, "light")

        # v2.2.2 布局：左列主题圆钮 + 齿轮设置，右侧导入音乐 / 数据目录两个独立按钮
        self.assertTrue(fb.theme_toggle.isCheckable())
        self.assertEqual(fb.settings_btn._kind, "gear")
        self.assertEqual(fb.import_btn.text().replace("\n", ""), "导入音乐")
        self.assertEqual(fb.dir_btn.text().replace("\n", ""), "数据目录")
        self.assertEqual(THEME_NEXT["columbina"], "light")  # 循环表不写反

    def test_sidebar_nav_aligned_with_float_bar(self):
        """侧栏「我喜欢 / 音乐库」圆钮要与浮动条首个圆钮同尺寸、左缘同一条竖线。

        v2.6.1 起浮动条四控件单行并排，只有最左的主题钮还在 x=12；
        设置齿轮跟着排到 x=44，不再与侧栏导航同列 —— 所以只比主题钮。
        """
        from PySide6.QtCore import QPoint

        self._import()
        nav = next(iter(self.window.sidebar._nav_buttons.values()))
        bar = self.window.float_bar.theme_toggle
        nav_pt = nav.mapTo(self.window._root, QPoint(0, 0))
        self.assertEqual(bar.width(), nav.width())
        self.assertEqual(bar.height(), nav.height())
        self.assertEqual(bar.mapTo(self.window._root, QPoint(0, 0)).x(), nav_pt.x())

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
        dialog = SettingsDialog("columbina", "音乐爱好者", stats_for(self.store), self.window)
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

    def test_edge_detection_and_qt_edge_mapping(self):
        """边缘缩放：6px 判定 + 内部边位到 Qt.Edges 的映射（纯逻辑，不启动原生手势）。

        拖动边缘时窗口会移位的根因是手动 setGeometry 累加，改为 startSystemResize
        后这里只需守住「哪条边、映射成哪个 Qt.Edge」别再写错。
        """
        from PySide6.QtCore import QPoint, Qt
        from ui.main_window import _EDGE_BOTTOM, _EDGE_LEFT, _EDGE_RIGHT, _EDGE_TOP

        w = self.window
        w._root.resize(1000, 700)
        rw, rh = w._root.width(), w._root.height()
        self.assertEqual(w._edge_at(QPoint(2, 2)), _EDGE_LEFT | _EDGE_TOP)
        self.assertEqual(w._edge_at(QPoint(rw - 2, 2)), _EDGE_RIGHT | _EDGE_TOP)
        self.assertEqual(w._edge_at(QPoint(2, rh - 2)), _EDGE_LEFT | _EDGE_BOTTOM)
        self.assertEqual(w._edge_at(QPoint(rw - 2, rh - 2)), _EDGE_RIGHT | _EDGE_BOTTOM)
        self.assertEqual(w._edge_at(QPoint(2, rh // 2)), _EDGE_LEFT)
        self.assertEqual(w._edge_at(QPoint(rw // 2, 2)), _EDGE_TOP)
        self.assertEqual(w._edge_at(QPoint(rw // 2, rh // 2)), 0)
        self.assertEqual(w._qt_edges(_EDGE_LEFT), Qt.Edge.LeftEdge)
        self.assertEqual(w._qt_edges(_EDGE_LEFT | _EDGE_TOP), Qt.Edge.LeftEdge | Qt.Edge.TopEdge)
        self.assertEqual(w._qt_edges(_EDGE_RIGHT | _EDGE_BOTTOM), Qt.Edge.RightEdge | Qt.Edge.BottomEdge)

    def test_hit_test_codes_match_winuser(self):
        """v2.7.9：原生边缘缩放的 HT* 码必须与 winuser.h 一致。

        这几个数字写错的后果不是报错，而是**缩错方向**（拖右边变成拖左边）：
        HTLEFT=10 HTRIGHT=11 HTTOP=12 HTBOTTOM=15
        HTTOPLEFT=13 HTTOPRIGHT=14 HTBOTTOMLEFT=16 HTBOTTOMRIGHT=17
        """
        from PySide6.QtCore import QPoint

        w = self.window
        w._root.resize(1000, 700)
        rw, rh = w._root.width(), w._root.height()
        m = 3                                   # 落在 6px 判定以内
        cases = {
            QPoint(m, rh // 2): 10,
            QPoint(rw - m, rh // 2): 11,
            QPoint(rw // 2, m): 12,
            QPoint(rw // 2, rh - m): 15,
            QPoint(m, m): 13,
            QPoint(rw - m, m): 14,
            QPoint(m, rh - m): 16,
            QPoint(rw - m, rh - m): 17,
            QPoint(rw // 2, rh // 2): 0,         # 客户区：不许插手
        }
        for pos, expected in cases.items():
            self.assertEqual(w._hit_test_code(pos), expected, f"位置 {pos} 的 HT 码不对")

    def test_hit_test_is_disabled_when_maximized(self):
        """最大化后四边不能还算缩放热区，否则标题栏/播放栏边缘的按钮点不动。"""
        from PySide6.QtCore import QPoint

        w = self.window
        w._root.resize(1000, 700)
        w.showMaximized()
        try:
            self.assertTrue(w.isMaximized())
            for pos in (QPoint(2, 2), QPoint(w._root.width() - 2, 300)):
                self.assertEqual(w._hit_test_code(pos), 0)
        finally:
            w.showNormal()

    # ---------- 鼠标指针（v2.7.2） ----------

    def _send_move(self, widget, local, global_point):
        """给 widget 投递 MouseMove（会经过应用级 eventFilter）。"""
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication

        ev = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(local),
            QPointF(global_point),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(widget, ev)

    def _move_on_widget_center(self, widget):
        """在控件中心（远离窗口四边）移动一次鼠标。"""
        from PySide6.QtCore import QPoint
        center = QPoint(max(1, widget.width() // 2), max(1, widget.height() // 2))
        self._send_move(widget, center, widget.mapToGlobal(center))

    def _feed_move(self, widget, at_left_edge: bool):
        """直接喂给 eventFilter 一次移动事件，绕开 Qt 的事件冒泡。

        真实投递时 QWidget 不处理 MouseMove 会把事件冒泡给父控件，过滤器会对
        祖先再跑一遍，导致「强制光标落在哪个控件上」不确定。测逻辑就直接调。
        """
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        local = QPoint(max(1, widget.width() // 2), max(1, widget.height() // 2))
        if at_left_edge:
            gpos = self.window._root.mapToGlobal(QPoint(1, self.window._root.height() // 2))
        else:
            gpos = widget.mapToGlobal(local)
        ev = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(local),
            QPointF(gpos),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        self.window.eventFilter(widget, ev)

    def test_mouse_move_keeps_own_cursor(self):
        """坑点：eventFilter 曾在每次 MouseMove 上 unsetCursor()，把控件自己设的
        PointingHandCursor 全抹成箭头（全应用小手失效）。移动鼠标不得改控件光标。
        """
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QPushButton

        self.window.resize(1185, 760)
        buttons = [
            self.window.player_bar.play_btn,
            self.window.player_bar.prev_btn,
            self.window.player_bar.queue_btn,
            self.window.sidebar.recent_btn,
            self.window.title_bar.findChildren(QPushButton)[0],
        ]
        for btn in buttons:
            self.assertEqual(btn.cursor().shape(), Qt.CursorShape.PointingHandCursor)
            self._move_on_widget_center(btn)
            self.assertEqual(
                btn.cursor().shape(), Qt.CursorShape.PointingHandCursor,
                "鼠标移动后按钮的小手光标被抹掉了",
            )
            self.assertTrue(
                btn.testAttribute(Qt.WidgetAttribute.WA_SetCursor),
                "控件自身的光标属性（WA_SetCursor）被清掉了",
            )

    def test_edge_cursor_applies_then_restores(self):
        """贴边显示缩放箭头，离开边缘后恢复控件自己设的（小手）光标。"""
        from PySide6.QtCore import Qt

        self.window.resize(1185, 760)
        btn = self.window.player_bar.play_btn
        self._feed_move(btn, at_left_edge=True)
        self.assertEqual(btn.cursor().shape(), Qt.CursorShape.SizeHorCursor)
        self._feed_move(btn, at_left_edge=False)
        self.assertEqual(btn.cursor().shape(), Qt.CursorShape.PointingHandCursor,
                         "离开边缘后没有恢复成小手光标")
        self.assertTrue(btn.testAttribute(Qt.WidgetAttribute.WA_SetCursor),
                        "恢复后控件应重新是「自带光标」状态")

    def test_edge_cursor_does_not_leak_to_other_widget(self):
        """贴边改了 A 的光标后移到 B：A 必须还原，B 不能被留下显式光标。"""
        from PySide6.QtCore import Qt

        self.window.resize(1185, 760)
        btn = self.window.player_bar.play_btn
        plain = self.window.track_list  # 自身没设光标，走「继承」分支
        self._feed_move(btn, at_left_edge=True)
        self.assertEqual(btn.cursor().shape(), Qt.CursorShape.SizeHorCursor)
        self._feed_move(plain, at_left_edge=False)
        self.assertEqual(btn.cursor().shape(), Qt.CursorShape.PointingHandCursor,
                         "上一个控件残留了缩放箭头")
        self.assertFalse(plain.testAttribute(Qt.WidgetAttribute.WA_SetCursor),
                         "不该给没自带光标的控件留下显式光标")


    def test_lyrics_source_label_shows_line_to_sentence_count(self):
        """来源小字要带「N 行 → M 句」对照（v2.7.3）。

        双语 txt 一行原文一行译文，界面按句显示会少一半；没有这个数字，用户看到
        行数对不上就会以为歌词丢了。
        """
        from app.lyrics import lyrics_from_text
        from ui.main_window import MainWindow

        text = ("作词 : 甲\n作曲 : 乙\n"
                "Who can surely know\n风将吹向何方\n"
                "How the wind blows,\n谁也捉摸不透")
        synced, plain = lyrics_from_text(text)
        self.assertEqual(synced, [])
        label = MainWindow._lyrics_label("本地歌词 · 同名 .txt", text, synced, plain)
        self.assertIn("6 行", label, "应报告 txt 原始非空行数")
        self.assertIn("2 句", label, "应报告合并双语后的句数")

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
        """各视图分别记住排序：切走再切回音乐库，不会被重置回默认值。"""
        from app.models import PLAYLIST_FAVORITES, PLAYLIST_LIBRARY
        self._import()
        self.window._on_sort_changed("size:asc")
        self.window.set_view(PLAYLIST_FAVORITES)   # 另一个视图用各自默认
        self.assertEqual(self.window._sort_id, "added:desc")
        self.window.set_view(PLAYLIST_LIBRARY)     # 切回音乐库
        self.assertEqual(self.window._sort_id, "size:asc")
        self.assertEqual(self.window.track_list.sort_combo.currentData(), "size:asc")

    def test_playlist_default_sort_keeps_custom_order(self):
        """歌单默认「自定义顺序」；切到别的排序也仍可拖（拖一下自动切回自定义）。"""
        self._import()
        pid = self.store.create_playlist("排序测试").id
        ids = [t.id for t in self.store.all_tracks()]
        self.store.add_to_playlist(pid, ids)
        self.window.set_view(pid)
        self.assertEqual(self.window._sort_id, "custom:asc")
        self.assertTrue(self.window.track_list._drag_enabled)
        self.window._on_sort_changed("title:asc")
        # v3.2.0：不再因为"非自定义排序"就禁拖 —— 拖一下会自动切回自定义顺序，
        # 这正是"随时能手动排"的前提。禁拖只剩两种情况：搜索中 / 最近播放。
        self.assertTrue(self.window.track_list._drag_enabled,
                        "非自定义排序下也能拖，拖完自动切回自定义顺序")
        self.window._on_sort_changed("custom:asc")

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

    一律不联网：`ui.main_window.MultiSourceWorker` 换成只记一笔的假线程；
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
            found = Signal(str, str, str)
            missed = Signal(str)
            aborted = Signal(str)
            progress = Signal(int, int)
            finished = Signal()

            def __init__(self, track_id, title, artist, duration_ms=0,
                         album="", parent=None):
                super().__init__(parent)
                self.track_id = track_id
                self.title = title
                self.artist = artist
                self.album = album

            def start(self):
                starts.append(self.track_id)

            # 假线程也要长得像 QThread，否则 closeEvent 里的 wait() 会炸
            def isRunning(self):  # noqa: N802
                return False

            # v2.7.5：closeEvent 现在会先 requestInterruption() 再 wait()，
            # 桩对象必须同步实现，否则关窗直接 AttributeError
            def requestInterruption(self):  # noqa: N802
                self.interrupted = True

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
        with mock.patch.object(mw, "MultiSourceWorker", self._fake_worker(starts)):
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
        with mock.patch.object(mw, "MultiSourceWorker", self._fake_worker(starts)):
            self.window._load_lyrics(track)
            self.window._load_lyrics(track)      # 同一首再进一次不该重复打网络
        self.assertEqual(starts, [track.id])
        self.assertEqual(self.window.now_playing.lyrics.empty_label.text(),
                         "正在联网匹配歌词…")

        # 假装后台线程抓到了歌词
        self.window._on_online_lyrics(track.id, "[00:01.00]故事的小黄花")
        self.assertEqual(read_cache(track.id), "[00:01.00]故事的小黄花")
        synced, _, _ = self.window._lyrics_cache[track.id]
        self.assertEqual([line.text for line in synced], ["故事的小黄花"])

        # 清掉内存缓存后重新加载：走「本地缓存」这一级，面板能显示歌词
        self.window._lyrics_cache.pop(track.id)
        self.window._load_lyrics(track)
        self.assertEqual(self.window.now_playing.lyrics.list.count(), 1)
        self.assertEqual(self.window.now_playing.lyrics.list.item(0).text(), "故事的小黄花")

    def test_progress_slot_matches_worker_signal(self):
        """v2.7.2 修：槽签名比信号少一个参数，每次上报都抛 TypeError，
        「正在联网匹配歌词…」从未显示过。

        v2.7.7 起信号是 `Signal(int, int, str)`，第三个参数是已返回的平台名，
        文案要同时体现「进度」和「查了哪些平台」。
        """
        track = self._bare_track()
        self.window.player._current = track
        self.window._lyrics_cache.pop(track.id, None)

        self.window._on_online_lyrics_progress(2, 3, "LRCLIB、网易云")
        self.assertEqual(self.window.now_playing.lyrics.empty_label.text(),
                         "联网匹配 2/3 · LRCLIB、网易云")

        # 只发两个参数的老调用/桩对象也不能炸（第三参数有默认值）
        self.window._on_online_lyrics_progress(1, 3)
        self.assertEqual(self.window.now_playing.lyrics.empty_label.text(),
                         "联网匹配 1/3")

    def test_start_shows_platform_list_immediately(self):
        """v2.7.7：一发起检索就把「要查哪几个平台」写出来，别让人对着空白干等。

        并行模式下这些请求是同时发出的，所以这是「清单」而不是「正在查某一个」。
        """
        import ui.main_window as mw
        from app.lyrics_multi import DEFAULT_SOURCES

        starts = []
        track = self._bare_track()
        self.window.player._current = track
        self.window._lyrics_cache.pop(track.id, None)
        with mock.patch.object(mw, "MultiSourceWorker", self._fake_worker(starts)):
            self.assertTrue(self.window._start_online_lyrics(track, force=True))

        expected = "联网匹配：" + "、".join(name for name, _ in DEFAULT_SOURCES)
        self.assertEqual(self.window.now_playing.lyrics.empty_label.text(), expected)
        self.assertIn("网易云", expected)      # 平台名真的在文案里，不是一个泛泛的提示

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
        with mock.patch.object(mw, "MultiSourceWorker", self._fake_worker(starts)):
            self.assertFalse(self.window._start_online_lyrics(track))

        self.store.settings.online_lyrics = True
        video = self._bare_track()
        video.fmt = "mp4"                     # 视频不配歌词
        with mock.patch.object(mw, "MultiSourceWorker", self._fake_worker(starts)):
            self.assertFalse(self.window._start_online_lyrics(video))
        self.assertEqual(starts, [])

    def test_miss_cache_suppresses_retry_until_manual_retry(self):
        """v2.4 负缓存：查不到的歌 7 天内不自动重打；右键「重新联网匹配」强制重来。

        没有这层记忆时，每启动一次就为一首冷门歌打四个请求，既慢又吃速率配额。
        """
        import ui.main_window as mw
        from app.lyrics_online import clear_miss, read_miss, write_miss

        track = self._bare_track()
        starts = []
        write_miss(track.id)
        self.assertTrue(read_miss(track.id))

        with mock.patch.object(mw, "MultiSourceWorker", self._fake_worker(starts)):
            self.assertFalse(self.window._start_online_lyrics(track),
                             "负缓存有效期内不该再发起检索")
            self.assertEqual(starts, [])

            # 手动重试：清负缓存 → 绕过「本次已试过」→ 真的发起，并显示等待提示
            # （`current_track` 是只读属性，直接改内部字段；这里不真的播放音频）
            self.window.player._current = track
            self.window._retry_online_lyrics()
        self.assertFalse(read_miss(track.id), "重试前必须清掉负缓存，否则下次又被挡住")
        self.assertEqual(starts, [track.id])
        self.assertEqual(self.window.now_playing.lyrics.empty_label.text(),
                         "正在联网匹配歌词…")
        clear_miss(track.id)

    def test_online_aborted_shows_retry_hint_but_no_negative_cache(self):
        """联网被中断（超时/限流）：歌词区不再卡在「正在找」，显示可重试提示，
        且**不写负缓存**——一次网络抖动不等于这首歌没有歌词。"""
        import ui.main_window as mw
        from app.lyrics_online import read_miss

        track = self._bare_track()
        self.window.player._current = track
        self.window.now_playing.set_empty(mw.ONLINE_PENDING_HINT)
        self.window._on_online_lyrics_aborted(track.id)
        self.assertEqual(self.window.now_playing.lyrics.empty_label.text(),
                         mw.ONLINE_ABORTED_HINT)
        self.assertFalse(read_miss(track.id), "中止时绝不能落负缓存")

    def test_settings_dialog_online_lyrics_toggle_persists(self):
        from app.paths import data_file
        from app.store import LibraryStore
        from ui.settings_dialog import SettingsDialog, stats_for

        self.assertTrue(self.store.settings.online_lyrics)
        dialog = SettingsDialog("columbina", "音乐爱好者", stats_for(self.store), self.window,
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

    def test_version_label_follows_app_version(self):
        """v2.7.6：右下角版本号必须跟随 app.version，不许再是写死的字符串。

        事故背景：这里曾经硬编码 "v2.6.12 · 本地音乐与视频"，而代码早已走到
        v2.7.5 —— 界面显示的版本与实际版本长期不符，直接把排查方向带沟里。
        """
        from app.version import APP_VERSION, version_text

        self.assertEqual(self.window.version_label.text(), version_text())
        self.assertIn(APP_VERSION, self.window.version_label.text())
        self.assertNotIn("v2.6.12", self.window.version_label.text())

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
        from ui.theme import THEMES, current_theme

        theme_name = self.store.settings.theme
        self.window._on_settings_accent("#ff7a45")
        self.window._on_settings_accent("")
        self.assertEqual(self.store.settings.accent_color, "")
        # 默认主题是「浅色」，默认强调色要跟主题表走，别写死某个主题
        self.assertEqual(current_theme().ACCENT, THEMES[theme_name].ACCENT)

    def test_accent_survives_theme_switch(self):
        """切主题不该把手选的颜色丢掉——只有"跟随主题"才回到默认色。"""
        from ui.theme import current_theme

        self.window._on_settings_accent("#22c55e")
        self.window._apply_theme("light")
        self.assertEqual(current_theme().ACCENT, "#22c55e")

    def test_font_scale_rebuilds_qss_and_keeps_layout(self):
        """字号放大后 QSS 要真变，且播放栏最小宽度不得突破窗口最小宽。"""
        from PySide6.QtWidgets import QApplication
        from ui.main_window import WINDOW_MIN_WIDTH

        self._import()
        self.window._on_settings_font_scale(1.28)
        sheet = QApplication.instance().styleSheet()
        self.assertIn("font-size: 17px", sheet)     # 基础 13px × 1.28 ≈ 17
        self.assertLessEqual(self.window.player_bar.minimumSizeHint().width(),
                             WINDOW_MIN_WIDTH)
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

        dialog = SettingsDialog("columbina", "音乐爱好者", stats_for(self.store), self.window,
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
        dialog = SettingsDialog("columbina", "音乐爱好者", stats_for(self.store), self.window,
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

    def test_settings_dialog_has_storage_tab(self):
        """v2.6：设置里能改数据目录，并且显示的就是当前真正生效的位置。"""
        from app import paths
        from ui.settings_dialog import SettingsDialog, stats_for

        dialog = SettingsDialog("light", "音乐爱好者", stats_for(self.store), self.window)
        titles = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
        self.assertIn("存储", titles)
        self.assertEqual(os.path.normcase(dialog.storage_path_edit.text()),
                         os.path.normcase(paths.current_root()),
                         "显示的路径必须等于实际解析出来的根目录")
        self.assertTrue(dialog.storage_path_edit.isReadOnly())
        # 源码运行时便携模式会被忽略，按钮必须禁用 —— 否则用户点了会把数据
        # 搬进仓库目录、程序却不认（这是一个真实的坑）
        self.assertFalse(dialog.portable_storage_btn.isEnabled())
        dialog.deleteLater()


class TestE2ELyricsTap(unittest.TestCase):
    """逐句打轴（v2.7.4）：空格打点 / Backspace 回退 / 打满才写 .lrc。

    为什么单独成进程：每建一次 MainWindow 就多一个 QMediaPlayer，同一进程累积到
    ~15-20 个后 offscreen 下 Qt 多媒体后端会 C++ 层死锁（见 TestE2ELyricsOnline 注释）。
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

    def _track(self, name="tap-song.mp3"):
        from app.models import Track, make_track_id

        tmp = tempfile.mkdtemp(prefix="qy_tap_")
        _tmp_dirs.append(tmp)
        path = os.path.join(tmp, name)
        return Track(id=make_track_id(path), path=path, title="打轴测试",
                     artist="测试", duration_ms=180_000)

    def _arm(self, plain=None, synced=None):
        """把曲目设为「正在播放」并塞入歌词缓存，返回 (track, 行数)。"""
        track = self._track()
        self.window.player._current = track
        if synced is not None:
            self.window._lyrics_cache[track.id] = (synced, [], "本地歌词")
            count = len(synced)
        else:
            lines = plain or ["第一句", "第二句", "第三句"]
            self.window._lyrics_cache[track.id] = ([], lines, "本地歌词")
            count = len(lines)
        return track, count

    def _enter(self):
        from unittest import mock

        with mock.patch.object(type(self.window.player), "position_ms",
                               new_callable=mock.PropertyMock, return_value=1000):
            self.window._start_tap()
        return self.window

    def test_enter_tap_mode_takes_over_space(self):
        """进入打轴：空格从「播放/暂停」让给「打点」，面板停止跟随播放位置。"""
        self._arm()
        self._enter()
        w = self.window
        self.assertTrue(w._tapping)
        self.assertFalse(w._space_shortcut.isEnabled(), "空格应让给打点")
        self.assertTrue(w._tap_shortcut.isEnabled())
        self.assertTrue(w._tap_undo_shortcut.isEnabled())
        self.assertTrue(w.now_playing.lyrics._tapping, "面板应停止跟随播放位置")
        self.assertIn("打轴 0/3", w.now_playing.lyrics.source_label.text())
        self.assertEqual(w.now_playing.lyrics._current_index, 0)

    def test_tap_marks_advance_and_undo_rolls_back(self):
        from unittest import mock

        self._arm()
        self._enter()
        w = self.window
        lyrics = w.now_playing.lyrics
        with mock.patch.object(type(w.player), "position_ms",
                               new_callable=mock.PropertyMock, return_value=1500):
            w._tap_mark()
        self.assertEqual(w._tap_times, [1500])
        self.assertEqual(lyrics._current_index, 1)
        self.assertEqual(len(w._tap_times), 1)

        w._tap_undo()
        self.assertEqual(w._tap_times, [])
        self.assertEqual(lyrics._current_index, 0,
                         "回退后高亮要退回上一句")

    def test_times_stay_strictly_increasing(self):
        """沙箱里 position 不推进：连按两次空格也不能出现重复时间戳。"""
        from unittest import mock

        self._arm()
        self._enter()
        w = self.window
        with mock.patch.object(type(w.player), "position_ms",
                               new_callable=mock.PropertyMock, return_value=2000):
            w._tap_mark()
            w._tap_mark()
        self.assertEqual(w._tap_times[0], 2000)
        self.assertGreater(w._tap_times[1], w._tap_times[0],
                           "时间戳必须严格递增，否则行序与当前句判定会乱")

    def test_full_marks_write_sidecar_lrc_and_restore(self):
        """打满最后一句自动结束并写同名 .lrc；快捷键与面板状态要还原。"""
        from unittest import mock

        from app.lyrics import parse_lrc

        track, count = self._arm()
        self._enter()
        w = self.window
        positions = [1000 + 2000 * i for i in range(count)]
        for pos in positions:
            with mock.patch.object(type(w.player), "position_ms",
                                   new_callable=mock.PropertyMock, return_value=pos):
                w._tap_mark()

        self.assertFalse(w._tapping, "打满最后一句应自动结束")
        self.assertTrue(w._space_shortcut.isEnabled(), "空格要还给播放/暂停")
        self.assertFalse(w._tap_shortcut.isEnabled())

        sidecar = os.path.splitext(track.path)[0] + ".lrc"
        self.assertTrue(os.path.isfile(sidecar), "应写出同名 .lrc")
        with open(sidecar, encoding="utf-8") as f:
            parsed = parse_lrc(f.read())
        self.assertEqual([ln.text for ln in parsed], ["第一句", "第二句", "第三句"])
        self.assertEqual([ln.time_ms for ln in parsed], positions)
        # 缓存被清掉重解析，面板回到同步模式（打轴态的 -1 占位行必须换掉）
        synced, _plain, _src = w._lyrics_cache[track.id]
        self.assertEqual(len(synced), count)
        self.assertTrue(all(ln.time_ms >= 0 for ln in synced))

    def test_abort_keeps_no_file_and_restores(self):
        from unittest import mock

        track, _count = self._arm()
        self._enter()
        w = self.window
        with mock.patch.object(type(w.player), "position_ms",
                               new_callable=mock.PropertyMock, return_value=1000):
            w._tap_mark()
        w._end_tap(save=False)
        self.assertFalse(w._tapping)
        self.assertTrue(w._space_shortcut.isEnabled())
        self.assertFalse(os.path.isfile(os.path.splitext(track.path)[0] + ".lrc"),
                         "放弃时不该留下 .lrc")

    def test_bilingual_tap_uses_one_stamp_per_sentence(self):
        """双语一句两行：一个时间戳管两句，LRC 写成同时间戳两行。"""
        from unittest import mock

        from app.lyrics import lyrics_from_text, parse_lrc

        plain = ["Who can surely know", "风将吹向何方",
                 "How the wind blows,", "谁也捉摸不透"]
        track, _ = self._arm(plain=plain)
        self._enter()
        w = self.window
        self.assertEqual(w._tap_rows[0], ("Who can surely know", "风将吹向何方"))
        for pos in (1000, 3000):
            with mock.patch.object(type(w.player), "position_ms",
                                   new_callable=mock.PropertyMock, return_value=pos):
                w._tap_mark()
        sidecar = os.path.splitext(track.path)[0] + ".lrc"
        with open(sidecar, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(len(parse_lrc(text)), 4, "双语两句各写一行原文+译文")
        # 合并成「一句两行」发生在解析层，用 lyrics_from_text 才看得到译文
        synced, _ = lyrics_from_text(text)
        self.assertEqual(len(synced), 2)
        self.assertEqual(synced[0].translation, "风将吹向何方")
        self.assertEqual([ln.time_ms for ln in synced], [1000, 3000])

    def test_marker_lines_are_skipped(self):
        """段落标记行不参与打轴（它们不是唱词）。"""
        self._arm(plain=["[Verse 1]", "第一句", "我追着光"])
        self._enter()
        self.assertEqual([main for main, _ in self.window._tap_rows],
                         ["第一句", "我追着光"])


class TestE2EThemeBackground(unittest.TestCase):
    """v2.8.3 内置背景预设：星空 / 云海选了就画，且与主题彻底解耦。

    单独成类 + 独立进程：每建一次 MainWindow 就多一个 QMediaPlayer，
    offscreen 下累积到 ~15-20 个会在 C++ 层死锁（见 run_tests.py 的说明）。
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

    def _apply_preset(self, preset_id: str):
        from ui.theme import background_preset_config
        self.window._on_settings_background("all", background_preset_config(preset_id))

    def test_preset_brings_builtin_background(self):
        from ui.theme import BG_SCRIM

        for pid in ("starry", "clouds"):
            self._apply_preset(pid)
            cfg = self.window.background.config()
            self.assertEqual(cfg.type, "image", pid)
            self.assertEqual(cfg.preset, pid)
            self.assertTrue(os.path.isfile(self.window.background._image_path()),
                            f"{pid} 的背景图不存在")
            self.assertTrue(self.window.background.is_active())
            self.assertAlmostEqual(self.window._bg_scrim, BG_SCRIM,
                                   msg="有图时面板必须半透明，否则图被盖住")

    def test_preset_independent_of_theme(self):
        """预设跟主题解耦：切主题不碰背景，选预设不碰主题。"""
        self._apply_preset("starry")
        self.window._apply_theme("light")
        self.assertEqual(self.window.background.config().preset, "starry")
        self.assertEqual(self.store.settings.theme, "light")

    def test_preset_background_is_saved_as_background_not_theme(self):
        """落盘的 preset 在背景里，主题字段保持不变。"""
        from app.paths import data_file
        from app.store import LibraryStore

        self._apply_preset("clouds")
        self.window.store.save()
        saved = LibraryStore(data_file()).settings
        self.assertEqual(saved.theme, "light")
        self.assertEqual(saved.bg_all.type, "image")
        self.assertEqual(saved.bg_all.preset, "clouds")

    def test_preset_does_not_paint_vector_decor(self):
        """照片背景上不该再叠一层矢量装饰（月牙星点会变成两套背景打架）。"""
        from app.models import BackgroundConfig

        self._apply_preset("starry")
        self.assertEqual(self.window.background._decor, "")
        self.window._on_settings_background("all", BackgroundConfig(type="none"))
        self.assertEqual(self.window.background._decor, "light")

    def test_settings_bg_tab_has_preset_cards(self):
        from ui.settings_dialog import SettingsDialog, stats_for

        dialog = SettingsDialog("light", "音乐爱好者", stats_for(self.store), self.window)
        # v3.1.1：四套配色按页拆开摆 —— 纯色的曜石/珍珠在「外观」页（跟强调色、
        # 字号一起），带装饰底纹的星夜/月白在「背景」页（跟背景图案一起）。
        # 断言用 parentWidget 判"摆在哪页"，不猜布局顺序。
        for tid in ("obsidian", "pearl"):
            self.assertIs(dialog.theme_radios[tid].parentWidget(),
                          dialog.appearance_page, f"{tid} 应在「外观」页")
        for tid in ("columbina", "light"):
            self.assertIs(dialog.theme_radios[tid].parentWidget(),
                          dialog.background_page, f"{tid} 应在「背景」页")
        # 背景页有星空/云海两张内置卡片
        self.assertEqual(set(dialog.preset_buttons), {"starry", "clouds"})
        dialog.deleteLater()

    def test_theme_radios_exclusive_across_pages(self):
        """跨页单选必须互斥（v3.1.1）。

        QRadioButton 的互斥是**按 parent 分组**的，两页各摆一部分之后它们不再
        是同一个 parent → 默认会各亮一个，界面上同时显示两套配色被选中。
        这例钉住 QButtonGroup 的跨页互斥，防止有人"优化"掉它。
        """
        from ui.settings_dialog import SettingsDialog, stats_for

        dialog = SettingsDialog("light", "音乐爱好者", stats_for(self.store), self.window)
        try:
            self.assertTrue(dialog.theme_radios["light"].isChecked())

            dialog.theme_radios["obsidian"].setChecked(True)   # 外观页
            self.assertFalse(dialog.theme_radios["light"].isChecked(),   # 背景页
                             "选了「外观」页的曜石，「背景」页的月白必须自动取消")
            self.assertFalse(dialog.theme_radios["columbina"].isChecked())
            self.assertFalse(dialog.theme_radios["pearl"].isChecked())

            dialog.theme_radios["columbina"].setChecked(True)  # 反向再验一次
            self.assertFalse(dialog.theme_radios["obsidian"].isChecked())
        finally:
            dialog.deleteLater()

    def test_per_page_preset_marks_custom(self):
        """分页面点内置预设：必须自动「本页单独设置」，否则会被 bg_all 静默吞掉。

        复现根因：切到「列表页/正在播放页」设背景时 inherit 仍是默认 True（跟随
        「全部页面」），Settings.bg_config() 退回 bg_all，表现就是「设了没反应」。
        """
        from ui.settings_dialog import SettingsDialog, stats_for

        dialog = SettingsDialog("light", "音乐爱好者", stats_for(self.store), self.window,
                                bg_scope="library")
        self.assertTrue(dialog._current_bg().inherit, "初始应跟随「全部页面」")

        emitted = []
        dialog.background_changed.connect(lambda scope, cfg: emitted.append((scope, cfg)))
        dialog._apply_preset("starry")

        self.assertFalse(dialog._current_bg().inherit, "分页面设背景要自动「本页单独设置」")
        self.assertTrue(dialog.bg_inherit_box.isChecked())
        scope, cfg = emitted[-1]
        self.assertEqual(scope, "library")
        self.assertFalse(cfg.inherit)

        # 写进主窗口后，当前页（列表页）真的画上了预设图
        self.window._on_settings_background(scope, cfg)
        self.assertEqual(self.window.background.config().preset, "starry")
        dialog.deleteLater()


class TestE2ELyricsColor(unittest.TestCase):
    """v2.9.0 歌词颜色覆盖：设置持久化 / 面板下发 / 逐句色落盘与恢复。

    独立成类 + 独立进程：每建一次 MainWindow 就多一个 QMediaPlayer，offscreen 下
    累积到 ~15-20 个会在 C++ 层死锁（见 run_tests.py 说明）。
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

    def _cfg(self, **kw):
        from app.models import LyricsColorConfig
        return LyricsColorConfig(enabled=True, color_a="#ff6b9d", **kw)

    def test_enable_persists_and_applies(self):
        from app.models import LyricsColorConfig
        from app.paths import data_file
        from app.store import LibraryStore

        self.window._on_settings_lyrics_color(self._cfg())
        self.assertTrue(self.store.settings.lyrics_color.enabled)
        self.assertIsNotNone(self.window.now_playing.lyrics._active_color_cfg())
        saved = LibraryStore(data_file()).settings.lyrics_color
        self.assertTrue(saved.enabled, "歌词颜色配置要落盘")
        self.assertEqual(saved.color_a, "#ff6b9d")
        # 关闭后必须回到旧渲染路径
        self.window._on_settings_lyrics_color(LyricsColorConfig(enabled=False))
        self.assertIsNone(self.window.now_playing.lyrics._active_color_cfg())

    def test_per_line_color_roundtrip_and_clear(self):
        from app.lyrics import LyricLine
        from app.lyrics_colors import load_line_colors, set_line_color
        from app.models import Track

        track = Track(id="color-track", path="/no/such.mp3", title="t")
        self.window.player._current = track     # current_track 只读，直接改内部字段
        panel = self.window.now_playing.lyrics
        panel.set_synced([LyricLine(1000, "第一句"), LyricLine(5000, "第二句")])

        mapping = set_line_color(track.id, panel.line_time(1), "#00ff00")
        panel.set_line_colors(mapping)
        a, _b = panel._row_colors(1)
        self.assertEqual(a.name(), "#00ff00")
        self.assertEqual(load_line_colors(track.id), {5000: "#00ff00"})

        self.window._on_lyric_song_colors_clear()
        self.assertEqual(load_line_colors(track.id), {}, "清除本曲要清空 sidecar")
        self.assertEqual(panel._line_color_map, {})

    def test_pick_line_color_writes_sidecar(self):
        from unittest import mock

        import ui.main_window as mw
        from PySide6.QtGui import QColor
        from app.lyrics import LyricLine
        from app.lyrics_colors import load_line_colors
        from app.models import Track

        class FakeColorDialog:
            @staticmethod
            def getColor(*_a, **_k):
                return QColor("#123456")

        track = Track(id="pick-track", path="/no/such.mp3", title="t")
        self.window.player._current = track
        panel = self.window.now_playing.lyrics
        panel.set_synced([LyricLine(1000, "第一句")])

        with mock.patch.object(mw, "QColorDialog", FakeColorDialog):
            self.window._on_lyric_line_color(0)

        self.assertEqual(load_line_colors(track.id), {1000: "#123456"})
        a, _b = panel._row_colors(0)
        self.assertEqual(a.name(), "#123456")

    def test_settings_dialog_color_signal(self):
        from app.models import LyricsColorConfig
        from ui.settings_dialog import SettingsDialog, stats_for

        dialog = SettingsDialog("light", "音乐爱好者", stats_for(self.store),
                                self.window,
                                lyrics_color=LyricsColorConfig(enabled=False))
        got = []
        dialog.lyrics_color_changed.connect(got.append)
        dialog.color_enabled_box.setChecked(True)
        self.assertTrue(got and got[-1].enabled)
        dialog.color_trigger_combo.setCurrentIndex(
            max(0, dialog.color_trigger_combo.findData("time")))
        self.assertEqual(got[-1].trigger, "time")
        dialog.color_direction_combo.setCurrentIndex(
            max(0, dialog.color_direction_combo.findData("diagonal")))
        self.assertEqual(got[-1].direction, "diagonal")
        dialog._reset_lyric_colors()
        self.assertEqual(got[-1].color_a, "")
        self.assertEqual(got[-1].color_b, "")
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
