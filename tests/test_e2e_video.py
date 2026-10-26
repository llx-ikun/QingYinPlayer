# -*- coding: utf-8 -*-
"""v2.1 视频 E2E：导入 -> 双击进视频页 -> 画面输出 -> 模式切换 -> 全屏 -> 返回列表。

独立测试类 + 独立进程（run_tests.py 里单列）：
QMediaPlayer 在 offscreen 下同进程内实例累积到 ~15-20 个会在 C++ 层死锁，
视频链路比纯音频多占播放器实例，必须单独一个进程。

注意：沙箱无音频渲染设备，position 不会自动推进；因此「进度不中断」
用「切模式前后 position_ms / current_track / 媒体源不变」来断言。
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.make_fixtures import ensure_fixtures, ensure_video_fixture

MUSIC_DIR = ensure_fixtures()
VIDEO_PATH = ensure_video_fixture()
VIDEO_DIR = os.path.dirname(VIDEO_PATH)

_tmp_dirs: list[str] = []


def setUpModule():
    global _tmp_appdata
    _tmp_appdata = tempfile.mkdtemp(prefix="qy_e2evideo_appdata_")
    _tmp_dirs.append(_tmp_appdata)
    os.environ["APPDATA"] = _tmp_appdata

    from PySide6.QtWidgets import QApplication
    global _app
    _app = QApplication.instance() or QApplication(sys.argv[:1])

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
    global _tmp_appdata
    _tmp_appdata = tempfile.mkdtemp(prefix="qy_e2evideo_appdata_")
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


class TestE2EVideo(unittest.TestCase):
    def setUp(self):
        _fresh_appdata()
        from ui.main_window import MainWindow
        self.window = MainWindow()
        self.window.show()
        self.store = self.window.store

    def tearDown(self):
        self.window.player.stop()
        self.window.close()

    # ---------- 导入 ----------

    def _import_video(self):
        self.window._start_import([VIDEO_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        return next((t for t in self.store.all_tracks() if t.is_video), None)

    def test_import_video_into_library(self):
        track = self._import_video()
        self.assertIsNotNone(track)
        self.assertEqual(track.fmt, "avi")
        self.assertTrue(track.is_video)
        self.assertIn(track.id, [t.id for t in self.window._displayed])

    def test_video_row_shows_video_badge(self):
        self._import_video()
        rows = {self.window.track_list.list.itemWidget(self.window.track_list.list.item(i)).title.full_text(): i
                for i in range(self.window.track_list.list.count())}
        index = rows["测试短片"]
        row = self.window.track_list.list.itemWidget(self.window.track_list.list.item(index))
        self.assertEqual(row.fmt.text(), "视频")
        self.assertEqual(row.fmt.property("tier"), "video")

    # ---------- 双击进视频页 ----------

    def test_double_click_video_enters_video_page(self):
        track = self._import_video()
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(track.id, ids.index(track.id))
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        self.assertEqual(self.window.stack.currentIndex(), 1)
        self.assertEqual(self.window.now_playing.media_mode, "video")

    def test_double_click_audio_keeps_list_page(self):
        """音频双击行为不变：不跳到正在播放页。"""
        self.window._start_import([MUSIC_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        audio = next(t for t in self.store.all_tracks() if not t.is_video)
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(audio.id, ids.index(audio.id))
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        self.assertEqual(self.window.stack.currentIndex(), 0)

    # ---------- 画面输出 ----------

    def test_video_frames_are_painted(self):
        """画面链路真的在跑：sink 收到帧，且 widget 上出现非黑像素。"""
        track = self._import_video()
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(track.id, ids.index(track.id))
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        self.assertEqual(self.window.now_playing.media_mode, "video")
        # 画面控件必须可见才会绘制
        self.assertTrue(_spin(lambda: self.window.now_playing.video_host.surface.isVisible()))
        self.assertTrue(_spin(lambda: self.window.now_playing.video_host.frames > 0, timeout_ms=20000),
                        "未收到任何视频帧")
        shot = self.window.now_playing.video_host.surface.grab().toImage()
        colors = {shot.pixelColor(x, y).name()
                  for x in range(0, shot.width(), 16)
                  for y in range(0, shot.height(), 16)}
        self.assertGreater(len(colors), 1, "画面控件上只有单一颜色，说明没画出内容")

    def test_video_output_bound_to_player(self):
        """播放器绑定的是 sink，而不是每次切模式重连。"""
        self.assertIsNotNone(self.window.player.video_sink)
        self.assertIs(self.window.player.video_sink, self.window.now_playing.video_host.sink)

    # ---------- 模式切换不中断播放 ----------

    def test_music_mode_switch_keeps_playback(self):
        track = self._import_video()
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(track.id, ids.index(track.id))
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        self.window.player.seek(1200)
        before_track = self.window.player.current_track.id
        before_pos = self.window.player.position_ms
        before_source = self.window.player._player.source()

        self.window.now_playing.set_media_mode(False)
        self.assertEqual(self.window.now_playing.media_mode, "audio")
        self.assertEqual(self.window.player.current_track.id, before_track)
        self.assertEqual(self.window.player.position_ms, before_pos)
        self.assertEqual(self.window.player._player.source(), before_source)

        # 再切回视频模式，同样不中断
        self.window.now_playing.set_media_mode(True)
        self.assertEqual(self.window.now_playing.media_mode, "video")
        self.assertEqual(self.window.player.current_track.id, before_track)
        self.assertEqual(self.window.player.position_ms, before_pos)
        self.assertEqual(self.window.player._player.source(), before_source)

    def test_audio_view_offers_video_button_for_video_track(self):
        """音频模式下正在播视频时，出现「视频画面」入口。"""
        track = self._import_video()
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(track.id, ids.index(track.id))
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        self.window.now_playing.set_media_mode(False)
        self.assertTrue(self.window.now_playing.audio_view.video_btn.isVisible())
        self.window.now_playing.audio_view.video_btn.click()
        self.assertEqual(self.window.now_playing.media_mode, "video")

    def test_auto_next_switches_view_by_track_type(self):
        """切到音频曲目时，正在播放页自动回到音频模式。"""
        self.window._start_import([MUSIC_DIR, VIDEO_DIR])
        self.assertTrue(_spin(lambda: self.window._scanner is None))
        video = next(t for t in self.store.all_tracks() if t.is_video)
        audio = next(t for t in self.store.all_tracks() if not t.is_video)
        self.window.player.play_single(video.id)
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        self.assertEqual(self.window.now_playing.media_mode, "video")
        self.window.player.play_single(audio.id)
        self.assertTrue(_spin(lambda: self.window.player.current_track.id == audio.id))
        self.assertEqual(self.window.now_playing.media_mode, "audio")

    # ---------- 全屏 ----------

    def test_fullscreen_toggle_keeps_playback(self):
        track = self._import_video()
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(track.id, ids.index(track.id))
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        before_track = self.window.player.current_track.id
        before_pos = self.window.player.position_ms

        self.window._set_video_fullscreen(True)
        self.assertTrue(self.window._fullscreen.active)
        self.assertEqual(self.window.player.current_track.id, before_track)
        self.assertEqual(self.window.player.position_ms, before_pos)

        self.window._set_video_fullscreen(False)
        self.assertFalse(self.window._fullscreen.active)
        self.assertEqual(self.window.player.current_track.id, before_track)
        self.assertEqual(self.window.player.position_ms, before_pos)

    def test_escape_exits_fullscreen_before_clearing_search(self):
        """全屏状态下 Esc 优先退出全屏，不清空搜索框。"""
        self.window.title_bar.search_box.setText("周杰伦")
        self.window._set_video_fullscreen(True)
        self.assertTrue(self.window._fullscreen.active)
        self.window._on_escape()
        self.assertFalse(self.window._fullscreen.active)
        self.assertEqual(self.window.title_bar.search_box.text(), "周杰伦")

    def test_f11_shortcut_toggles_fullscreen(self):
        self.window._toggle_video_fullscreen()
        self.assertTrue(self.window._fullscreen.active)
        self.window._toggle_video_fullscreen()
        self.assertFalse(self.window._fullscreen.active)

    # ---------- 返回列表 ----------

    def test_back_to_list_keeps_playing(self):
        track = self._import_video()
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(track.id, ids.index(track.id))
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        before_track = self.window.player.current_track.id

        self.window.now_playing.video_view.back_btn.click()
        self.assertEqual(self.window.stack.currentIndex(), 0)
        self.assertEqual(self.window.player.current_track.id, before_track)

    # ---------- 收藏 / 队列 / 时长 ----------

    def test_video_supports_favorite_and_queue(self):
        track = self._import_video()
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(track.id, ids.index(track.id))
        self.assertTrue(_spin(lambda: self.window.player.current_track is not None))
        self.assertIn(track.id, self.window.player.queue_ids)
        self.window._toggle_current_favorite()
        self.assertTrue(self.store.is_favorite(track.id))

    def test_video_duration_backfilled_after_load(self):
        """mutagen 读不出 AVI 时长，加载后由播放器回填并落盘。"""
        track = self._import_video()
        self.assertEqual(track.duration_ms, 0)
        ids = [t.id for t in self.window._displayed]
        self.window._on_track_activated(track.id, ids.index(track.id))
        self.assertTrue(_spin(lambda: self.window.player.duration_ms > 0, timeout_ms=20000))
        self.assertTrue(_spin(lambda: self.store.get_track(track.id).duration_ms > 0))
        self.assertEqual(self.store.get_track(track.id).duration_ms, self.window.player.duration_ms)


if __name__ == "__main__":
    unittest.main()
