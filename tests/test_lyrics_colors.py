# -*- coding: utf-8 -*-
"""逐曲歌词颜色 sidecar 单测（v2.9.0）。"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import lyrics_colors as lc


class TestLineColorsSidecar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_lyric_colors_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip(self):
        lc.set_line_color("track1", 1200, "#FF6B9D", self.tmp)
        lc.set_line_color("track1", 45000, "#7f7bff", self.tmp)
        self.assertEqual(lc.load_line_colors("track1", self.tmp),
                         {1200: "#ff6b9d", 45000: "#7f7bff"},
                         "读回要归一成小写 #rrggbb")

    def test_set_overwrites_and_clears(self):
        lc.set_line_color("t", 1000, "#111111", self.tmp)
        lc.set_line_color("t", 1000, "#222222", self.tmp)
        self.assertEqual(lc.load_line_colors("t", self.tmp), {1000: "#222222"})
        lc.clear_line_color("t", 1000, self.tmp)
        self.assertEqual(lc.load_line_colors("t", self.tmp), {})

    def test_invalid_color_is_ignored(self):
        lc.set_line_color("t", 1000, "red", self.tmp)      # 非 #rrggbb
        lc.set_line_color("t", 1000, "#fff", self.tmp)     # 三位简写不收
        self.assertEqual(lc.load_line_colors("t", self.tmp), {})

    def test_corrupt_json_returns_empty(self):
        path = os.path.join(self.tmp, "bad.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(lc.load_line_colors("bad", self.tmp), {})

    def test_non_int_keys_skipped(self):
        path = os.path.join(self.tmp, "k.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"lines": {"abc": "#123456", "100": "#abcdef"}}, f)
        self.assertEqual(lc.load_line_colors("k", self.tmp), {100: "#abcdef"})

    def test_empty_mapping_deletes_file(self):
        lc.set_line_color("t", 1000, "#123456", self.tmp)
        path = lc._path("t", self.tmp)
        self.assertTrue(os.path.isfile(path))
        lc.clear_song_colors("t", self.tmp)
        self.assertFalse(os.path.isfile(path), "清空后应删文件，别留空壳")

    def test_safe_id_strips_illegal_chars(self):
        lc.set_line_color("../evil", 1000, "#123456", self.tmp)
        names = os.listdir(self.tmp)
        self.assertEqual(len(names), 1)
        self.assertNotIn("/", names[0])
        self.assertNotIn("..", names[0])
        # 仍然能按原 id 读回（过滤规则一致）
        self.assertEqual(lc.load_line_colors("../evil", self.tmp), {1000: "#123456"})


if __name__ == "__main__":
    unittest.main()
