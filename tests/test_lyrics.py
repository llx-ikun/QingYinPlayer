# -*- coding: utf-8 -*-
"""app.lyrics 单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lyrics import (LyricLine, format_lrc, format_lrc_stamp, format_time,
                        has_cjk, is_bilingual_alternating, is_structure_marker,
                        lyric_index_at, lyrics_from_text, merge_translations,
                        pair_bilingual, parse_lrc, parse_plain, shift_lrc,
                        strip_meta_lines)


class TestParseLrc(unittest.TestCase):
    def test_basic(self):
        lines = parse_lrc("[00:01.00]第一行\n[00:02.50]第二行")
        self.assertEqual([ln.time_ms for ln in lines], [1000, 2500])
        self.assertEqual([ln.text for ln in lines], ["第一行", "第二行"])

    def test_multiple_time_tags_one_line(self):
        lines = parse_lrc("[00:10.00][00:20.00]副歌")
        self.assertEqual(len(lines), 2)
        self.assertEqual([ln.time_ms for ln in lines], [10000, 20000])
        self.assertTrue(all(ln.text == "副歌" for ln in lines))

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
        self.assertEqual([ln.time_ms for ln in lines], [1000, 5000])

    def test_malformed_lines_ignored(self):
        text = "[00:01.00]正常\n没有时间标签\n[abc]垃圾\n[00:02.00]\n   \n[00:03.00]结尾"
        lines = parse_lrc(text)
        self.assertEqual([ln.text for ln in lines], ["正常", "结尾"])

    def test_empty_and_none(self):
        self.assertEqual(parse_lrc(""), [])
        self.assertEqual(parse_lrc(None), [])

    def test_crlf_and_bom(self):
        lines = parse_lrc("\ufeff[00:01.00]带BOM\r\n[00:02.00]CRLF")
        self.assertEqual([ln.text for ln in lines], ["带BOM", "CRLF"])

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


class TestStripMetaLines(unittest.TestCase):
    """纯文本歌词开头的「歌名 + 作词/作曲/编曲」元数据块要能被剔除。"""

    def test_strips_title_and_credit_block(self):
        text = (
            "唯有追赶风的方向 (Only By Chasing the)\n"
            "作词 : 音融三喜\n"
            "作曲 : 音融三喜\n"
            "编曲 : 音融三喜\n"
            "Who can surely know\n"
            "风将吹向何方\n"
        )
        synced, plain = lyrics_from_text(text)
        self.assertEqual(synced, [])
        self.assertEqual(plain, ["Who can surely know", "风将吹向何方"])

    def test_strips_fullwidth_colon(self):
        text = "作曲：张三\n作词：李四\n第一句歌词"
        self.assertEqual(strip_meta_lines(text).splitlines(), ["第一句歌词"])

    def test_keeps_plain_lyrics_without_meta(self):
        text = "第一句\n第二句\n第三句"
        self.assertEqual(strip_meta_lines(text).splitlines(), ["第一句", "第二句", "第三句"])

    def test_first_line_not_dropped_without_meta_signal(self):
        """首行只在「后面紧跟元数据行」时才当歌名剔除；否则保留。"""
        text = "第一句歌词\n第二句歌词"
        self.assertEqual(strip_meta_lines(text).splitlines(), ["第一句歌词", "第二句歌词"])

    # ---------- v2.7.3 收紧：别再把正文当元数据删 ----------

    def test_single_meta_like_line_in_body_kept(self):
        """正文里孤零零一行「制作 : xxx」是歌词，不是元数据块。

        旧实现会把它删掉，还因为「首行后面紧跟元数据」把第一句歌词一起当歌名删，
        3 行变 1 行（探针 tools/probe_txt_lyrics.py 用例 C）。
        """
        text = "风将吹向何方\n制作 : 这是一句歌词\n我追着光"
        self.assertEqual(strip_meta_lines(text).splitlines(),
                         ["风将吹向何方", "制作 : 这是一句歌词", "我追着光"])

    def test_meta_block_must_be_consecutive(self):
        """不连续的元数据行各自孤立，都不算「块」（首行的那行见下一个用例）。"""
        text = "第一句\n作词 : 甲\n第二句\n作曲 : 乙"
        self.assertEqual(strip_meta_lines(text).splitlines(),
                         ["第一句", "作词 : 甲", "第二句", "作曲 : 乙"])

    def test_single_meta_line_at_very_first_line_stripped(self):
        """第一行就是「作词 : xxx」：单行也删——否则它会和第一句歌词配成双语。"""
        text = "作词 : 甲\nWho can surely know\n风将吹向何方"
        self.assertEqual(strip_meta_lines(text).splitlines(),
                         ["Who can surely know", "风将吹向何方"])

    def test_meta_block_beyond_head_lines_kept(self):
        """正文深处的元数据样式行不动（只看前 8 行）。"""
        body = [f"第{i}句" for i in range(1, 10)]
        text = "\n".join([*body, "制作 : 丙", "编曲 : 丁"])
        self.assertEqual(strip_meta_lines(text).splitlines(),
                         [*body, "制作 : 丙", "编曲 : 丁"])

    def test_two_line_meta_block_at_head_still_stripped(self):
        """前 8 行内连续 ≥2 行的元数据块照旧剔除（别把原能力改没了）。"""
        text = "作词 : 甲\n作曲 : 乙\n第一句\n第二句"
        self.assertEqual(strip_meta_lines(text).splitlines(), ["第一句", "第二句"])


class TestStructureMarker(unittest.TestCase):
    """v2.7.3：段落标记行 `[Verse 1]` / `(间奏)` 要有独立身份。

    它们若被当成歌词行参与双语判定，含 ASCII 的会冒充「英文原文行」，把真中文
    歌词降级成小字译文（探针用例 D：4 行被配成 2 句）。
    """

    def test_recognizes_common_markers(self):
        for line in ("[Verse 1]", "[Chorus 2]", "【副歌】", "(间奏)", "（前奏）",
                     "*intro*", "间奏", "Interlude", "[bridge]"):
            self.assertTrue(is_structure_marker(line), f"{line!r} 应判为段落标记")

    def test_bracket_numbering_and_words(self):
        self.assertTrue(is_structure_marker("[Verse 2]"))
        self.assertTrue(is_structure_marker("(Chorus)"))

    def test_real_lyrics_not_marked(self):
        for line in ("Who can surely know", "风将吹向何方", "(月亮代表我的心)",
                     "唯有追赶风的方向 (Only By Chasing the)", "第1句：开始"):
            self.assertFalse(is_structure_marker(line), f"{line!r} 不该判为段落标记")

    def test_marker_does_not_become_translation(self):
        """核心回归：标记行不能把中文歌词挤成译文。"""
        lines = ["[Verse 1]", "风将吹向何方", "[Chorus]", "我追着光"]
        pairs = pair_bilingual(lines)
        self.assertEqual(pairs, [("[Verse 1]", ""), ("风将吹向何方", ""),
                                 ("[Chorus]", ""), ("我追着光", "")])
        self.assertTrue(all(sub == "" for _main, sub in pairs))

    def test_marker_kept_while_bilingual_still_pairs(self):
        """标记行夹在双语之间：标记行原样保留，双语照旧配对。"""
        lines = ["[Verse 1]", *BILINGUAL_SAMPLE]
        pairs = pair_bilingual(lines)
        self.assertEqual(len(pairs), 5)
        self.assertEqual(pairs[0], ("[Verse 1]", ""))
        self.assertEqual(pairs[1], ("Who can surely know", "风将吹向何方"))

    def test_markers_excluded_from_bilingual_detection(self):
        """只有标记 + 中文时不该被判成双语。"""
        lines = ["[Verse 1]", "风将吹向何方", "[Chorus]", "我追着光"]
        self.assertFalse(is_bilingual_alternating(lines))

    def test_marker_between_pair_does_not_break_pairing(self):
        """标记行插在原文与译文之间也不打断配对（不吞行、不串句）。"""
        lines = ["Who can surely know", "[breathe]", "风将吹向何方",
                 "How the wind blows,", "谁也捉摸不透"]
        pairs = pair_bilingual(lines)
        self.assertIn(("Who can surely know", "风将吹向何方"), pairs)
        self.assertIn(("[breathe]", ""), pairs)
        self.assertIn(("How the wind blows,", "谁也捉摸不透"), pairs)
        self.assertEqual(len(pairs), 3)


# 双语歌词（原文行 / 译文行交替）—— 取自真实场景的形态：
# 浏览器下载的 .txt 里英文原文一行、中文译文一行。
BILINGUAL_SAMPLE = [
    "Who can surely know", "风将吹向何方",
    "How the wind blows,", "谁也捉摸不透",
    "When showers of notes", "当音符的骤雨",
    "Fall like sparkles", "如星辉般洒落",
]


class TestHasCjk(unittest.TestCase):
    def test_detects_chinese_japanese_korean(self):
        self.assertTrue(has_cjk("风将吹向何方"))
        self.assertTrue(has_cjk("あいうえお"))
        self.assertTrue(has_cjk("안녕하세요"))

    def test_latin_and_punctuation_are_not_cjk(self):
        self.assertFalse(has_cjk("Who can surely know"))
        self.assertFalse(has_cjk("(Lento, presto)"))
        self.assertFalse(has_cjk(""))
        self.assertFalse(has_cjk(None))


class TestIsBilingualAlternating(unittest.TestCase):
    def test_strict_alternation_is_bilingual(self):
        self.assertTrue(is_bilingual_alternating(BILINGUAL_SAMPLE))

    def test_pure_chinese_is_not(self):
        self.assertFalse(is_bilingual_alternating(["第一句", "第二句", "第三句", "第四句"]))

    def test_chinese_with_one_english_hook_is_not(self):
        """纯中文歌里夹一句英文副歌：不能当双语，否则会少一句、整首错位。"""
        mixed = ["第一句歌词", "第二句歌词", "Yeah yeah", "第三句歌词", "第四句歌词"]
        self.assertFalse(is_bilingual_alternating(mixed))

    def test_too_short_is_not(self):
        self.assertFalse(is_bilingual_alternating(["Who can surely know", "风将吹向何方"]))


class TestPairBilingual(unittest.TestCase):
    def test_pairs_main_with_translation(self):
        pairs = pair_bilingual(BILINGUAL_SAMPLE)
        self.assertEqual(len(pairs), 4)
        self.assertEqual(pairs[0], ("Who can surely know", "风将吹向何方"))
        self.assertEqual(pairs[-1], ("Fall like sparkles", "如星辉般洒落"))

    def test_non_bilingual_keeps_each_line(self):
        pairs = pair_bilingual(["第一句", "第二句", "第三句", "第四句"])
        self.assertEqual(len(pairs), 4)
        self.assertTrue(all(sub == "" for _main, sub in pairs))

    def test_odd_tail_becomes_single(self):
        pairs = pair_bilingual([*BILINGUAL_SAMPLE, "Woah! Keep on movin'"])
        self.assertEqual(len(pairs), 5)
        self.assertEqual(pairs[-1], ("Woah! Keep on movin'", ""))

    def test_drops_blank_lines(self):
        lines = ["", "Who can surely know", "  ", "风将吹向何方",
                 "How the wind blows,", "谁也捉摸不透"]
        pairs = pair_bilingual(lines)
        self.assertEqual(len(pairs), 2)


class TestMergeTranslations(unittest.TestCase):
    def test_same_timestamp_two_lines_merge(self):
        lines = [LyricLine(1000, "Who can surely know"), LyricLine(1000, "风将吹向何方"),
                 LyricLine(3000, "How the wind blows,")]
        merged = merge_translations(lines)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0].text, "Who can surely know")
        self.assertEqual(merged[0].translation, "风将吹向何方")
        self.assertEqual(merged[1].translation, "")

    def test_identical_text_not_merged(self):
        """副歌同一句重复两次（同时间戳）不能被吞掉一句。"""
        lines = [LyricLine(1000, "副歌"), LyricLine(1000, "副歌")]
        self.assertEqual(len(merge_translations(lines)), 2)

    def test_three_same_timestamp_only_first_pair_merges(self):
        lines = [LyricLine(1000, "a"), LyricLine(1000, "甲"), LyricLine(1000, "b")]
        self.assertEqual(len(merge_translations(lines)), 2)

    def test_keeps_existing_translation(self):
        lines = [LyricLine(1000, "a", "甲"), LyricLine(1000, "b")]
        merged = merge_translations(lines)
        self.assertEqual(merged[0].translation, "甲")
        self.assertEqual(len(merged), 2)


class TestFormatLrc(unittest.TestCase):
    def test_stamp_is_percent_seconds(self):
        self.assertEqual(format_lrc_stamp(0), "[00:00.00]")
        self.assertEqual(format_lrc_stamp(2740), "[00:02.74]")
        self.assertEqual(format_lrc_stamp(61230), "[01:01.23]")
        self.assertEqual(format_lrc_stamp(-5), "[00:00.00]")

    def test_writes_translation_on_same_timestamp(self):
        text = format_lrc([LyricLine(2740, "Who can surely know", "风将吹向何方"),
                           LyricLine(4260, "How the wind blows,")])
        self.assertEqual(text.splitlines(), [
            "[00:02.74]Who can surely know",
            "[00:02.74]风将吹向何方",
            "[00:04.26]How the wind blows,",
        ])

    def test_round_trips_through_lyrics_from_text(self):
        """写出再读回必须还原成「一句 + 译文」，否则 .lrc 落地后双语就丢了。"""
        src = [LyricLine(2740, "Who can surely know", "风将吹向何方"),
               LyricLine(4260, "How the wind blows,", "谁也捉摸不透")]
        synced, plain = lyrics_from_text(format_lrc(src))
        self.assertEqual(plain, [])
        self.assertEqual([(ln.time_ms, ln.text, ln.translation) for ln in synced],
                         [(2740, "Who can surely know", "风将吹向何方"),
                          (4260, "How the wind blows,", "谁也捉摸不透")])

    def test_empty_returns_empty_string(self):
        self.assertEqual(format_lrc([]), "")


class TestShiftLrc(unittest.TestCase):
    """整体偏移（v2.6.12）：本地对齐只能估算，前奏长会整条偏早，靠这个微调。

    只许动「行首时间标签」：正文里的方括号、元数据行、双语同时间戳两行都要正确。
    """

    def test_shift_later_moves_every_stamp(self):
        lrc = "[00:01.00]a\n[00:03.00]b\n"
        out, applied = shift_lrc(lrc, 500)
        self.assertEqual(applied, 500)
        self.assertEqual(out, "[00:01.50]a\n[00:03.50]b\n")

    def test_shift_earlier_moves_every_stamp(self):
        lrc = "[00:10.00]a\n[00:12.00]b\n"
        out, applied = shift_lrc(lrc, -500)
        self.assertEqual(applied, -500)
        self.assertEqual(out, "[00:09.50]a\n[00:11.50]b\n")

    def test_first_line_clamps_at_zero(self):
        """最早一句只有 0.3s 时再提前 0.5s，只能提 0.3s —— 否则多句糊在 0 秒。"""
        lrc = "[00:00.30]a\n[00:05.00]b\n"
        out, applied = shift_lrc(lrc, -500)
        self.assertEqual(applied, -300)
        self.assertEqual(out, "[00:00.00]a\n[00:04.70]b\n")

    def test_already_at_zero_returns_unchanged(self):
        lrc = "[00:00.00]a\n[00:05.00]b\n"
        out, applied = shift_lrc(lrc, -500)
        self.assertEqual(applied, 0)
        self.assertEqual(out, lrc)

    def test_bilingual_same_stamp_shifts_together(self):
        lrc = "[00:04.06]Who can surely know\n[00:04.06]风将吹向何方\n"
        out, _ = shift_lrc(lrc, 1000)
        self.assertEqual(out, "[00:05.06]Who can surely know\n[00:05.06]风将吹向何方\n")

    def test_text_brackets_and_metadata_untouched(self):
        lrc = "[ar:某人]\n[00:01.00][00:03.00]合唱 [第一段]\n"
        out, _ = shift_lrc(lrc, 500)
        self.assertIn("[ar:某人]", out)                 # 元数据行没有时间标签，原样保留
        self.assertIn("合唱 [第一段]", out)             # 正文方括号不碰
        self.assertIn("[00:01.50][00:03.50]", out)      # 一行多标签一起平移

    def test_hundredths_and_milliseconds_both_parse(self):
        self.assertEqual(shift_lrc("[00:01.23]a\n", 0)[0], "[00:01.23]a\n")
        out, _ = shift_lrc("[00:01.23]a\n", 1000)
        self.assertEqual(out, "[00:02.23]a\n")
        out, _ = shift_lrc("[00:01.234]a\n", 1000)      # 毫秒写法：解析认，输出仍统一百分秒
        self.assertEqual(out, "[00:02.23]a\n")

    def test_no_stamps_returns_unchanged(self):
        self.assertEqual(shift_lrc("纯文本没有时间轴\n", 500), ("纯文本没有时间轴\n", 0))
        self.assertEqual(shift_lrc("", 500), ("", 0))

    def test_trailing_newline_preserved(self):
        with_nl, _ = shift_lrc("[00:01.00]a\n", 500)
        self.assertTrue(with_nl.endswith("\n"))
        without, _ = shift_lrc("[00:01.00]a", 500)
        self.assertFalse(without.endswith("\n"))

    def test_roundtrip_restores_original(self):
        lrc = "[00:10.00]a\n[00:12.00]b\n"
        later, _ = shift_lrc(lrc, 2000)
        back, _ = shift_lrc(later, -2000)
        self.assertEqual(back, lrc)


class TestBilingualText(unittest.TestCase):
    def test_pure_text_bilingual_still_plain_list(self):
        """纯文本路径仍返回逐行列表（配对交给 pair_bilingual / 界面按句渲染）。"""
        text = "作词 : 音融三喜\n" + "\n".join(BILINGUAL_SAMPLE)
        synced, plain = lyrics_from_text(text)
        self.assertEqual(synced, [])
        self.assertEqual(len(pair_bilingual(plain)), 4)

    def test_synced_bilingual_txt_merges(self):
        text = ("[00:02.74]Who can surely know\n"
                "[00:02.74]风将吹向何方\n"
                "[00:04.26]How the wind blows,\n"
                "[00:04.26]谁也捉摸不透")
        synced, _plain = lyrics_from_text(text)
        self.assertEqual(len(synced), 2)
        self.assertEqual(synced[0].translation, "风将吹向何方")



if __name__ == "__main__":
    unittest.main()
