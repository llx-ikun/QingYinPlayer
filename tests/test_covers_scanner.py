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

    def _make_tree(self):
        """构造一棵包含系统目录/隐藏目录/非音频文件的临时目录树。"""
        root = tempfile.mkdtemp(prefix="qy_scan_tree_")
        for skip in (".git", "node_modules", "__pycache__", ".hidden",
                     "System Volume Information", "$RECYCLE.BIN"):
            d = os.path.join(root, skip)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "藏在里面的歌.mp3"), "wb") as f:
                f.write(b"\x00")
        normal = os.path.join(root, "正常子目录")
        os.makedirs(normal, exist_ok=True)
        with open(os.path.join(normal, "正常歌曲.flac"), "wb") as f:
            f.write(b"\x00")
        for junk in ("readme.txt", "cover.jpg", "歌词.lrc"):
            with open(os.path.join(root, junk), "wb") as f:
                f.write(b"\x00")
        return root

    def test_skip_system_and_hidden_dirs(self):
        from app.scanner import collect_audio_files
        files = collect_audio_files([self._make_tree()])
        names = [os.path.basename(f) for f in files]
        self.assertEqual(names, ["正常歌曲.flac"])

    def test_case_insensitive_extensions(self):
        from app.scanner import collect_audio_files
        root = tempfile.mkdtemp(prefix="qy_scan_case_")
        for name in ("大写.MP3", "混合.Flac", "小写.wav"):
            with open(os.path.join(root, name), "wb") as f:
                f.write(b"\x00")
        files = collect_audio_files([root])
        self.assertEqual(sorted(os.path.basename(f) for f in files),
                         ["大写.MP3", "小写.wav", "混合.Flac"])

    def test_empty_and_missing_paths(self):
        from app.scanner import collect_audio_files
        self.assertEqual(collect_audio_files([]), [])
        self.assertEqual(collect_audio_files([""]), [])
        self.assertEqual(collect_audio_files([os.path.join(tempfile.gettempdir(), "不存在的目录xyz")]), [])

    def test_output_is_sorted(self):
        from app.scanner import collect_audio_files
        files = collect_audio_files([MUSIC_DIR, MUSIC_DIR])
        self.assertEqual(files, sorted(files))


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

    def test_cancel_stops_before_finish(self):
        from PySide6.QtCore import QEventLoop, QTimer
        from app.scanner import ScannerWorker

        worker = ScannerWorker([MUSIC_DIR])
        # 收到第一首就取消：保证取消发生在后续文件检查之前，结果确定
        worker.track_ready.connect(lambda m: worker.cancel())
        outcome = {}
        worker.cancelled.connect(lambda: outcome.update(cancelled=True))
        worker.finished_ok.connect(lambda n: outcome.update(finished=n))
        loop = QEventLoop()
        worker.cancelled.connect(loop.quit)
        worker.finished_ok.connect(loop.quit)
        QTimer.singleShot(15000, loop.quit)
        worker.start()
        loop.exec()
        worker.wait(2000)
        self.assertTrue(outcome.get("cancelled"), "取消后应发出 cancelled 信号")
        self.assertNotIn("finished", outcome, "取消后不应再发出 finished_ok")

    def test_unparsable_file_falls_back_to_filename(self):
        """无法解析的音频以「文件名/未知艺人」兜底入库，不阻断整次导入。"""
        from PySide6.QtCore import QEventLoop, QTimer
        from app.scanner import ScannerWorker

        tmp = tempfile.mkdtemp(prefix="qy_scan_bad_")
        bad = os.path.join(tmp, "损坏的文件.mp3")
        with open(bad, "wb") as f:
            f.write(b"this is definitely not audio")
        worker = ScannerWorker([bad, os.path.join(MUSIC_DIR, "夜曲.flac")])
        metas = []
        worker.track_ready.connect(metas.append)
        progress = []
        worker.progress.connect(lambda d, t: progress.append((d, t)))
        result = {}
        worker.finished_ok.connect(lambda n: result.update(n=n))
        loop = QEventLoop()
        worker.finished_ok.connect(loop.quit)
        QTimer.singleShot(15000, loop.quit)
        worker.start()
        loop.exec()
        worker.wait(2000)
        # 总数按文件数计（含坏文件），坏文件以兜底元数据发出
        self.assertEqual(result.get("n"), 2)
        self.assertEqual(len(metas), 2)
        bad_meta = next(m for m in metas if m.path == bad)
        self.assertEqual(bad_meta.title, "损坏的文件")
        self.assertEqual(bad_meta.artist, "未知艺人")
        self.assertEqual(bad_meta.duration_ms, 0)
        # 进度最终到达 (2, 2)
        self.assertEqual(progress[-1], (2, 2))


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

    # ---------- v2.2.1：内存缓存按像素预算 LRU，避免无上限增长 ----------

    def test_mem_cache_bounded_by_pixels(self):
        from app.covers import CoverProvider
        from app.models import Track
        provider = CoverProvider(self.covers_dir, max_pixels=2000)  # 40px 图=1600px
        for i in range(20):
            provider.get_pixmap(Track(id=f"t{i:04x}", path=""), 40, 6)
        # 1600px/张 × 20 张 = 32000px，被 2000px 预算压到 2 张以内
        self.assertLessEqual(len(provider._mem), 2)
        self.assertLessEqual(provider._mem.pixels, 2000 + 1600)

    def test_lru_evicts_least_recently_used(self):
        from app.covers import CoverProvider
        from app.models import Track
        provider = CoverProvider(self.covers_dir, max_pixels=2000)
        provider.get_pixmap(Track(id="aaaa", path=""), 40, 6)
        provider.get_pixmap(Track(id="bbbb", path=""), 40, 6)  # 挤掉 aaaa
        self.assertNotIn(("aaaa", 40, 6), provider._mem._items)
        self.assertIn(("bbbb", 40, 6), provider._mem._items)

    def test_lru_hit_marks_recent(self):
        from app.covers import CoverProvider
        from app.models import Track
        provider = CoverProvider(self.covers_dir, max_pixels=2000)
        provider.get_pixmap(Track(id="aaaa", path=""), 40, 6)
        provider.get_pixmap(Track(id="bbbb", path=""), 40, 6)  # aaaa 被淘汰
        provider.get_pixmap(Track(id="aaaa", path=""), 40, 6)  # 重读 aaaa → bbbb 被淘汰
        self.assertIn(("aaaa", 40, 6), provider._mem._items)
        self.assertNotIn(("bbbb", 40, 6), provider._mem._items)

    def test_oversized_pixmap_still_returned(self):
        from app.covers import CoverProvider
        from app.models import Track
        provider = CoverProvider(self.covers_dir, max_pixels=2000)
        # 单张 200px = 40000px 远超预算，仍应返回有效图且不抛
        pixmap = provider.get_pixmap(Track(id="big", path=""), 200, 0)
        self.assertFalse(pixmap.isNull())
        self.assertEqual(pixmap.width(), 200)


if __name__ == "__main__":
    unittest.main()
