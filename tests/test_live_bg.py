# -*- coding: utf-8 -*-
"""动态背景（v3.3.0）：能量包络 + 绘制 + 计时器 + 设置接线。

分三层测：
1. `app/audio_energy.py` 纯数学（包络 / 查表 / 缓存）—— 不需要 Qt；
2. `ui/live_bg.py` 绘制 —— 只需要 QApplication（画到 QImage 上，不建窗口）；
3. `BackgroundLayer` / 设置页 —— 要真控件，但都是离屏可见即可。
"""
import array
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.audio_energy import (ENERGY_HZ, build_envelope, energy_at,  # noqa: E402
                              envelope_path, load_envelope, save_envelope,
                              source_key)
from app.models import BackgroundConfig  # noqa: E402
from ui.background import BackgroundLayer  # noqa: E402
from ui.live_bg import (LIVE_BY_KEY, LIVE_KEYS, LIVE_STYLES,  # noqa: E402
                        is_live_style, live_label, paint_live, paint_live_scrim)

SR = 8000


def _tone(seconds: float, amp: float = 0.5, freq: float = 220.0) -> array.array:
    n = int(SR * seconds)
    return array.array("f", [math.sin(2 * math.pi * freq * i / SR) * amp
                             for i in range(n)])


def _silence(seconds: float) -> array.array:
    return array.array("f", [0.0] * int(SR * seconds))


class TestEnvelope(unittest.TestCase):
    """包络是整条链路的地基：它错了，背景就只是"乱闪"。"""

    def test_frame_count_matches_duration(self):
        env = build_envelope(_tone(3.0), SR)
        self.assertEqual(len(env), 3 * ENERGY_HZ)

    def test_silence_is_all_zero(self):
        env = build_envelope(_silence(2.0), SR)
        self.assertTrue(env)
        self.assertEqual(max(env), 0.0)

    def test_loud_section_beats_silence(self):
        samples = _silence(1.0) + _tone(1.0) + _silence(1.0)
        env = build_envelope(samples, SR)
        quiet = sum(env[:15]) / 15
        loud = sum(env[25:35]) / 10
        self.assertLess(quiet, 0.05)
        self.assertGreater(loud, 0.6)

    def test_values_are_normalised(self):
        env = build_envelope(_tone(2.0, amp=0.9), SR)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in env))
        self.assertGreater(max(env), 0.9)      # 满幅信号要顶到接近 1

    def test_empty_input_returns_empty(self):
        self.assertEqual(build_envelope(array.array("f"), SR), [])
        self.assertEqual(build_envelope(_tone(1.0), 0), [])

    def test_normalisation_ignores_single_spike(self):
        """一两个爆点不该把其余部分压成平线（95 分位参考的意义）。"""
        samples = _tone(3.0, amp=0.2)
        spike = array.array("f", [0.0] * 400 + [1.0] * 400)
        env = build_envelope(samples + spike + samples, SR)
        body = env[20:50]
        self.assertGreater(sum(body) / len(body), 0.3)


class TestEnergyAt(unittest.TestCase):
    def test_interpolates_between_frames(self):
        env = [0.0, 1.0]
        self.assertAlmostEqual(energy_at(env, 25), 0.5, places=6)   # 25ms = 半帧

    def test_clamps_after_end(self):
        self.assertEqual(energy_at([0.5, 0.8], 60_000), 0.0)

    def test_negative_and_none_are_zero(self):
        self.assertEqual(energy_at([0.9], -100), 0.0)
        self.assertEqual(energy_at(None, 1000), 0.0)
        self.assertEqual(energy_at([], 1000), 0.0)

    def test_out_of_range_hz(self):
        self.assertEqual(energy_at([0.5], 1000, hz=0), 0.0)


