# -*- coding: utf-8 -*-
"""歌词批量导入的文件名匹配：归一化 / 曲目键 / 匹配与歧义（纯逻辑）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lyrics_import import match_lrc_files, normalize_key, track_keys
from app.models import Track, make_track_id


def _track(path: str, title: str = "", artist: str = "") -> Track:
    return Track(id=make_track_id(path), path=path, title=title, artist=artist)


class TestNormalize(unittest.TestCase):
    def test_lowercases_and_strips_noise(self):
        self.assertEqual(normalize_key("晴天 - 周杰伦"), "晴天周杰伦")
        self.assertEqual(normalize_key("Count On Me (Live)"), "countonmelive")
        self.assertEqual(normalize_key("  Hello,  World!  "), "helloworld")

    def test_empty(self):
        self.assertEqual(normalize_key(""), "")
        self.assertEqual(normalize_key("---"), "")


class TestTrackKeys(unittest.TestCase):
    def test_builds_filename_title_artist_and_combos(self):
        t = _track("/music/晴天.mp3", title="晴天", artist="周杰伦")
        keys = track_keys(t)
        self.assertIn("晴天", keys)                 # 文件名与标题
        self.assertIn("周杰伦", keys)               # 艺人
        self.assertIn("晴天周杰伦", keys)           # 标题+艺人
        self.assertIn("周杰伦晴天", keys)           # 艺人+标题
        # 去重：文件名与标题都是「晴天」，只留一个
        self.assertEqual(len(keys), len(set(keys)))

    def test_no_duplicate_combos(self):
        t = _track("/music/晴天.mp3", title="晴天", artist="晴天")
        keys = track_keys(t)
        self.assertEqual(len(keys), len(set(keys)))


class TestMatch(unittest.TestCase):
    def test_matches_by_audio_basename(self):
        t = _track("/music/晴天.mp3", title="晴天", artist="周杰伦")
        matched, unmatched = match_lrc_files(["/lr/晴天.lrc"], [t])
        self.assertEqual(list(matched.values()), [t])
        self.assertEqual(unmatched, [])

    def test_matches_by_title(self):
        t = _track("/music/01 - 晴天.mp3", title="晴天", artist="周杰伦")
        # 歌词文件名只有「晴天」，靠标题认上
        matched, _ = match_lrc_files(["/lr/晴天.lrc"], [t])
        self.assertEqual(list(matched.values()), [t])

    def test_matches_by_title_artist_combo(self):
        t = _track("/music/xyz.mp3", title="晴天", artist="周杰伦")
        matched, _ = match_lrc_files(["/lr/周杰伦 - 晴天.lrc"], [t])
        self.assertEqual(list(matched.values()), [t])

    def test_ambiguous_key_is_skipped(self):
        a = _track("/a/晴天.mp3", title="晴天", artist="甲")
        b = _track("/b/晴天.mp3", title="晴天", artist="乙")
        # 两首都叫「晴天」，仅凭文件名区分不出 → 跳过
        matched, unmatched = match_lrc_files(["/lr/晴天.lrc"], [a, b])
        self.assertEqual(matched, {})
        self.assertEqual(unmatched, ["/lr/晴天.lrc"])

    def test_no_hit_goes_unmatched(self):
        t = _track("/music/晴天.mp3", title="晴天", artist="周杰伦")
        matched, unmatched = match_lrc_files(["/lr/完全无关.lrc"], [t])
        self.assertEqual(matched, {})
        self.assertEqual(unmatched, ["/lr/完全无关.lrc"])

    def test_multiple_files_partial_match(self):
        t = _track("/music/晴天.mp3", title="晴天", artist="周杰伦")
        matched, unmatched = match_lrc_files(
            ["/lr/晴天.lrc", "/lr/其他.lrc"], [t])
        self.assertEqual(list(matched.values()), [t])
        self.assertEqual(unmatched, ["/lr/其他.lrc"])

    def test_empty_key_is_skipped(self):
        t = _track("/music/晴天.mp3", title="晴天", artist="周杰伦")
        matched, unmatched = match_lrc_files(["/lr/.lrc"], [t])
        self.assertEqual(matched, {})
        self.assertEqual(unmatched, ["/lr/.lrc"])

    def test_matches_txt_extension_too(self):
        """v2.6.5：.txt 歌词文件按文件名同样能匹配（只取去扩展名的 basename）。"""
        t = _track("/music/晴天.mp3", title="晴天", artist="周杰伦")
        matched, unmatched = match_lrc_files(["/lr/晴天.txt"], [t])
        self.assertEqual(list(matched.values()), [t])
        self.assertEqual(unmatched, [])


if __name__ == "__main__":
    unittest.main()
