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


class TestOnsetEnvelope(unittest.TestCase):
    """onset 强度包络（v3.0.3）：半波整流的短时能量增量，抓音节起音的上升沿。"""

    def test_rise_produces_peak_then_decays(self):
        # 前 5 帧稳态 0.1，后 5 帧升到 0.9；diff 20ms / hop 10ms → lookback=2
        rms = [0.1] * 5 + [0.9] * 5
        onset = la.onset_envelope(rms, hop_ms=10, diff_ms=20)
        self.assertEqual(len(onset), len(rms))
        self.assertGreater(onset[5], 0.0, "能量上升沿要出一个正峰")
        self.assertEqual(onset[7], 0.0, "升到位后稳态，onset 应回 0")

    def test_decay_is_clipped_to_zero(self):
        # 一路衰减：半波整流后不允许出现负值（那是「下降沿」，不是起音）
        onset = la.onset_envelope([0.9, 0.7, 0.5, 0.3, 0.1], hop_ms=10, diff_ms=20)
        self.assertEqual([round(v, 6) for v in onset], [0.0] * 5)

    def test_empty_rms(self):
        self.assertEqual(la.onset_envelope([]), [])

    def test_rms_shorter_than_lookback(self):
        """包络短于 lookback 帧时不得在 numpy 路径里炸形状。"""
        onset = la.onset_envelope([0.1, 0.2], hop_ms=10, diff_ms=30)
        self.assertEqual(len(onset), 2)
        self.assertGreaterEqual(onset[1], 0.0, "第二帧相对首帧上升，应是正 onset")


class TestSnapToOnset(unittest.TestCase):
    """字边界吸附到 onset 峰（v3.0.3），与 RMS 谷吸附互补。"""

    def test_boundary_moves_to_onset_peak(self):
        # onset 在 300ms 处有个峰，边界 350 应吸到 300
        onset = [0.0] * 100
        onset[30] = 1.0
        windows = [(0, 350), (350, 600)]
        snapped = la.snap_to_onset(windows, onset, hop_ms=10, snap_ms=120)
        self.assertEqual(snapped[0][1], 300, "边界从 350 吸到 onset 峰 300")
        self.assertEqual(snapped[1][0], 300, "相邻字的起点必须跟着一起改")

    def test_flat_onset_does_not_move(self):
        """onset 全 0（稳态/静音）时，守卫必须拦住，不能把边界随机挪到扫描端点。"""
        windows = [(0, 350), (350, 600)]
        self.assertEqual(la.snap_to_onset(windows, [0.0] * 100, hop_ms=10),
                         windows)

    def test_no_onset_returns_unchanged(self):
        windows = [(0, 350), (350, 600)]
        self.assertEqual(la.snap_to_onset(windows, []), windows)

    def test_min_char_guard(self):
        """吸附不许把字压得比 MIN_CHAR_MS 更短。"""
        onset = [0.0] * 100
        onset[1] = 1.0                      # 峰在 10ms，但 lo 被 min_char 抬到 40
        windows = [(0, 350), (350, 400)]
        snapped = la.snap_to_onset(windows, onset, hop_ms=10, snap_ms=400,
                                   min_char_ms=40)
        self.assertGreaterEqual(snapped[0][1] - snapped[0][0], 40)

    def test_single_window_untouched(self):
        self.assertEqual(la.snap_to_onset([(0, 100)], [1.0] * 50), [(0, 100)])


class TestGuessLanguage(unittest.TestCase):
    """按歌词汉字占比猜识别语言（v3.0.3），解决英文歌被识别成中文乱码。"""

    def test_chinese(self):
        self.assertEqual(la.guess_language([LyricLine(0, "故事的小黄花")]), "zh")

    def test_english(self):
        self.assertEqual(la.guess_language([LyricLine(0, "Who can know")]), "en")

    def test_mixed_more_chinese(self):
        self.assertEqual(la.guess_language([LyricLine(0, "你好世界 hi")]), "zh")

    def test_mixed_more_latin(self):
        self.assertEqual(la.guess_language([LyricLine(0, "hello 世界")]), "en")

    def test_punctuation_only_falls_back_to_zh(self):
        self.assertEqual(la.guess_language([LyricLine(0, "…——")]), "zh")

    def test_empty_lines_falls_back_to_zh(self):
        self.assertEqual(la.guess_language([]), "zh")