class TestEnvelopeCache(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="qy_energy_")
        self.path = envelope_path(self.dir, "track-abc")

    def test_roundtrip(self):
        env = [0.0, 0.25, 0.5, 1.0]
        self.assertTrue(save_envelope(self.path, env, 200, "100:2000"))
        loaded = load_envelope(self.path, "100:2000")
        self.assertEqual(loaded, env)

    def test_source_fingerprint_mismatch_rejected(self):
        save_envelope(self.path, [0.5], 200, "100:2000")
        self.assertIsNone(load_envelope(self.path, "100:9999"))

    def test_corrupted_file_returns_none(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIsNone(load_envelope(self.path, "100:2000"))

    def test_bad_payload_shapes_rejected(self):
        save_envelope(self.path, [0.5], 200, "1:1")
        for payload in ({"v": 999, "hz": ENERGY_HZ, "src": "1:1", "data": [0.5]},
                        {"v": 1, "hz": ENERGY_HZ, "src": "1:1", "data": "nope"},
                        {"v": 1, "hz": ENERGY_HZ, "src": "1:1", "data": [None]}):
            with open(self.path, "w", encoding="utf-8") as f:
                import json
                json.dump(payload, f)
            self.assertIsNone(load_envelope(self.path, "1:1"), payload)

    def test_missing_file_and_empty_source(self):
        self.assertIsNone(load_envelope(self.path + ".nope", "1:1"))
        self.assertFalse(save_envelope(self.path, [0.5], 1, ""))

    def test_source_key_of_missing_file(self):
        self.assertEqual(source_key(os.path.join(self.dir, "nope.mp3")), "")


class TestLivePaint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def _render(self, style: str, energy: float) -> QImage:
        img = QImage(320, 200, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0, 255))
        painter = QPainter(img)
        paint_live(painter, 320, 200, style, 1.7, energy, QColor("#7ec8e8"), 1.0)
        paint_live_scrim(painter, 320, 200)
        painter.end()
        return img

    def test_every_style_paints_something(self):
        """四种风格都必须真的画出东西 —— 画成空白底会像"功能坏了"。"""
        for key, _label in LIVE_STYLES:
            with self.subTest(style=key):
                img = self._render(key, 0.8)
                colours = {img.pixel(x, y) for x in range(0, 320, 16)
                           for y in range(0, 200, 16)}
                self.assertGreater(len(colours), 1, f"{key} 画得一片纯色")

    def test_energy_changes_output(self):
        """能量必须真的影响画面，否则"跟随音乐"是假的。"""
        quiet = self._render("glow", 0.05)
        loud = self._render("glow", 1.0)
        diff = sum(1 for x in range(0, 320, 8) for y in range(0, 200, 8)
                   if quiet.pixel(x, y) != loud.pixel(x, y))
        self.assertGreater(diff, 100)

    def test_unknown_style_falls_back(self):
        img = self._render("nope", 0.5)
        self.assertEqual(img.width(), 320)

    def test_zero_intensity_paints_nothing(self):
        img = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0, 255))
        painter = QPainter(img)
        paint_live(painter, 64, 64, "glow", 1.0, 1.0, QColor("#ffffff"), 0.0)
        painter.end()
        self.assertEqual(img.pixel(10, 10), QColor(0, 0, 0, 255).rgba())

    def test_degenerate_size_is_safe(self):
        img = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(img)
        paint_live(painter, 0, 0, "ring", 0.0, 0.0, QColor("#fff"))
        paint_live_scrim(painter, 0, 0)
        painter.end()


class TestLiveNaming(unittest.TestCase):
    def test_labels_are_single_source(self):
        self.assertEqual(len(LIVE_KEYS), len(set(LIVE_KEYS)))
        for key, label in LIVE_STYLES:
            self.assertEqual(live_label(key), label)
            self.assertTrue(is_live_style(key))

    def test_unknown_key(self):
        self.assertEqual(live_label("ghost"), "")
        self.assertFalse(is_live_style("ghost"))
        self.assertEqual(LIVE_BY_KEY["glow"], "呼吸光晕")


class TestBackgroundLayerLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def _layer(self) -> BackgroundLayer:
        layer = BackgroundLayer()
        layer.resize(320, 200)
        layer.show()
        return layer

    def test_timer_runs_only_for_live(self):
        layer = self._layer()
        layer.set_config(BackgroundConfig(type="live", preset="glow"))
        self.assertTrue(layer._live_timer.isActive())
        layer.set_config(BackgroundConfig(type="color", color="#123456"))
        self.assertFalse(layer._live_timer.isActive())
        layer.close()

    def test_paused_slows_down(self):
        layer = self._layer()
        layer.set_config(BackgroundConfig(type="live", preset="dust"))
        layer.set_playing(True)
        playing = layer._live_timer.interval()
        layer.set_playing(False)
        idle = layer._live_timer.interval()
        self.assertLess(playing, idle)          # 暂停要更省
        layer.close()

    def test_energy_provider_is_used(self):
        layer = self._layer()
        layer.set_live_energy_provider(lambda: 0.73)
        self.assertAlmostEqual(layer.current_energy(), 0.73, places=6)

    def test_without_provider_energy_is_a_slow_baseline(self):
        """没包络时必须给非零基线：完全静止会被当成"功能坏了"。"""
        layer = self._layer()
        layer.set_live_energy_provider(None)
        values = []
        for _ in range(24):
            layer._live_phase += 0.033
            values.append(layer.current_energy())
        self.assertTrue(all(0.05 < v < 0.6 for v in values))
        self.assertGreater(max(values) - min(values), 0.02)   # 确实在动
        layer.close()

    def test_broken_provider_does_not_raise(self):
        layer = self._layer()

        def boom():
            raise RuntimeError("bad")

        layer.set_live_energy_provider(boom)
        self.assertGreater(layer.current_energy(), 0.0)
        layer.close()

    def test_paints_live_without_crash(self):
        layer = self._layer()
        layer.set_config(BackgroundConfig(type="live", preset="aurora",
                                          opacity=0.8, dim=0.2))
        img = QImage(320, 200, QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(img)
        layer.render(painter, QRectF(0, 0, 320, 200).topLeft().toPoint())
        painter.end()
        layer.close()


class TestSettingsLiveOptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_live_is_a_bg_type(self):
        from ui.settings_dialog import BG_TYPE_OPTIONS
        values = [v for _label, v in BG_TYPE_OPTIONS]
        self.assertIn("live", values)
        self.assertEqual(values[0], "none")     # "无背景" 必须排第一

    def test_from_dict_keeps_live(self):
        cfg = BackgroundConfig.from_dict(
            {"type": "live", "preset": "aurora", "opacity": 0.7, "dim": 0.1})
        self.assertEqual(cfg.type, "live")
        self.assertEqual(cfg.preset, "aurora")
        self.assertAlmostEqual(cfg.opacity, 0.7, places=6)

    def test_unknown_bg_type_falls_back(self):
        self.assertEqual(BackgroundConfig.from_dict({"type": "video"}).type, "none")


if __name__ == "__main__":
    unittest.main()
