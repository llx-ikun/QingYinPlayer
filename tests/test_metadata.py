# -*- coding: utf-8 -*-
"""app.metadata 单元测试（基于合成夹具）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.make_fixtures import ensure_fixtures

from app.lyrics import lyrics_from_text
from app.metadata import read_track

MUSIC_DIR = ensure_fixtures()


class TestMetadata(unittest.TestCase):
    def test_mp3_with_id3(self):
        meta = read_track(os.path.join(MUSIC_DIR, "晴天 - 周杰伦.mp3"))
        self.assertIsNotNone(meta)
        self.assertEqual(meta.title, "晴天")
        self.assertEqual(meta.artist, "周杰伦")
        self.assertEqual(meta.album, "叶惠美")
        self.assertEqual(meta.fmt, "mp3")
        self.assertGreater(meta.duration_ms, 1500)
        self.assertIsNotNone(meta.picture)
        self.assertTrue(meta.picture.startswith(b"\x89PNG"))
        self.assertIn("内嵌纯文本歌词", meta.lyrics_text)
        synced, plain = lyrics_from_text(meta.lyrics_text)
        self.assertEqual(synced, [])
        self.assertEqual(len(plain), 2)

    def test_flac(self):
        meta = read_track(os.path.join(MUSIC_DIR, "夜曲.flac"))
        self.assertEqual(meta.title, "夜曲")
        self.assertEqual(meta.artist, "周杰伦")
        self.assertEqual(meta.fmt, "flac")
        self.assertIsNotNone(meta.picture)
        synced, _plain = lyrics_from_text(meta.lyrics_text)
        self.assertEqual(len(synced), 2)  # FLAC 内嵌的是带时间戳的歌词
        self.assertEqual(synced[0].text, "FLAC 内嵌歌词第一行")

    def test_wav_id3_chunk(self):
        meta = read_track(os.path.join(MUSIC_DIR, "晨间轻音乐.wav"))
        self.assertEqual(meta.title, "晨间轻音乐")
        self.assertEqual(meta.artist, "测试艺术家")
        self.assertEqual(meta.fmt, "wav")

    def test_ogg(self):
        meta = read_track(os.path.join(MUSIC_DIR, "海浪的声音.ogg"))
        self.assertEqual(meta.title, "海浪的声音")
        self.assertEqual(meta.artist, "自然白噪音")
        self.assertEqual(meta.fmt, "ogg")

    def test_bare_mp3_falls_back_to_filename(self):
        meta = read_track(os.path.join(MUSIC_DIR, "无标签音频.mp3"))
        self.assertEqual(meta.title, "无标签音频")
        self.assertEqual(meta.artist, "未知艺人")
        self.assertIsNone(meta.picture)
        self.assertGreater(meta.duration_ms, 1500)

    def test_missing_file_returns_none(self):
        self.assertIsNone(read_track(os.path.join(MUSIC_DIR, "不存在的文件.mp3")))

    def test_lrc_file_not_audio(self):
        # .lrc 不是音频，mutagen.File 返回 None -> 走 MP3 强读分支也失败 -> 回退文件名
        meta = read_track(os.path.join(MUSIC_DIR, "晴天 - 周杰伦.lrc"))
        self.assertIsNotNone(meta)
        self.assertEqual(meta.title, "晴天 - 周杰伦")
        self.assertEqual(meta.duration_ms, 0)


if __name__ == "__main__":
    unittest.main()