class TestOnsetInAlign(unittest.TestCase):
    """`align_lyrics` 收到 onset 时，字边界要真的被峰吸附（v3.0.3）。"""

    def test_uniform_spread_then_snapped_to_onset(self):
        # 「故事」两字被识别成一个词 (0,600)：均分得边界 300，onset 峰在 200 → 吸到 200
        lines = [LyricLine(0, "故事")]
        onset = [0.0] * 100
        onset[20] = 1.0                      # 200ms 处一个起音峰
        outcome = la.align_lyrics(lines, [_w(0, 600, "故事")], onset=onset)
        self.assertTrue(outcome.ok, outcome.detail)
        words = outcome.lines[0].words
        self.assertEqual("".join(w.text for w in words), "故事")
        self.assertEqual(words[0].start_ms, 0)
        self.assertEqual(words[1].start_ms, 200, "第二字起点应吸到 onset 峰而非均分的 300")

    def test_without_onset_still_uniform(self):
        # 不给 onset 时行为不变：仍按均分 300（零回归）
        lines = [LyricLine(0, "故事")]
        outcome = la.align_lyrics(lines, [_w(0, 600, "故事")])
        self.assertEqual(outcome.lines[0].words[1].start_ms, 300)


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


class _FakeResponse:
    """够 urllib.request.urlopen 返回值的形状：status / headers.get / read / with。"""

    def __init__(self, body: bytes, status: int = 200, length=None, chunks=None):
        self._body = body
        self._chunks = list(chunks) if chunks is not None else None
        self.status = status
        self.headers = {"Content-Length": str(len(body) if length is None else length)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size: int = -1) -> bytes:
        if self._chunks is not None:
            return self._chunks.pop(0) if self._chunks else b""
        body, self._body = self._body, b""     # 只给一次，第二次必须是 EOF
        return body


class _FakeServer:
    """按脚本依次返回响应或抛异常的假 urlopen，同时记下每次请求头。"""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        action = self.script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action

    def header(self, name, index=0):
        return self.requests[index].get_header(name) or self.requests[index].headers.get(name)

    def startswith(self, name, index=0):
        for key, value in self.requests[index].headers.items():
            if key.lower() == name.lower():
                return value
        return None


