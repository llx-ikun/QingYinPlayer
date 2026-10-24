# -*- coding: utf-8 -*-
"""app.player 播放控制器测试（offscreen）。

注意：构建沙箱无音频渲染设备，播放时 position 不会自动推进
（已在环境探测中确认），因此这里只验证状态机、seek、音量与错误处理，
「声音与进度自动推进」需交付后在本机验证。
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
    from PySide6.QtWidgets import QApplication
    global _app
    _app = QApplication.instance() or QApplication(sys.argv[:1])


def _spin(predicate, timeout_ms=5000, interval_ms=20):
    """驱动 Qt 事件循环直到 predicate 为真或超时。"""
    from PySide6.QtCore import QCoreApplication
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(interval_ms / 1000)
    return predicate()


class SignalCollector:
    def __init__(self, *signals):
        self.calls = []
        for s in signals:
            s.connect(lambda *a, _s=s: self.calls.append((_s, a)))


class TestPlaybackController(unittest.TestCase):
    def setUp(self):
        from app.metadata import read_track
        from app.store import LibraryStore

        self.tmp = tempfile.mkdtemp(prefix="qy_player_")
        self.store = LibraryStore(os.path.join(self.tmp, "data.json"))
        self.paths = {}
        for name in ("晴天 - 周杰伦.mp3", "夜曲.flac", "晨间轻音乐.wav", "海浪的声音.ogg"):
            path = os.path.join(MUSIC_DIR, name)
            track = self.store.add_or_update(read_track(path), path)
            self.paths[name] = track.id
        from app.player import PlaybackController
        self.controller = PlaybackController(self.store)

    # ---------- 基础播放 ----------

    def test_play_tracks_changes_track_and_state(self):
        from PySide6.QtMultimedia import QMediaPlayer
        events = []
        self.controller.track_changed.connect(lambda t: events.append(t.id))
        self.controller.state_changed.connect(lambda s: events.append(s))
        ids = list(self.paths.values())
        self.controller.play_tracks(ids, 1)
        self.assertTrue(_spin(lambda: len(events) >= 2))
        self.assertEqual(self.controller.current_track.id, self.paths["夜曲.flac"])
        self.assertEqual(self.controller._player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)

    def test_pause_resume_stop(self):
        from PySide6.QtMultimedia import QMediaPlayer
        ids = list(self.paths.values())
        self.controller.play_tracks(ids, 0)
        self.assertTrue(_spin(lambda: self.controller._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState))
        self.controller.pause()
        self.assertEqual(self.controller._player.playbackState(), QMediaPlayer.PlaybackState.PausedState)
        self.controller.resume()
        self.assertEqual(self.controller._player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
        self.controller.stop()
        self.assertEqual(self.controller._player.playbackState(), QMediaPlayer.PlaybackState.StoppedState)
        self.controller.toggle_play()  # stopped -> 重新播放
        self.assertEqual(self.controller._player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)

    def test_next_previous(self):
        ids = list(self.paths.values())
        self.controller.play_tracks(ids, 0)
        self.controller.next()
        self.assertEqual(self.controller.current_track.id, self.paths["夜曲.flac"])
        self.controller.next()
        self.assertEqual(self.controller.current_track.id, self.paths["晨间轻音乐.wav"])
        self.controller.previous()  # position < 3s -> 上一首
        self.assertEqual(self.controller.current_track.id, self.paths["夜曲.flac"])

    # ---------- seek / 音量 ----------

    def test_seek(self):
        from PySide6.QtMultimedia import QMediaPlayer
        positions = []
        self.controller.position_changed.connect(positions.append)
        ids = list(self.paths.values())
        self.controller.play_tracks(ids, 0)
        self.assertTrue(_spin(lambda: self.controller._player.mediaStatus() in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
            QMediaPlayer.MediaStatus.EndOfMedia,
        )))
        self.controller.seek(1000)
        self.assertEqual(self.controller.position_ms, 1000)
        self.assertIn(1000, positions)

    def test_volume_and_mute(self):
        self.controller.set_volume(0.4)
        self.assertEqual(self.controller.volume, 0.4)
        self.assertAlmostEqual(self.controller._audio.volume(), 0.4, places=5)
        self.controller.toggle_mute()
        self.assertTrue(self.controller.muted)
        self.assertAlmostEqual(self.controller._audio.volume(), 0.0, places=5)
        self.controller.set_volume(0.6)  # 调音量自动解除静音
        self.assertFalse(self.controller.muted)
        self.assertAlmostEqual(self.controller._audio.volume(), 0.6, places=5)

    def test_mode_cycle_persists(self):
        seen = []
        self.controller.mode_changed.connect(seen.append)
        order = [self.controller.cycle_mode() for _ in range(4)]
        self.assertEqual(order, ["sequential", "single", "shuffle", "loop"])
        self.assertEqual(self.store.settings.play_mode, "loop")
        self.assertEqual(seen, ["sequential", "single", "shuffle", "loop"])

    # ---------- 错误处理 ----------

    def test_missing_file_errors_and_skips(self):
        from app.metadata import TrackMeta
        from app.models import Track, make_track_id
        errors = []
        self.controller.error.connect(errors.append)
        ghost = os.path.join(self.tmp, "幽灵歌曲.mp3")
        self.store.tracks["ghost"] = Track(id="ghost", path=ghost, title="幽灵歌曲")
        self.controller.play_tracks(["ghost", self.paths["夜曲.flac"]], 0)
        self.assertTrue(_spin(lambda: len(errors) >= 1))
        self.assertIn("文件不存在", errors[0])
        self.assertEqual(self.controller.current_track.id, self.paths["夜曲.flac"])
        self.assertTrue(self.store.get_track("ghost").broken)

    def test_play_single_with_seek(self):
        from PySide6.QtMultimedia import QMediaPlayer
        self.controller.play_single(self.paths["晴天 - 周杰伦.mp3"], autoplay=False, seek_ms=800)
        self.assertTrue(_spin(lambda: self.controller._player.mediaStatus() in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
            QMediaPlayer.MediaStatus.EndOfMedia,
        )))
        self.assertEqual(self.controller.current_track.id, self.paths["晴天 - 周杰伦.mp3"])
        self.assertEqual(self.controller._player.playbackState(), QMediaPlayer.PlaybackState.StoppedState)
        self.assertGreaterEqual(self.controller.position_ms, 0)


if __name__ == "__main__":
    unittest.main()
