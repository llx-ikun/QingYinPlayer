# -*- coding: utf-8 -*-
"""同名 .lrc 落地：写入歌曲同目录同名 .lrc（本地近似对齐复用它落盘）。

说明：v2.7.0 移除了联网精确对齐（LyricTimestamps，上传音频做强制对齐、需自备 Key），
本文件只保留 sidecar 写盘的用例。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lyrics_align import sidecar_lrc_path, write_sidecar_lrc

LRC_OK = "[00:01.00]第一句歌词\n[00:05.00]第二句歌词"


def _tmp_audio(content: bytes = b"fake-mp3-bytes", suffix: str = ".mp3") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, content)
    os.close(fd)
    return path


class TestSidecarLrc(unittest.TestCase):
    def test_path_strips_extension(self):
        self.assertEqual(sidecar_lrc_path("/music/晴天.mp3"), "/music/晴天.lrc")
        self.assertEqual(sidecar_lrc_path("/music/晴天.flac"), "/music/晴天.lrc")

    def test_write_creates_file(self):
        audio = _tmp_audio()
        try:
            path = write_sidecar_lrc(audio, LRC_OK)
            self.assertEqual(path, sidecar_lrc_path(audio))
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), LRC_OK)
        finally:
            os.remove(sidecar_lrc_path(audio))
            os.remove(audio)

    def test_write_overwrites_existing(self):
        audio = _tmp_audio()
        sidecar = sidecar_lrc_path(audio)
        try:
            with open(sidecar, "w", encoding="utf-8") as f:
                f.write("旧内容")
            write_sidecar_lrc(audio, LRC_OK)
            with open(sidecar, encoding="utf-8") as f:
                self.assertEqual(f.read(), LRC_OK)
        finally:
            os.remove(sidecar)
            os.remove(audio)

    def test_write_failure_returns_none(self):
        audio = _tmp_audio()
        try:
            with mock.patch("app.lyrics_align.open", side_effect=OSError("readonly")):
                self.assertIsNone(write_sidecar_lrc(audio, LRC_OK))
        finally:
            os.remove(audio)

    def test_write_empty_returns_none(self):
        self.assertIsNone(write_sidecar_lrc("", LRC_OK))
        self.assertIsNone(write_sidecar_lrc(_tmp_audio(), ""))


if __name__ == "__main__":
    unittest.main()
