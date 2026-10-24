# -*- coding: utf-8 -*-
"""app.covers / app.scanner 测试（offscreen 环境，需要 QApplication）。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.make_fixtures import ensure_fixtures

MUSIC_DIR = ensure_fixtures()


def setUpModule():
    from PySide6.QtWidgets import QApplication
    global _app
    _app = QApplication.instance() or QApplication(sys.argv[:1])


class TestCollectAudioFiles(unittest.TestCase):
    def test_folder_scan(self):
        from app.scanner import collect_audio_files
        files = collect_audio_files([MUSIC_DIR])
        names = {os.path.basename(f) for f in files}
        self.assertEqual(names, {
            "晨间轻音乐.wav",
            "夜曲.flac",
            "无标签音频.mp3",
            "晴天 - 周杰伦.mp3",
            "海浪的声音.ogg",
        })
        self.assertEqual(len(files), 5)

    def test_dedupe_and_direct_file(self):
        from app.scanner import collect_audio_files
        one = os.path.join(MUSIC_DIR, "夜曲.flac")
        files = collect_audio_files([MUSIC_DIR, MUSIC_DIR, one])
        self.assertEqual(len(files), 5)

    def test_skip_non_audio(self):
        from app.scanner import collect_audio_files
        self.assertEqual(collect_audio_files([os.path.join(MUSIC_DIR, "晴天 - 周杰伦.lrc")]), [])


class TestScannerWorker(unittest.TestCase):
    def test_worker_emits_metas(self):
        from PySide6.QtCore import QEventLoop, QTimer
        from app.scanner import ScannerWorker

        worker = ScannerWorker([MUSIC_DIR])
        metas = []
        worker.track_ready.connect(metas.append)
        result = {}

        def on_finished(n):
            result["n"] = n
            loop.quit()

        worker.finished_ok.connect(on_finished)
        loop = QEventLoop()
        QTimer.singleShot(15000, loop.quit)
        worker.start()
        loop.exec()
        worker.wait(2000)
        self.assertEqual(result.get("n"), 5)
        self.assertEqual(len(metas), 5)
        titles = sorted(m.title for m in metas)
        self.assertIn("晴天", titles)
        self.assertIn("无标签音频", titles)


class TestCoverProvider(unittest.TestCase):
    def setUp(self):
        self.covers_dir = tempfile.mkdtemp(prefix="qy_covers_")

    def _track(self, name):
        from app.models import Track, make_track_id
        path = os.path.join(MUSIC_DIR, name)
        return Track(id=make_track_id(path), path=path)

    def test_embedded_cover_cached(self):
        from app.covers import CoverProvider
        provider = CoverProvider(self.covers_dir)
        track = self._track("晴天 - 周杰伦.mp3")
        pixmap = provider.get_pixmap(track, 48, 6)
        self.assertFalse(pixmap.isNull())
        self.assertEqual(pixmap.width(), 48)
        # 磁盘缓存已写入
        self.assertTrue(os.path.isfile(os.path.join(self.covers_dir, f"{track.id}.png")))
        # 二次读取命中缓存（同对象）
        self.assertIs(provider.get_pixmap(track, 48, 6), pixmap)

    def test_placeholder_when_no_cover(self):
        from app.covers import CoverProvider
        provider = CoverProvider(self.covers_dir)
        track = self._track("无标签音频.mp3")
        pixmap = provider.get_pixmap(track, 64, 0)
        self.assertFalse(pixmap.isNull())
        self.assertEqual(pixmap.width(), 64)
        # 无封面不写磁盘缓存
        self.assertFalse(os.path.isfile(os.path.join(self.covers_dir, f"{track.id}.png")))

    def test_missing_file_placeholder(self):
        from app.covers import CoverProvider
        from app.models import Track
        provider = CoverProvider(self.covers_dir)
        track = Track(id="deadbeefdeadbeef", path=os.path.join(MUSIC_DIR, "不存在.mp3"))
        self.assertFalse(provider.get_pixmap(track, 48).isNull())


if __name__ == "__main__":
    unittest.main()
