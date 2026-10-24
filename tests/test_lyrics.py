# -*- coding: utf-8 -*-
"""app.lyrics 单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lyrics import LyricLine, format_time, lyric_index_at, parse_lrc, parse_plain


class TestParseLrc(unittest.TestCase):
    def test_basic(self):
        lines = parse_lrc("[00:01.00]第一行\n[00:02.50]第二行")
        self.assertEqual([l.time_ms for l in lines], [1000, 2500])
        self.assertEqual([l.text for l in lines], ["第一行", "第二行"])

    def test_multiple_time_tags_one_line(self):
        lines = parse_lrc("[00:10.00][00:20.00]副歌")
        self.assertEqual(len(lines), 2)
        self.assertEqual([l.time_ms for l in lines], [10000, 20000])
        self.assertTrue(all(l.text == "副歌" for l in lines))

    def test_metadata_lines_skipped(self):
        lines = parse_lrc("[ti:标题]\n[ar:艺人]\n[00:01.00]歌词")
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].text, "歌词")

    def test_offset_applied(self):
        lines = parse_lrc("[offset:500]\n[00:01.00]提前半秒")
        self.assertEqual(lines[0].time_ms, 1500)
        lines2 = parse_lrc("[offset:-500]\n[00:01.00]推迟半秒")
        self.assertEqual(lines2[0].time_ms, 500)

    def test_offset_float_and_sign(self):
        lines = parse_lrc("[offset:-250]\n[00:02.00]x")
        self.assertEqual(lines[0].time_ms, 1750)

    def test_three_digit_minute(self):
        lines = parse_lrc("[100:30.00]长音频")
        self.assertEqual(lines[0].time_ms, 100 * 60000 + 30000)

    def test_three_digit_frac_is_milliseconds(self):
        lines = parse_lrc("[00:01.250]毫秒标签")
        self.assertEqual(lines[0].time_ms, 1250)

    def test_unsorted_input_gets_sorted(self):
        lines = parse_lrc("[00:05.00]后\n[00:01.00]先")
        self.assertEqual([l.time_ms for l in lines], [1000, 5000])

    def test_malformed_lines_ignored(self):
        text = "[00:01.00]正常\n没有时间标签\n[abc]垃圾\n[00:02.00]\n   \n[00:03.00]结尾"
        lines = parse_lrc(text)
        self.assertEqual([l.text for l in lines], ["正常", "结尾"])

    def test_empty_and_none(self):
        self.assertEqual(parse_lrc(""), [])
        self.assertEqual(parse_lrc(None), [])

    def test_crlf_and_bom(self):
        lines = parse_lrc("\ufeff[00:01.00]带BOM\r\n[00:02.00]CRLF")
        self.assertEqual([l.text for l in lines], ["带BOM", "CRLF"])

    def test_colon_in_text_kept(self):
        lines = parse_lrc("[00:01.00]时间: 12:30 的钟声")
        self.assertEqual(lines[0].text, "时间: 12:30 的钟声")


class TestLyricIndexAt(unittest.TestCase):
    def setUp(self):
        self.lines = [LyricLine(1000, "一"), LyricLine(3000, "二"), LyricLine(3000, "三"), LyricLine(5000, "四")]

    def test_before_first(self):
        self.assertEqual(lyric_index_at(self.lines, 0), -1)
        self.assertEqual(lyric_index_at(self.lines, 999), -1)

    def test_exact_and_between(self):
        self.assertEqual(lyric_index_at(self.lines, 1000), 0)
        self.assertEqual(lyric_index_at(self.lines, 2000), 0)
        self.assertEqual(lyric_index_at(self.lines, 3000), 2)  # 同行取最后一个
        self.assertEqual(lyric_index_at(self.lines, 4999), 2)

    def test_after_last(self):
        self.assertEqual(lyric_index_at(self.lines, 5000), 3)
        self.assertEqual(lyric_index_at(self.lines, 99999), 3)

    def test_empty_list(self):
        self.assertEqual(lyric_index_at([], 100), -1)


class TestPlainAndTime(unittest.TestCase):
    def test_parse_plain(self):
        self.assertEqual(parse_plain("第一行\n\n  第二行  \n"), ["第一行", "第二行"])

    def test_format_time(self):
        self.assertEqual(format_time(0), "0:00")
        self.assertEqual(format_time(1000), "0:01")
        self.assertEqual(format_time(61000), "1:01")
        self.assertEqual(format_time(3661000), "1:01:01")
        self.assertEqual(format_time(-5), "0:00")


if __name__ == "__main__":
    unittest.main()
