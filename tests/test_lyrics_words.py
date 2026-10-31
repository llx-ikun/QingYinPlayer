# -*- coding: utf-8 -*-
"""增强 LRC 逐字标签解析 + 逐字 sidecar 单测（v3.0.0）。"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import lyrics_words as lw
from app.lyrics import LyricLine, WordSpan, parse_lrc


class TestEnhancedLrcParse(unittest.TestCase):
    """`[mm:ss.xx]<mm:ss.xx>字` 形态的逐字解析。"""

    def test_word_tags_fill_spans(self):
        lines = parse_lrc("[00:12.34]<00:12.34>故<00:12.56>事<00:13.00>")
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].text, "故事", "标签要剥干净，只留正文")
        self.assertEqual(lines[0].words,
                         (WordSpan(12340, 12560, "故"), WordSpan(12560, 13000, "事")))

    def test_plain_lrc_keeps_words_empty(self):
        lines = parse_lrc("[00:12.34]故事")
        self.assertEqual(lines[0].text, "故事")
        self.assertEqual(lines[0].words, (), "普通 LRC 必须留空元组，渲染走零回归路径")

    def test_last_word_end_unknown_is_zero(self):
        lines = parse_lrc("[00:01.00]<00:01.00>我<00:01.50>爱")
        self.assertEqual(lines[0].words[-1].end_ms, 0, "末尾没有结尾戳 → 终点未知记 0")

    def test_concat_equals_line_text(self):
        raw = "[00:01.00]<00:01.00>Who <00:01.40>can <00:01.80>know"
        line = parse_lrc(raw)[0]
        self.assertEqual("".join(w.text for w in line.words), line.text,
                         "字元拼接必须与行文本逐字符相等，否则高亮切片会错位")
        self.assertEqual(line.text, "Who can know", "英文单词间的空格不能被 strip 掉")

    def test_leading_text_merges_into_first_word(self):
        line = parse_lrc("[00:05.00]前<00:05.20>奏")[0]
        self.assertEqual(line.text, "前奏")
        self.assertEqual(line.words[0].text, "前奏", "首个标签前的残留文字并入第一段")
        self.assertEqual(line.words[0].start_ms, 5200)

    def test_multiple_line_stamps_shift_words(self):
        lines = parse_lrc("[00:10.00][00:20.00]<00:10.00>故<00:10.50>事")
        self.assertEqual([line.time_ms for line in lines], [10000, 20000])
        self.assertEqual(lines[0].words[0].start_ms, 10000)
        self.assertEqual(lines[1].words[0].start_ms, 20000, "重复副歌的逐字要跟着那一遍平移")
        self.assertEqual(lines[1].words[1].start_ms, 20500)

    def test_offset_applies_to_word_spans(self):
        lines = parse_lrc("[offset:500]\n[00:01.00]<00:01.00>故")
        self.assertEqual(lines[0].time_ms, 1500)
        self.assertEqual(lines[0].words[0].start_ms, 1500)

    def test_non_time_angle_brackets_untouched(self):
        self.assertEqual(parse_lrc("[00:01.00]I <3 you")[0].text, "I <3 you")
        self.assertEqual(parse_lrc("[00:01.00]a <b> c")[0].words, (),
                         "`<b>` 不是 mm:ss 时间标签，不能被当逐字戳删掉")

    def test_tag_only_line_dropped(self):
        self.assertEqual(parse_lrc("[00:01.00]<00:01.00>"), [],
                         "整行只有标签没有正文 → 丢弃，别占一个时间槽")


class TestWordsSidecar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_lyric_words_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip(self):
        mapping = {12340: (WordSpan(12340, 12560, "故"), WordSpan(12560, 0, "事"))}
        self.assertTrue(lw.save_line_words("t1", mapping, self.tmp))
        self.assertEqual(lw.load_line_words("t1", self.tmp), mapping)

    def test_corrupt_json_returns_empty(self):
        with open(os.path.join(self.tmp, "bad.json"), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(lw.load_line_words("bad", self.tmp), {})

    def test_non_int_keys_skipped(self):
        path = os.path.join(self.tmp, "k.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"lines": {"abc": [[0, 1, "x"]], "100": [[0, 50, "x"]]}}, f)
        self.assertEqual(lw.load_line_words("k", self.tmp),
                         {100: (WordSpan(0, 50, "x"),)})

    def test_bad_spans_drop_whole_line(self):
        path = os.path.join(self.tmp, "b.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"lines": {
                "100": [[0, 50, "a"], [50, 90, ""]],      # 空文本 → 整条丢
                "200": [[0, 50, "a"], "oops"],            # 结构不对 → 整条丢
                "300": [[0, 50, "a"], [-1, 90, "b"]],     # 负起点 → 整条丢
                "400": [[0, 50, "a"]],                    # 合法
            }}, f)
        self.assertEqual(lw.load_line_words("b", self.tmp),
                         {400: (WordSpan(0, 50, "a"),)})

    def test_end_before_start_treated_as_unknown(self):
        path = os.path.join(self.tmp, "e.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"lines": {"100": [[500, 100, "a"]]}}, f)
        self.assertEqual(lw.load_line_words("e", self.tmp)[100],
                         (WordSpan(500, 0, "a"),))

    def test_empty_mapping_deletes_file(self):
        lw.save_line_words("t2", {100: (WordSpan(0, 10, "a"),)}, self.tmp)
        path = lw._path("t2", self.tmp)
        self.assertTrue(os.path.isfile(path))
        lw.clear_song_words("t2", self.tmp)
        self.assertFalse(os.path.isfile(path), "清空后应删文件，别留空壳")

    def test_safe_id_strips_illegal_chars(self):
        lw.save_line_words("../evil", {100: (WordSpan(0, 10, "a"),)}, self.tmp)
        names = os.listdir(self.tmp)
        self.assertEqual(len(names), 1)
        self.assertNotIn("..", names[0])
        self.assertEqual(lw.load_line_words("../evil", self.tmp),
                         {100: (WordSpan(0, 10, "a"),)})

    def test_save_from_lines_only_picks_words(self):
        lines = [LyricLine(1000, "故事", words=(WordSpan(1000, 1500, "故事"),)),
                 LyricLine(3000, "没有逐字")]
        self.assertTrue(lw.save_from_lines("t3", lines, self.tmp))
        self.assertEqual(lw.load_line_words("t3", self.tmp),
                         {1000: (WordSpan(1000, 1500, "故事"),)})


class TestAttachWords(unittest.TestCase):
    def test_attach_by_time_and_text(self):
        lines = [LyricLine(1000, "故事"), LyricLine(3000, "后来")]
        mapping = {1000: (WordSpan(1000, 1500, "故"), WordSpan(1500, 0, "事"))}
        out = lw.attach_words(lines, mapping)
        self.assertEqual(out[0].words, mapping[1000])
        self.assertEqual(out[1].words, (), "没收录的行保持空元组")

    def test_input_not_mutated(self):
        lines = [LyricLine(1000, "故事")]
        mapping = {1000: (WordSpan(1000, 1500, "故事"),)}
        lw.attach_words(lines, mapping)
        self.assertEqual(lines[0].words, (), "不得原地改入参（缓存里的歌词会被污染）")

    def test_text_mismatch_drops_only_that_line(self):
        lines = [LyricLine(1000, "故事啊"), LyricLine(3000, "后来")]
        mapping = {1000: (WordSpan(1000, 1500, "故事"),),      # 文本对不上
                   3000: (WordSpan(3000, 3500, "后来"),)}
        out = lw.attach_words(lines, mapping)
        self.assertEqual(out[0].words, (), "时间戳撞上但文本不同 → 该行丢弃")
        self.assertEqual(out[1].words, mapping[3000], "其他行不受影响")

    def test_empty_mapping_returns_copy(self):
        lines = [LyricLine(1000, "故事")]
        out = lw.attach_words(lines, {})
        self.assertEqual(out, lines)
        self.assertIsNot(out, lines)

    def test_apply_track_words_roundtrip(self):
        tmp = tempfile.mkdtemp(prefix="qy_lyric_words_apply_")
        try:
            lines = [LyricLine(1000, "故事", "story")]
            lw.save_from_lines("t4", [LyricLine(1000, "故事",
                                                words=(WordSpan(1000, 1500, "故事"),))], tmp)
            out = lw.apply_track_words(lines, "t4", tmp)
            self.assertEqual(out[0].words, (WordSpan(1000, 1500, "故事"),))
            self.assertEqual(out[0].translation, "story", "译文不能丢")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
