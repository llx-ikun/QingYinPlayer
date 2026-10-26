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


class TestFixtureIsolation(unittest.TestCase):
    """用户专属目录 `tests/fixtures/我的音乐` 不得被合成夹具污染。

    用户明确要求：该目录只能放他本人提供的音乐，不得生成、下载或混入其他音乐。
    此前 `ensure_fixtures()` 直接往里面写 6 个合成文件，导致
    ① 每次跑测试该目录都被塞满；
    ② 应用导入过这些路径后，夹具被清理时库里留下失效条目（「晴天」）。
    现在合成产物统一落在 `_generated/` 子目录，本组用例锁住该约束。
    """

    def setUp(self):
        from tests.make_fixtures import FIXTURES, GENERATED

        self.fixtures_root = FIXTURES
        self.generated = GENERATED
        self.user_dir = os.path.join(FIXTURES, "我的音乐")

    def test_generated_audio_is_not_inside_user_dir(self):
        self.assertTrue(
            os.path.abspath(MUSIC_DIR).startswith(os.path.abspath(self.generated) + os.sep),
            f"合成夹具应位于 _generated/ 下，实际为 {MUSIC_DIR}",
        )

    def test_user_dir_stays_empty_after_ensure(self):
        # 再调一次（幂等路径）也不得往用户目录写东西
        ensure_fixtures()
        self.assertTrue(os.path.isdir(self.user_dir), "用户目录应保留（即使为空）")
        self.assertEqual(
            os.listdir(self.user_dir), [], "用户专属目录必须为空，不得混入合成夹具"
        )

    def test_generated_audio_files_all_exist(self):
        names = sorted(os.listdir(MUSIC_DIR))
        self.assertEqual(len(names), 6, f"合成夹具应为 6 个文件，实际 {names}")


if __name__ == "__main__":
    unittest.main()