class TestDownloadFile(unittest.TestCase):
    """模型下载（v3.0.1）：换成标准库直连之后，每条失败路径都要能说清楚原因。

    这个模块原来用 huggingface_hub，异常被它自己的包装层吃掉，用户在真实环境里
    只看到「检查网络」。下载器重写后**错误分类就是产品行为**，必须钉死。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_dl_")
        self.dest = os.path.join(self.tmp, "model.bin")
        self._real_urlopen = la.urllib.request.urlopen

    def tearDown(self):
        la.urllib.request.urlopen = self._real_urlopen
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _serve(self, *script):
        server = _FakeServer(*script)
        la.urllib.request.urlopen = server
        return server

    def _read_dest(self):
        with open(self.dest, "rb") as f:
            return f.read()

    def test_success_writes_file_and_reports_progress(self):
        seen = []
        server = self._serve(_FakeResponse(b"abcdefgh"))
        code, detail = la.download_file("http://x/model.bin", self.dest, seen.append)
        self.assertEqual((code, detail), ("", ""))
        self.assertEqual(self._read_dest(), b"abcdefgh")
        self.assertEqual(seen[-1], 1.0, "进度要走到 100%")
        self.assertFalse(os.path.exists(self.dest + ".part"), "成功后不该留 .part")
        self.assertEqual(len(server.requests), 1)

    def test_partial_progress_is_monotonic(self):
        seen = []
        self._serve(_FakeResponse(b"", length=8, chunks=[b"abcd", b"efgh"]))
        la.download_file("http://x/model.bin", self.dest, seen.append)
        self.assertEqual(seen, [0.5, 1.0])

    def test_resume_sends_range_header(self):
        with open(self.dest + ".part", "wb") as f:
            f.write(b"abcd")
        server = self._serve(_FakeResponse(b"efgh", status=206))
        code, _detail = la.download_file("http://x/model.bin", self.dest)
        self.assertEqual(code, "")
        self.assertEqual(self._read_dest(), b"abcdefgh", "续传要接在已有字节后面")
        self.assertEqual(server.startswith("Range"), "bytes=4-")

    def test_server_ignoring_range_restarts_clean(self):
        """服务端不认 Range 时会回 200 + 整个文件，此时绝不能append成双倍长度。"""
        with open(self.dest + ".part", "wb") as f:
            f.write(b"abcd")
        self._serve(_FakeResponse(b"abcdefgh", status=200))
        code, _detail = la.download_file("http://x/model.bin", self.dest)
        self.assertEqual(code, "")
        self.assertEqual(self._read_dest(), b"abcdefgh")

    def test_http_404_stops_immediately(self):
        err = la.urllib.error.HTTPError("http://x", 404, "Not Found", {}, None)
        server = self._serve(err)
        code, detail = la.download_file("http://x/model.bin", self.dest)
        self.assertEqual(code, "download_failed")
        self.assertIn("404", detail)
        self.assertEqual(len(server.requests), 1, "4xx 重试没有意义，必须立刻收手")

    def test_retry_after_transient_network_error(self):
        server = self._serve(la.urllib.error.URLError("连接被重置"),
                             _FakeResponse(b"ok"))
        code, _detail = la.download_file("http://x/model.bin", self.dest)
        self.assertEqual(code, "")
        self.assertEqual(len(server.requests), 2)
        self.assertEqual(self._read_dest(), b"ok")

    def test_all_retries_fail_keeps_reason(self):
        errs = [la.urllib.error.URLError("超时")] * la._DOWNLOAD_RETRIES
        self._serve(*errs)
        code, detail = la.download_file("http://x/model.bin", self.dest)
        self.assertEqual(code, "download_failed")
        self.assertIn("超时", detail, "详情必须带出真实原因，不能只剩一个错误码")

    def test_truncated_body_detected(self):
        """Content-Length 说 8 字节、实际只给 4 字节：必须当失败，不能落盘半个模型。"""
        self._serve(*[_FakeResponse(b"abcd", length=8)] * la._DOWNLOAD_RETRIES)
        code, detail = la.download_file("http://x/model.bin", self.dest)
        self.assertEqual(code, "download_failed")
        self.assertIn("不完整", detail)
        self.assertFalse(os.path.exists(self.dest))

    def test_disk_error_not_retried(self):
        calls = []

        def _boom(path, append):
            calls.append(path)
            raise la._DiskError("OSError: 磁盘已满")

        real_open = la._open_part
        la._open_part = _boom
        try:
            self._serve(*[_FakeResponse(b"data")] * la._DOWNLOAD_RETRIES)
            code, detail = la.download_file("http://x/model.bin", self.dest)
        finally:
            la._open_part = real_open
        self.assertEqual(code, "disk_failed")
        self.assertIn("磁盘已满", detail)
        self.assertEqual(len(calls), 1, "磁盘写不进去重试也没有用")

    def test_416_discards_bad_part(self):
        """断点比服务器上的文件还长（.part 是坏片段）时要丢掉重来。"""
        with open(self.dest + ".part", "wb") as f:
            f.write(b"x" * 99)
        err = la.urllib.error.HTTPError("http://x", 416, "Range Not Satisfiable", {}, None)
        self._serve(err, _FakeResponse(b"abcdefgh", status=200))
        code, _detail = la.download_file("http://x/model.bin", self.dest)
        self.assertEqual(code, "")
        self.assertEqual(self._read_dest(), b"abcdefgh")


class TestEnsureModel(unittest.TestCase):
    """ensure_model 的契约：`(目录, 错误码, 详情)`，详情永远是真实原因。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_model_")
        self._real_dir_for = la.model_dir_for
        self._real_download = la.download_file
        la.model_dir_for = lambda name: os.path.join(self.tmp, name)

    def tearDown(self):
        la.model_dir_for = self._real_dir_for
        la.download_file = self._real_download
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_ready(self, name="base"):
        target = os.path.join(self.tmp, name)
        os.makedirs(target, exist_ok=True)
        for file_name in la._MODEL_FILES:
            with open(os.path.join(target, file_name), "wb") as f:
                f.write(b"x")

    def test_ready_model_does_not_touch_network(self):
        self._make_ready()

        def _boom(*_a, **_k):
            raise AssertionError("模型已就绪时不许联网")

        la.download_file = _boom
        target, code, detail = la.ensure_model("base")
        self.assertEqual((code, detail), ("", ""))
        self.assertTrue(la.model_ready(target))

    def test_unknown_tier(self):
        _target, code, detail = la.ensure_model("huge")
        self.assertEqual(code, "model_missing")
        self.assertIn("huge", detail)

    def test_downloads_all_files_with_progress(self):
        seen = []
        la.download_file = lambda url, dest, cb=None, stop=None: ("", "")
        _target, code, _detail = la.ensure_model("tiny", lambda s, f: seen.append(f))
        # download_file 是假的，文件不会真的落地 → 最后一步要能识别出来
        self.assertEqual(code, "download_failed")
        self.assertIn("不完整", _detail)
        self.assertEqual(seen[-1], 1.0)

    def test_failure_carries_file_name_and_reason(self):
        la.download_file = lambda url, dest, cb=None, stop=None: (
            "download_failed", "HTTP 503 Busy")
        _target, code, detail = la.ensure_model("tiny")
        self.assertEqual(code, "download_failed")
        self.assertIn("HTTP 503", detail)
        self.assertIn(la._MODEL_FILES[0], detail, "要指明是哪个文件失败")

    def test_url_uses_repo_and_endpoint(self):
        seen = []

        def _fake(url, dest, cb=None, stop=None):
            seen.append(url)
            return ("", "")

        os.environ["QY_HF_ENDPOINT"] = "https://mirror.example/"
        la.download_file = _fake
        try:
            la.ensure_model("base")
        finally:
            os.environ.pop("QY_HF_ENDPOINT", None)
        self.assertEqual(len(seen), len(la._MODEL_FILES))
        self.assertTrue(seen[0].startswith(
            "https://mirror.example/Systran/faster-whisper-base/resolve/main/"), seen[0])
        self.assertTrue(seen[0].endswith(la._MODEL_FILES[0]))

    def test_default_endpoint_used_without_env(self):
        saved = {key: os.environ.pop(key, None)
                 for key in ("QY_HF_ENDPOINT", "HF_ENDPOINT")}
        try:
            self.assertEqual(la.download_endpoint(), la.DEFAULT_ENDPOINT)
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value

    def test_disk_error_making_dir(self):
        la.model_dir_for = lambda name: os.path.join(self.tmp, "ro", "deep", name)
        real_makedirs = os.makedirs

        def _boom(*_a, **_k):
            raise OSError("拒绝访问")

        os.makedirs = _boom
        try:
            _target, code, detail = la.ensure_model("base")
        finally:
            os.makedirs = real_makedirs
        self.assertEqual(code, "disk_failed")
        self.assertIn("拒绝访问", detail)


