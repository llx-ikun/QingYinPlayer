# -*- coding: utf-8 -*-
"""受管理曲库（v2.1.9）：导入即复制 / 同内容去重 / 同名冲突 / 非法字符 / 扫描器落库。

背景：v2.1.8 及以前，导入只把**原文件绝对路径**写进 data.json；用户挪动或删除
原文件后曲目就变「失效」。v2.1.9 改成导入时把文件复制进
`%APPDATA%/轻音播放器/library/`，曲目与源文件解耦。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.library import file_signature, import_into_library, is_in_library, safe_stem
from tests.make_fixtures import ensure_fixtures

MUSIC_DIR = ensure_fixtures()


def setUpModule():
    # QThread + QEventLoop 需要事件分发器，否则 loop.exec() 会一直挂着
    from PySide6.QtWidgets import QApplication
    global _app
    _app = QApplication.instance() or QApplication(sys.argv[:1])


class TestImportIntoLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_lib_")
        self.src_dir = os.path.join(self.tmp, "src")
        self.lib = os.path.join(self.tmp, "library")
        os.makedirs(self.src_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make(self, name: str, data: bytes, sub: str = "") -> str:
        folder = os.path.join(self.src_dir, sub) if sub else self.src_dir
        os.makedirs(folder, exist_ok=True)
        p = os.path.join(folder, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def test_copies_file_into_library(self):
        src = self._make("晴天.mp3", b"abc123")
        dest, copied = import_into_library(src, self.lib)
        self.assertTrue(copied)
        self.assertTrue(os.path.isfile(dest))
        self.assertTrue(is_in_library(dest, self.lib))
        self.assertEqual(os.path.basename(dest), "晴天.mp3")
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), b"abc123")
        # 复制而非移动：原文件仍在
        self.assertTrue(os.path.isfile(src))

    def test_same_content_is_deduped(self):
        src = self._make("歌.mp3", b"same-bytes")
        d1, c1 = import_into_library(src, self.lib)
        d2, c2 = import_into_library(src, self.lib)
        self.assertTrue(c1)
        self.assertFalse(c2, "同内容第二次不应再复制")
        self.assertEqual(d1, d2)
        self.assertEqual(len(os.listdir(self.lib)), 1)

    def test_same_name_diff_content_not_overwritten(self):
        a = self._make("同名.mp3", b"content-A")
        b = self._make("同名.mp3", b"content-B", sub="other")
        da, ca = import_into_library(a, self.lib)
        db, cb = import_into_library(b, self.lib)
        self.assertNotEqual(da, db, "同名不同内容必须落到不同文件")
        self.assertTrue(ca and cb)
        self.assertEqual(len(os.listdir(self.lib)), 2)
        contents = set()
        for name in os.listdir(self.lib):
            with open(os.path.join(self.lib, name), "rb") as f:
                contents.add(f.read())
        self.assertEqual(contents, {b"content-A", b"content-B"})

    def test_no_partial_file_left_behind(self):
        src = self._make("留不留.mp3", b"payload")
        import_into_library(src, self.lib)
        leftovers = [n for n in os.listdir(self.lib) if n.endswith(".part")]
        self.assertEqual(leftovers, [])

    def test_sidecar_lrc_copied(self):
        """同名 .lrc 必须跟着媒体一起进曲库，否则自动歌词失效（e2e 抓到的回归）。"""
        src = self._make("带歌词.mp3", b"audio-bytes")
        with open(os.path.join(self.src_dir, "带歌词.lrc"), "w", encoding="utf-8") as f:
            f.write("[00:01.00]第一行\n")
        dest, copied = import_into_library(src, self.lib)
        self.assertTrue(copied)
        lrc = os.path.splitext(dest)[0] + ".lrc"
        self.assertTrue(os.path.isfile(lrc), "同名 .lrc 应一并复制进曲库")
        with open(lrc, encoding="utf-8") as f:
            self.assertIn("第一行", f.read())

    def test_existing_lrc_not_overwritten(self):
        """曲库里已有的歌词不被再次导入覆盖（可能是用户手动换过的）。"""
        src = self._make("有词.mp3", b"audio")
        with open(os.path.join(self.src_dir, "有词.lrc"), "w", encoding="utf-8") as f:
            f.write("[00:01.00]源歌词\n")
        dest, _ = import_into_library(src, self.lib)
        target = os.path.splitext(dest)[0] + ".lrc"
        with open(target, "w", encoding="utf-8") as f:
            f.write("[00:01.00]用户改过的歌词\n")
        import_into_library(src, self.lib)      # 同内容 → 复用
        with open(target, encoding="utf-8") as f:
            self.assertIn("用户改过", f.read())

    def test_safe_stem_strips_illegal_chars(self):
        out = safe_stem('bad:name?*"<>|')
        for ch in '<>:"/\\|?*':
            self.assertNotIn(ch, out)
        self.assertTrue(out)
        self.assertEqual(safe_stem("   "), "track")

    def test_signature_stable_and_discriminating(self):
        a = self._make("a.bin", b"1" * 100)
        b = self._make("b.bin", b"1" * 100)
        c = self._make("c.bin", b"2" * 100)
        self.assertEqual(file_signature(a), file_signature(b))   # 内容相同 → 指纹相同
        self.assertNotEqual(file_signature(a), file_signature(c))  # 内容不同 → 指纹不同

    def test_is_in_library(self):
        self.assertTrue(is_in_library(os.path.join(self.lib, "x.mp3"), self.lib))
        self.assertFalse(is_in_library(os.path.join(self.tmp, "x.mp3"), self.lib))
        self.assertFalse(is_in_library("", self.lib))


class TestScannerCopiesIntoLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_libscan_")
        self.lib = os.path.join(self.tmp, "library")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scanner_places_copies_in_library(self):
        from PySide6.QtCore import QEventLoop, QTimer

        from app.scanner import ScannerWorker

        worker = ScannerWorker([MUSIC_DIR], library_dir=self.lib)
        metas, done = [], {}

        def on_finished(n):
            done["n"] = n
            loop.quit()

        worker.track_ready.connect(metas.append)
        worker.finished_ok.connect(on_finished)
        loop = QEventLoop()
        QTimer.singleShot(20000, loop.quit)
        worker.start()
        loop.exec()
        worker.wait(3000)

        self.assertTrue(metas, "应至少解析出一首")
        for m in metas:
            self.assertTrue(is_in_library(m.path, self.lib), f"未落进曲库: {m.path}")
            self.assertTrue(os.path.isfile(m.path), f"曲库副本不存在: {m.path}")
        self.assertGreaterEqual(worker.copied, 1)
        self.assertEqual(worker.failed, 0)

    def test_scanner_without_library_keeps_original_path(self):
        """不传 library_dir 时维持旧行为（单测/外部脚本按老语义调用）。"""
        from PySide6.QtCore import QEventLoop, QTimer

        from app.scanner import ScannerWorker

        worker = ScannerWorker([MUSIC_DIR])      # 不传 library_dir
        metas, done = [], {}

        def on_finished(n):
            done["n"] = n
            loop.quit()

        worker.track_ready.connect(metas.append)
        worker.finished_ok.connect(on_finished)
        loop = QEventLoop()
        QTimer.singleShot(20000, loop.quit)
        worker.start()
        loop.exec()
        worker.wait(3000)

        self.assertTrue(metas)
        for m in metas:
            self.assertFalse(is_in_library(m.path, self.lib))


if __name__ == "__main__":
    unittest.main()
