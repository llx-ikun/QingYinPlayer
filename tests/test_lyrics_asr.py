# -*- coding: utf-8 -*-
"""AI 强制对齐的纯逻辑单测（v3.0.0，不加载模型、不碰音频）。

覆盖 L1 的向量化 RMS、L3 序列比对、L4 能量谷吸附、L5 置信度自检与逐行装配。
模型推理（L2）由 `tools/probe_asr.py` 与打包 smoke 覆盖，这里不碰——
只有「纯函数对了」这件事能在 CI 里被反复验证，模型每次都跑一遍不现实。
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import lyrics_asr as la
from app.lyrics import LyricLine, WordSpan


def _w(start, end, text, prob=0.9):
    return la.RecognizedWord(start, end, text, prob)


class TestNormalize(unittest.TestCase):
    def test_lines_strip_punctuation_and_keep_index(self):
        lines = [LyricLine(0, "故事的小黄花，"), LyricLine(2000, "从出生那年就飘着")]
        norm, pos = la.normalize_lines(lines)
        self.assertEqual(norm, "故事的小黄花从出生那年就飘着")
        self.assertEqual(pos[0], (0, 0))
        # 第一行正文 6 个字（「故事的小黄花」），逗号在原文下标 6 上被丢掉
        self.assertEqual(pos[5], (0, 5), "标点被丢掉后仍要回到原文位置")
        self.assertEqual(pos[6], (1, 0), "下一行的第一个字下标从 0 重新开始")

    def test_lines_lowercase_latin(self):
        norm, _pos = la.normalize_lines([LyricLine(0, "Who Can Know")])
        self.assertEqual(norm, "whocanknow")

    def test_recognized_expands_word_to_chars(self):
        norm, spans, probs = la.normalize_recognized([_w(0, 500, " 故事"), _w(500, 900, "谁")])
        self.assertEqual(norm, "故事谁")
        self.assertEqual(spans[0], (0, 500))
        self.assertEqual(spans[1], (0, 500), "同一个词里的字先共享窗口")
        self.assertEqual(len(probs), 3)


class TestMatch(unittest.TestCase):
    def test_exact_match_maps_windows(self):
        lines = [LyricLine(0, "故事"), LyricLine(1000, "后来")]
        outcome = la.align_lyrics(lines, [_w(0, 400, "故事"), _w(1000, 1400, "后来")])
        self.assertTrue(outcome.ok, outcome.detail)
        self.assertEqual(outcome.matched_ratio, 1.0)
        first = outcome.lines[0].words
        self.assertEqual(len(first), 2)
        self.assertEqual("".join(w.text for w in first), "故事")
        self.assertEqual((first[0].start_ms, first[1].start_ms), (0, 200),
                         "同一个词的两个字按均分拆开，不能同时亮")

    def test_misheard_word_still_matches_rest(self):
        """whisper 听错一个字（「黄」→「苦」）不该毁掉整句对齐。

        「故事的小黄花」= 6 个字；识别出「故事 / 的 / 小苦 / 花」= 6 个字，
        其中「黄→苦」对不上 → 匹配率 5/6，仍然远高于 0.55 的门槛。
        """
        lines = [LyricLine(0, "故事的小黄花")]
        recog = [_w(0, 1000, "故事"), _w(1000, 1200, "的"), _w(1200, 1600, "小苦"),
                 _w(1600, 2400, "花")]
        outcome = la.align_lyrics(lines, recog)
        self.assertTrue(outcome.ok, outcome.detail)
        self.assertAlmostEqual(outcome.matched_ratio, 5 / 6, places=3)
        words = outcome.lines[0].words
        self.assertEqual("".join(w.text for w in words), "故事的小黄花",
                         "听错字也得保证字元拼回整行原文")
        self.assertEqual(len(words), 6, "每个字一个时间窗（错字由邻居插值补上）")

    def test_truncated_recognition_still_aligned(self):
        """只识别出前半句：后半句用邻居外推补上，不能留空洞。"""
        lines = [LyricLine(0, "故事的小黄花")]
        outcome = la.align_lyrics(lines, [_w(0, 400, "故事"), _w(400, 800, "的小")])
        self.assertTrue(outcome.ok, outcome.detail)
        self.assertEqual(len(outcome.lines[0].words), 6)
        self.assertGreaterEqual(outcome.lines[0].words[-1].start_ms, 800,
                                "补出来的字要接在后面，不能比已识别的部分还早")

    def test_windows_monotonic_after_fill(self):
        lines = [LyricLine(0, "一二三四五")]
        # 4/5 的字对得上（匹配率 0.8 过关），中间那个字靠插值补
        outcome = la.align_lyrics(lines, [_w(0, 200, "一"), _w(200, 400, "二"),
                                          _w(400, 600, "三"), _w(1000, 1200, "五")])
        starts = [w.start_ms for w in outcome.lines[0].words]
        self.assertEqual(starts, sorted(starts), "时间必须单调不减，否则渲染层会拒收")
        self.assertEqual(starts[0], 0)
        self.assertEqual(starts[-1], 1000)


class TestConfidence(unittest.TestCase):
    def test_low_match_ratio_rejected(self):
        """唱的内容和歌词对不上（如识别成外语）→ 不产出，lines 原样返回。"""
        lines = [LyricLine(0, "故事的小黄花从出生那年就飘着")]
        recog = [_w(0, 500, "totally"), _w(500, 900, "different")]
        outcome = la.align_lyrics(lines, recog)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error, "low_confidence")
        self.assertEqual(outcome.lines[0].words, (), "失败时绝不能写入半对的时间轴")

    def test_low_probability_rejected(self):
        """Phase 0 实测：无语音合成音会被"听"出内容，但 probability 只有 0.03~0.12。"""
        lines = [LyricLine(0, "故事的小黄花")]
        recog = [_w(0, 1000, "故事的小黄花", 0.05)]
        outcome = la.align_lyrics(lines, recog)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.error, "low_confidence")

    def test_empty_inputs(self):
        self.assertEqual(la.align_lyrics([], [_w(0, 100, "a")]).error, "no_lyrics")
        self.assertEqual(la.align_lyrics([LyricLine(0, "")], []).error, "no_lyrics")
        self.assertEqual(la.align_lyrics([LyricLine(0, "故事")], []).error, "no_speech")

    def test_thresholds_are_overridable(self):
        """门槛可调（批量对齐时给用户「放宽」选项用）。"""
        lines = [LyricLine(0, "故事的小黄花")]
        recog = [_w(0, 500, "故事", 0.1)]
        self.assertFalse(la.align_lyrics(lines, recog).ok)
        relaxed = la.align_lyrics(lines, recog, min_match_ratio=0.0, min_mean_prob=0.0)
        self.assertTrue(relaxed.ok, relaxed.detail)


class TestSnap(unittest.TestCase):
    def test_boundary_moves_to_energy_valley(self):
        """边界附近有一个能量极小点（换气口），应该吸过去。"""
        # hop 10ms，共 100 帧 = 1000ms；在 300ms 处造一个低谷
        rms = [1.0] * 100
        rms[30] = 0.01
        windows = [(0, 350), (350, 600)]
        snapped = la.snap_to_energy(windows, rms, hop_ms=10, snap_ms=120)
        self.assertEqual(snapped[0][1], 300, "边界从 350 吸到谷底 300")
        self.assertEqual(snapped[1][0], 300, "相邻字的起点必须跟着一起改")

    def test_no_snap_without_rms(self):
        windows = [(0, 350), (350, 600)]
        self.assertEqual(la.snap_to_energy(windows, []), windows)

    def test_min_char_guard(self):
        """吸附不许把字压得比 MIN_CHAR_MS 更短。"""
        rms = [1.0] * 100
        rms[1] = 0.0
        windows = [(0, 350), (350, 400)]
        snapped = la.snap_to_energy(windows, rms, hop_ms=10, snap_ms=400,
                                    min_char_ms=40)
        self.assertGreaterEqual(snapped[0][1] - snapped[0][0], 40,
                                "边界不能吸到把第一个字挤没")

    def test_single_window_untouched(self):
        self.assertEqual(la.snap_to_energy([(0, 100)], [1.0] * 50), [(0, 100)])


class TestRmsFast(unittest.TestCase):
    def test_matches_pure_python_version(self):
        """向量化 RMS 必须与现成的 `rms_envelope` 同口径。"""
        from array import array

        from app.lyrics_local_align import rms_envelope

        samples = array("f", [0.5 * ((i % 37) - 18) / 18.0 for i in range(8000)])
        fast = la.rms_fast(samples, 1000, frame_ms=20, hop_ms=10)
        slow = rms_envelope(samples, 1000, frame_ms=20, hop_ms=10)
        self.assertEqual(len(fast), len(slow), "帧数必须一致")
        for a, b in zip(fast, slow, strict=True):
            self.assertAlmostEqual(a, b, places=6)

    def test_degenerate_inputs(self):
        self.assertEqual(la.rms_fast([], 16000), [])
        self.assertEqual(la.rms_fast([0.1, 0.2], 16000), [], "样本不够一帧就返回空")


class TestBuildLineWords(unittest.TestCase):
    def test_punctuation_absorbed_keeps_text_equal(self):
        """标点没有时间窗，必须并进相邻字元，否则拼不回整行原文。"""
        lines = [LyricLine(0, "故事，小黄花")]
        norm, pos = la.normalize_lines(lines)
        windows = [(i * 100, i * 100 + 100) for i in range(len(norm))]
        blocks = la.build_line_words(lines, pos, windows)
        words = blocks[0]
        self.assertEqual("".join(w.text for w in words), "故事，小黄花")
        self.assertEqual(len(words), len(norm), "6 个字 → 6 个时间窗（标点不算一个）")

    def test_line_without_any_window_stays_empty(self):
        lines = [LyricLine(0, "故事"), LyricLine(1000, "后来")]
        _norm, pos = la.normalize_lines(lines)
        windows = [(0, 100), (100, 200), None, None]
        blocks = la.build_line_words(lines, pos, windows)
        self.assertEqual(blocks[0], (WordSpan(0, 100, "故"), WordSpan(100, 200, "事")))
        self.assertEqual(blocks[1], (), "没有时间窗的行留空元组 → 渲染走线性插值")


class TestRetime(unittest.TestCase):
    """`retime_lines`：用对齐出的首字时刻重打行时间轴（行级 6.04s → <0.5s）。"""

    def test_line_time_from_first_word(self):
        lines = [LyricLine(0, "故事"), LyricLine(2000, "后来")]
        recog = [_w(5800, 6200, "故事"), _w(7000, 7600, "后来")]
        outcome = la.align_lyrics(lines, recog)
        self.assertTrue(outcome.ok, outcome.detail)
        self.assertEqual(outcome.max_shift_ms, 5800, "最大偏差要如实报出来")
        shifted = la.retime_lines(outcome.lines)
        self.assertEqual([line.time_ms for line in shifted], [5800, 7000])
        self.assertEqual(shifted[0].words, outcome.lines[0].words, "逐字数据要跟着搬过去")

    def test_lines_without_words_keep_time(self):
        lines = [LyricLine(1000, "一句"), LyricLine(5000, "没有逐字")]
        out = la.retime_lines(lines)
        self.assertEqual([line.time_ms for line in out], [1000, 5000])

    def test_monotonic_with_min_gap(self):
        """两行算出来的时刻太近（识别抖动）要拉开，否则高亮会跳。"""
        lines = [LyricLine(0, "一句"), LyricLine(0, "二句")]
        lines[0].words = (WordSpan(1000, 1500, "一句"),)
        lines[1].words = (WordSpan(1010, 1600, "二句"),)
        out = la.retime_lines(lines, min_gap_ms=120)
        self.assertEqual([line.time_ms for line in out], [1000, 1120])

    def test_empty_input(self):
        self.assertEqual(la.retime_lines([]), [])


class TestAlignTrackDegrade(unittest.TestCase):
    """端到端入口在缺依赖时只能返回错误码，不能抛异常。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_asr_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_model_dir(self):
        outcome = la.transcribe("whatever.mp3", os.path.join(self.tmp, "nope"))
        self.assertEqual(outcome.error, "model_missing")
        self.assertTrue(outcome.detail)

    def test_bad_audio_returns_decode_failed(self):
        bad = os.path.join(self.tmp, "bad.mp3")
        with open(bad, "wb") as f:
            f.write(b"not audio at all")
        outcome = la.align_track(bad, [LyricLine(0, "故事")], self.tmp)
        self.assertIn(outcome.error, ("decode_failed", "model_missing"))
        self.assertEqual(outcome.lines[0].words, ())

    def test_describe_error_has_chinese_text(self):
        for code in ("no_lyrics", "no_speech", "model_missing", "low_confidence"):
            self.assertTrue(la.describe_error(code))
        self.assertEqual(la.describe_error("unknown_code"), "unknown_code")


if __name__ == "__main__":
    unittest.main()
