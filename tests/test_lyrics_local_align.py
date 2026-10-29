# -*- coding: utf-8 -*-
"""本地歌词对齐：解码 / 能量包络 / 静音检测 / 时间戳分配 / LRC 生成 / 后台线程。

设计要点：合成音频用标准库 `wave` 生成（正弦波 + 静音），不引入额外依赖。
静音检测的验证靠「前奏/间奏/尾奏都是静音、歌词行不该铺在这些地方」这条可断言的性质。
"""
import math
import os
import struct
import sys
import tempfile
import unittest
import wave
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lyrics import parse_lrc
from app.lyrics_local_align import (
    LyricsLocalAlignWorker,
    align_local,
    assign_timestamps,
    decode_mono,
    detect_speech,
    rms_envelope,
)


def setUpModule():
    from PySide6.QtWidgets import QApplication
    global _app
    _app = QApplication.instance() or QApplication(sys.argv[:1])


def _write_wav(path: str, segments: list[tuple[int, int]], sr: int = 16000) -> None:
    """写单声道 16bit WAV。`segments` 是 `[(时长ms, 频率Hz)]`，频率 0 表示静音。"""
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for dur_ms, freq in segments:
            n = sr * dur_ms // 1000
            for i in range(n):
                v = int(0.5 * 32767 * math.sin(2 * math.pi * freq * i / sr)) if freq else 0
                frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def _speech_tone_wav(path: str) -> None:
    """前奏 500ms 静音 → 1000ms 音 → 500ms 静音 → 1000ms 音 → 尾奏 500ms 静音。"""
    _write_wav(path, [(500, 0), (1000, 440), (500, 0), (1000, 880), (500, 0)])


class TestDecode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_local_align_")
        self.wav = os.path.join(self.tmp, "tone.wav")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_decodes_to_mono_16k(self):
        _write_wav(self.wav, [(2000, 440)])
        samples, sr = decode_mono(self.wav)
        self.assertEqual(sr, 16000)
        self.assertAlmostEqual(len(samples), 16000 * 2, delta=160)

    def test_decodes_chinese_path(self):
        """miniaudio.decode_file 对中文路径会失败，必须走 bytes 解码绕开。"""
        wav_cn = os.path.join(self.tmp, "我的音乐 测试.wav")
        _write_wav(wav_cn, [(1000, 440)])
        samples, _sr = decode_mono(wav_cn)
        self.assertGreater(len(samples), 0)


class TestRmsEnvelope(unittest.TestCase):
    def test_silence_is_zero_and_tone_is_loud(self):
        import tempfile
        import shutil
        tmp = tempfile.mkdtemp(prefix="qy_rms_")
        wav = os.path.join(tmp, "mix.wav")
        _write_wav(wav, [(1000, 0), (1000, 440)])
        samples, sr = decode_mono(wav)
        rms = rms_envelope(samples, sr)
        half = len(rms) // 2
        # 前半段静音 RMS 接近 0，后半段有声 RMS 明显更大
        self.assertLess(max(rms[:half]), 0.001)
        self.assertGreater(max(rms[half:]), 0.1)
        shutil.rmtree(tmp, ignore_errors=True)


class TestDetectSpeech(unittest.TestCase):
    def _rms_of(self, segments):
        import tempfile
        import shutil
        tmp = tempfile.mkdtemp(prefix="qy_speech_")
        wav = os.path.join(tmp, "s.wav")
        _write_wav(wav, segments)
        samples, sr = decode_mono(wav)
        rms = rms_envelope(samples, sr)
        segs = detect_speech(rms)
        shutil.rmtree(tmp, ignore_errors=True)
        return segs

    def test_finds_two_speech_segments_with_gaps(self):
        segs = self._rms_of([(500, 0), (1000, 440), (500, 0), (1000, 880), (500, 0)])
        self.assertEqual(len(segs), 2)
        s0, e0 = segs[0]
        s1, e1 = segs[1]
        self.assertTrue(400 <= s0 <= 600, f"第一段起点 {s0} 应在前奏后")
        self.assertTrue(1400 <= e0 <= 1600, f"第一段终点 {e0}")
        self.assertTrue(1900 <= s1 <= 2100, f"第二段起点 {s1} 应在间奏后")
        self.assertTrue(2900 <= e1 <= 3100, f"第二段终点 {e1}")

    def test_all_silence_returns_empty(self):
        import tempfile
        import shutil
        tmp = tempfile.mkdtemp(prefix="qy_sil_")
        wav = os.path.join(tmp, "sil.wav")
        _write_wav(wav, [(1000, 0)])
        samples, sr = decode_mono(wav)
        segs = detect_speech(rms_envelope(samples, sr))
        self.assertEqual(segs, [])
        shutil.rmtree(tmp, ignore_errors=True)