class TestInterruption(unittest.TestCase):
    """「停止」要能在中途生效（v3.0.2）。

    原来是只翻一个标志位、worker 照跑不误，用户点了停止等几分钟没反应，窗口又关不掉
    —— 就是「批量对齐关不了」那个 bug。这里钉住三处：下载、识别、worker 的传导。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_int_")
        self._real_urlopen = la.urllib.request.urlopen
        self._real_dir_for = la.model_dir_for

    def tearDown(self):
        la.urllib.request.urlopen = self._real_urlopen
        la.model_dir_for = self._real_dir_for
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_download_stops_at_first_chunk_checkpoint(self):
        server = _FakeServer(_FakeResponse(b"abcdefgh"))
        la.urllib.request.urlopen = server
        dest = os.path.join(self.tmp, "m.bin")
        code, detail = la.download_file("http://x/m.bin", dest, None, lambda: True)
        self.assertEqual(code, "cancelled", "取消要和失败分开，否则批量里会记成失败")
        self.assertEqual(detail, la.describe_error("cancelled"))
        self.assertEqual(len(server.requests), 1, "取消了就别重试")
        self.assertFalse(os.path.exists(dest))

    def test_ensure_model_cancelled_before_any_download(self):
        la.model_dir_for = lambda name: os.path.join(self.tmp, name)
        la.download_file = lambda *a, **k: ("", "")   # 不该被调用
        try:
            _target, code, _detail = la.ensure_model("tiny", None, lambda: True)
        finally:
            del la.download_file
        self.assertEqual(code, "cancelled")

    def test_worker_hands_probe_to_align_track(self):
        """worker 必须把 `isInterruptionRequested` 作为谓词传进去，而不是只传个布尔。"""
        from unittest import mock

        from app.lyrics import LyricLine

        seen = {}

        def _fake_align(path, lines, model_dir, language="zh", progress=None,
                        interrupted=None, beam_size=5):
            seen["probe"] = interrupted
            return la.AlignOutcome(lines=[], matched_ratio=1.0)

        with mock.patch.object(la, "ensure_model", lambda *a, **k: ("/model", "", "")), \
                mock.patch.object(la, "align_track", _fake_align), \
                mock.patch.object(la, "save_from_lines", lambda *a, **k: None):
            worker = la.LyricsAsrWorker("t1", "/a.mp3", [LyricLine(0, "一句")], "base")
            finished = []
            worker.done.connect(lambda tid, _out: finished.append(tid))
            worker.run()

        self.assertEqual(finished, ["t1"])
        probe = seen["probe"]
        self.assertTrue(callable(probe), "要传谓词，让推理循环自己问")
        # 必须是 worker 自己的 `isInterruptionRequested`：换成别的「总是 False」的
        # lambda 也能让测试过，但停止就废了。注：QThread 未 start() 时
        # requestInterruption() 会被 Qt 忽略，所以这里断言身份而不是实测翻转。
        self.assertIs(getattr(probe, "__self__", None), worker)
        self.assertEqual(getattr(probe, "__name__", ""), "isInterruptionRequested")
        self.assertFalse(probe())

    def test_progress_signal_carries_track_id(self):
        """`progress` 必须是 `(track_id, percent, stage)` 三个参数（v3.0.2）。

        v3.0.0 声明成 `Signal(int, str)`，而主窗口和批量对话框的槽都按三个参数写，
        于是每次推送都抛 TypeError；windowed 产物 stderr 为 None，异常完全不可见，
        表现就是「进度条一直 0%、没有阶段文字」。
        """
        from unittest import mock

        from app.lyrics import LyricLine

        seen = []

        def _fake_ensure(name, progress=None, interrupted=None):
            progress("download", 0.5)
            return ("/model", "cancelled", "")

        with mock.patch.object(la, "ensure_model", _fake_ensure):
            worker = la.LyricsAsrWorker("t1", "/a.mp3", [LyricLine(0, "一句")], "base")
            worker.progress.connect(lambda tid, pct, stage: seen.append((tid, pct, stage)))
            worker.run()
        self.assertEqual(seen, [("t1", 50, "下载 AI 模型")],
                         "槽按 (track_id, percent, stage) 收，签名必须对上")

    def test_align_track_does_not_duplicate_error_text(self):
        """`detail` 里别再塞一遍中文提示，否则界面会显示「xxx（xxx）」。"""
        from unittest import mock

        from app.lyrics import LyricLine

        audio = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "fixtures", "_generated", "我的音乐", "晴天 - 周杰伦.mp3")
        if not os.path.isfile(audio):
            self.skipTest("夹具音频缺失")
        with mock.patch.object(la, "transcribe",
                               lambda *a, **k: la.AsrOutcome(error="no_speech")):
            outcome = la.align_track(audio, [LyricLine(0, "一句")], "/model")
        self.assertEqual(outcome.error, "no_speech")
        self.assertEqual(outcome.detail, "")


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
