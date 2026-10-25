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
        self.assertTrue(_spin(
            lambda: self.controller._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState))
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
        from app.models import Track
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

    # ---------- 自动续播（EndOfMedia 调度） ----------

    def _finish_current(self):
        """模拟当前曲播完：直接驱动真实信号槽（沙箱无音频渲染，EndOfMedia 不会自然到来）。"""
        from PySide6.QtMultimedia import QMediaPlayer
        self.controller._on_media_status(QMediaPlayer.MediaStatus.EndOfMedia)

    def test_autoplay_next_sequential(self):
        from PySide6.QtMultimedia import QMediaPlayer
        ids = list(self.paths.values())
        self.controller.play_tracks(ids, 0)
        self.assertTrue(_spin(
            lambda: self.controller._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState))
        self._finish_current()
        self.assertEqual(self.controller.current_track.id, ids[1])

    def test_autoplay_stops_at_end_sequential(self):
        from PySide6.QtMultimedia import QMediaPlayer
        ids = list(self.paths.values())
        self.controller.play_tracks(ids, len(ids) - 1)
        self.assertTrue(_spin(
            lambda: self.controller._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState))
        self._finish_current()
        # 顺序播放到末尾：停止，不循环
        self.assertEqual(self.controller._player.playbackState(), QMediaPlayer.PlaybackState.StoppedState)

    def test_autoplay_loop_wraps_to_first(self):
        from PySide6.QtMultimedia import QMediaPlayer
        ids = list(self.paths.values())
        self.controller.set_mode("loop")
        self.controller.play_tracks(ids, len(ids) - 1)
        self.assertTrue(_spin(
            lambda: self.controller._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState))
        self._finish_current()
        self.assertEqual(self.controller.current_track.id, ids[0])

    def test_autoplay_single_replays_same_track(self):
        from PySide6.QtMultimedia import QMediaPlayer
        ids = list(self.paths.values())
        self.controller.set_mode("single")
        self.controller.play_tracks(ids, 1)
        self.assertTrue(_spin(
            lambda: self.controller._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState))
        self._finish_current()
        # 单曲循环：不切歌，回到开头继续播
        self.assertEqual(self.controller.current_track.id, ids[1])
        self.assertEqual(self.controller._player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
        self.assertEqual(self.controller.position_ms, 0)

    def test_autoplay_shuffle_reshuffles_and_continues(self):
        from PySide6.QtMultimedia import QMediaPlayer
        ids = list(self.paths.values())
        self.controller.set_mode("shuffle")
        self.controller.play_tracks(ids, len(ids) - 1)
        self.assertTrue(_spin(
            lambda: self.controller._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState))
        self._finish_current()
        # 随机播放播完一轮：重新洗牌后继续，不停不空（play 状态切换是异步的，需等待）
        self.assertTrue(_spin(
            lambda: self.controller._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState))
        self.assertIsNotNone(self.controller.current_track)
        self.assertIn(self.controller.current_track.id, ids)
        # 回归：重排后的队列仍是合法排列，不会出现重复曲目
        self.assertEqual(sorted(self.controller._queue.ids), sorted(ids))

    def test_manual_next_at_end_stops(self):
        from PySide6.QtMultimedia import QMediaPlayer
        ids = list(self.paths.values())
        self.controller.play_tracks(ids, len(ids) - 1)
        self.assertTrue(_spin(
            lambda: self.controller._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState))
        self.controller.next()
        self.assertEqual(self.controller._player.playbackState(), QMediaPlayer.PlaybackState.StoppedState)

    # ---------- 上一首阈值与断点跳过 ----------

    def _make_long_track(self, seconds: float = 6.0) -> str:
        """在临时目录合成一根超过「上一首」阈值(3s)的 WAV，返回曲目 id。

        共享夹具全是 2 秒短样本，seek 超过时长会被 QMediaPlayer 钳制，
        阈值分支必须用更长的样本验证。
        """
        import numpy as np
        import soundfile as sf
        from app.metadata import read_track
        path = os.path.join(self.tmp, "长音频.wav")
        rate = 44100
        t = np.linspace(0, seconds, int(seconds * rate), endpoint=False)
        pcm = (0.3 * 32767 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
        sf.write(path, pcm, rate, format="WAV")
        return self.store.add_or_update(read_track(path), path).id

    def test_previous_restarts_track_after_threshold(self):
        from PySide6.QtMultimedia import QMediaPlayer
        long_id = self._make_long_track(6.0)
        other_id = self.paths["晴天 - 周杰伦.mp3"]
        self.controller.play_tracks([long_id, other_id], 0)
        self.assertTrue(_spin(lambda: self.controller._player.mediaStatus() in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        )))
        self.controller.seek(3500)  # 超过 3s 阈值且未超时长
        self.assertEqual(self.controller.position_ms, 3500)
        self.controller.previous()
        # 只回本曲开头，不切歌
        self.assertEqual(self.controller.current_track.id, long_id)
        self.assertEqual(self.controller.position_ms, 0)

    def test_play_single_pending_seek_applied_on_load(self):
        """恢复上次播放位置：LoadedMedia 后应真正落到 seek 位置。"""
        self.controller.play_single(self.paths["晨间轻音乐.wav"], autoplay=False, seek_ms=800)
        self.assertTrue(_spin(lambda: self.controller.position_ms == 800, timeout_ms=5000))

    def test_consecutive_broken_files_are_skipped(self):
        from app.models import Track
        errors = []
        self.controller.error.connect(errors.append)
        for i in (1, 2):
            ghost_path = os.path.join(self.tmp, f"幽灵歌曲{i}.mp3")
            self.store.tracks[f"ghost{i}"] = Track(id=f"ghost{i}", path=ghost_path, title=f"幽灵歌曲{i}")
        self.controller.play_tracks(["ghost1", "ghost2", self.paths["夜曲.flac"]], 0)
        good = self.paths["夜曲.flac"]
        self.assertTrue(_spin(lambda: self.controller.current_track is not None
                              and self.controller.current_track.id == good, timeout_ms=10000))
        # 两个坏文件各报一次错，均标记 broken，最终落在好歌上
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("文件不存在" in e for e in errors))
        self.assertTrue(self.store.get_track("ghost1").broken)
        self.assertTrue(self.store.get_track("ghost2").broken)

    # ---------- v2.0：队列查询与跳转 ----------

    def test_queue_ids_and_index(self):
        ids = list(self.paths.values())
        self.controller.play_tracks(ids, 1)
        self.assertEqual(self.controller.queue_ids, ids)
        self.assertEqual(self.controller.queue_index, 1)
        self.controller.next()
        self.assertEqual(self.controller.queue_index, 2)

    def test_play_from_queue(self):
        ids = list(self.paths.values())
        self.controller.play_tracks(ids, 0)
        target = self.paths["晨间轻音乐.wav"]
        self.assertTrue(self.controller.play_from_queue(target))
        self.assertTrue(_spin(lambda: self.controller.current_track is not None
                              and self.controller.current_track.id == target))
        self.assertEqual(self.controller.queue_ids[self.controller.queue_index], target)
        # 不在队列中的 id 拒绝跳转
        from app.models import Track
        self.store.tracks["outsider"] = Track(id="outsider", path=os.path.join(self.tmp, "队外之歌.mp3"))
        self.assertFalse(self.controller.play_from_queue("outsider"))

    def test_queue_ids_empty_before_play(self):
        self.assertEqual(self.controller.queue_ids, [])
        self.assertEqual(self.controller.queue_index, -1)
        self.assertFalse(self.controller.play_from_queue("随便"))


if __name__ == "__main__":
    unittest.main()