class TestAssignTimestamps(unittest.TestCase):
    def test_skips_intro_and_outro(self):
        """歌词行应铺在有声段上，第一行不落在前奏、最后一行不落在尾奏。"""
        segments = [(5000, 10000), (20000, 25000)]
        pairs = assign_timestamps(["a", "b", "c", "d"], segments, total_ms=30000)
        times = [ms for _, ms in pairs]
        self.assertEqual(times, [6250, 8750, 21250, 23750])
        self.assertGreaterEqual(times[0], 5000)      # 不在前奏
        self.assertLessEqual(times[-1], 25000)       # 不在尾奏

    def test_no_segments_falls_back_to_uniform(self):
        pairs = assign_timestamps(["a", "b", "c", "d"], [], total_ms=40000)
        self.assertEqual([ms for _, ms in pairs], [0, 10000, 20000, 30000])

    def test_empty_lines_returns_empty(self):
        self.assertEqual(assign_timestamps([], [], 1000), [])


class TestAlignLocal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_align_")
        self.wav = os.path.join(self.tmp, "song.wav")
        _speech_tone_wav(self.wav)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_end_to_end_produces_synced_lrc(self):
        outcome = align_local(self.wav, "第一句\n第二句\n第三句\n第四句")
        self.assertTrue(outcome.lrc)
        lines = parse_lrc(outcome.lrc)
        self.assertEqual(len(lines), 4)
        times = [ln.time_ms for ln in lines]
        self.assertEqual(times, sorted(times), "时间戳应递增")
        self.assertEqual([ln.text for ln in lines], ["第一句", "第二句", "第三句", "第四句"])

    def test_no_audio(self):
        self.assertEqual(align_local(os.path.join(self.tmp, "nope.mp3"), "歌词").error_code,
                         "no_audio")

    def test_no_lyrics(self):
        self.assertEqual(align_local(self.wav, "").error_code, "no_lyrics")
        self.assertEqual(align_local(self.wav, "   \n  ").error_code, "no_lyrics")

    def test_already_synced(self):
        self.assertEqual(align_local(self.wav, "[00:01.00]故事的小黄花").error_code,
                         "already_synced")

    def test_decode_failed(self):
        bad = os.path.join(self.tmp, "bad.mp3")
        with open(bad, "wb") as f:
            f.write(b"this is not audio")
        self.assertEqual(align_local(bad, "歌词").error_code, "decode_failed")

    def test_missing_decoder_degrades_to_no_decoder(self):
        """miniaudio 不可用（打包漏收 _cffi_backend）只该降级，不该抛出。

        `sys.modules[name] = None` 会让 `import name` 直接抛 ImportError，正好
        模拟「解码器装不上」而无需真的卸载依赖。
        """
        import app.lyrics_local_align as la
        with mock.patch.dict(sys.modules, {"miniaudio": None}):
            with self.assertRaises(la.AudioDecoderUnavailable):
                decode_mono(self.wav)
            outcome = align_local(self.wav, "第一句\n第二句")
        self.assertEqual(outcome.error_code, "no_decoder")
        self.assertIn("解码组件", la.describe_error("no_decoder"))

    def test_module_import_does_not_require_decoder(self):
        """模块顶层不许 import miniaudio —— 否则可选依赖会把主程序启动一起拖死。

        在子进程里把 sys.modules['miniaudio'] 置 None 再导入本模块：若顶层有
        `import miniaudio` 就会抛 ImportError，子进程非零退出即判失败。
        """
        import subprocess
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        env.pop("PYTHONPATH", None)
        code = ("import sys; sys.modules['miniaudio'] = None; "
                "import app.lyrics_local_align as m; print('IMPORT_OK')")
        proc = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120)
        self.assertEqual(proc.returncode, 0,
                         f"顶层导入了 miniaudio？stderr={proc.stderr[-500:]}")
        self.assertIn("IMPORT_OK", proc.stdout)


class TestWorker(unittest.TestCase):
    def _run(self, worker, done=None, failed=None, timeout_ms=4000):
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        if done is not None:
            worker.done.connect(lambda *args: (done.append(args), loop.quit()))
        if failed is not None:
            worker.failed.connect(lambda *args: (failed.append(args), loop.quit()))
        QTimer.singleShot(timeout_ms, loop.quit)
        worker.start()
        loop.exec()
        worker.wait(2000)

    def test_emits_done_with_lrc(self):
        done = []
        worker = LyricsLocalAlignWorker("tid-1", "a.mp3", "歌词")
        with mock.patch("app.lyrics_local_align.align_local",
                        return_value=type("O", (), {"lrc": "[00:01.00]hi", "error_code": ""})()):
            self._run(worker, done=done)
        self.assertEqual(done, [("tid-1", "[00:01.00]hi")])

    def test_emits_failed_with_message(self):
        failed = []
        worker = LyricsLocalAlignWorker("tid-2", "a.mp3", "歌词")
        with mock.patch("app.lyrics_local_align.align_local",
                        return_value=type("O", (), {"lrc": None, "error_code": "decode_failed",
                                                    "error_message": ""})()):
            self._run(worker, failed=failed, timeout_ms=600)
        self.assertEqual(failed, [("tid-2", "无法解码该音频（本地对齐支持 mp3/flac/wav/ogg，其余格式请用联网对齐）")])


if __name__ == "__main__":
    unittest.main()
