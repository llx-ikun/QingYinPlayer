# -*- coding: utf-8 -*-
"""视觉歌词面板（JIZURA）：选项一致性 / 数据收敛 / 对外接口回归（v3.4.0）。

这里**不启动 QWebEngineView**：起一次要 2.6s 且吃 GPU，不适合放进回归。
真正要守的是下面四件事：

1. 注入 JS 里的 `PALETTES` / `BGS` 与 `app.models` 的白名单**逐项一致**。
   颜色只能写在 JS（绘制在那边），Python 侧只放 key 白名单供数据收敛 ——
   两边一旦漂移，就会出现「设置里选了琥珀，面板却是桃红」这种查不出原因的怪事。
2. `Settings` 对三个新字段的收敛：不认识的值落回默认，老数据（没有这三个键）
   必须落到原生面板。
3. `normalize_palette` / `normalize_background` 接受 key 与下标、拒绝垃圾值。
4. 桥方法名别被改掉：`PANEL_JS` 是纯字符串，改错了 Python 侧不会报错，
   只会在运行时「点了没反应」。
"""
from __future__ import annotations

import re
import unittest

from app.models import (DEFAULT_LYRICS_PANEL, JIZURA_BACKGROUNDS, JIZURA_PALETTES,
                        LYRICS_PANELS, Settings)
from ui import jizura_panel as jp

# 从注入 JS 里抠出两张表的 key 序列（`{ key: 'xxx', ...` 的书写顺序就是下标顺序，
# Python 侧传下标给它，顺序错了颜色就错位，所以顺序也要比）。
_JS_PALETTE_KEYS = re.compile(r"const PALETTES = \[(.*?)\n  \];", re.S)
_JS_BG_KEYS = re.compile(r"const BGS = \[(.*?)\n  \];", re.S)
_KEY_FIELD = re.compile(r"key: '([a-z]+)'")


def _js_keys(pattern: re.Pattern[str]) -> tuple[str, ...]:
    m = pattern.search(jp.PANEL_JS)
    if m is None:                      # 表被改名 / 挪走
        return ()
    return tuple(_KEY_FIELD.findall(m.group(1)))


class TestOptionTables(unittest.TestCase):
    """JS 表与 Python 白名单必须完全一致（顺序也算）。"""

    def test_palette_keys_match(self):
        self.assertEqual(_js_keys(_JS_PALETTE_KEYS), JIZURA_PALETTES)

    def test_background_keys_match(self):
        self.assertEqual(_js_keys(_JS_BG_KEYS), JIZURA_BACKGROUNDS)

    def test_python_options_derive_from_models(self):
        # Python 侧的下拉数据是从 models 派生的，不该另抄一份
        self.assertEqual(tuple(p["key"] for p in jp.PALETTE_OPTIONS), JIZURA_PALETTES)
        self.assertEqual(tuple(b["key"] for b in jp.BACKGROUND_OPTIONS), JIZURA_BACKGROUNDS)
        self.assertTrue(all(item["name"] for item in jp.PALETTE_OPTIONS))
        self.assertTrue(all(item["name"] for item in jp.BACKGROUND_OPTIONS))

    def test_background_is_independent_of_palette(self):
        # 用户明确要求「独立背景色」：两张表不能是同一份，否则又绑回去了
        self.assertNotEqual(set(JIZURA_PALETTES), set(JIZURA_BACKGROUNDS))
        self.assertIn("auto", JIZURA_BACKGROUNDS)   # 「跟随配色」是默认
        self.assertNotIn("auto", JIZURA_PALETTES)


class TestNormalize(unittest.TestCase):
    def test_palette_key(self):
        self.assertEqual(jp.normalize_palette("amber"), "amber")
        self.assertEqual(jp.normalize_palette("rose"), "rose")

    def test_palette_index(self):
        self.assertEqual(jp.normalize_palette(0), JIZURA_PALETTES[0])
        self.assertEqual(jp.normalize_palette(3), JIZURA_PALETTES[3])

    def test_palette_garbage(self):
        for bad in ("nope", "", None, 999, -1, [], {}):
            self.assertEqual(jp.normalize_palette(bad), "random", msg=repr(bad))

    def test_background_key(self):
        self.assertEqual(jp.normalize_background("ink"), "ink")

    def test_background_index(self):
        self.assertEqual(jp.normalize_background(1), JIZURA_BACKGROUNDS[1])

    def test_background_garbage(self):
        for bad in ("nope", "", None, 999, -1, [], {}):
            self.assertEqual(jp.normalize_background(bad), "auto", msg=repr(bad))


class TestSettingsFields(unittest.TestCase):
    def test_defaults(self):
        s = Settings()
        self.assertEqual(s.lyrics_panel, DEFAULT_LYRICS_PANEL)
        self.assertEqual(s.jizura_palette, "random")
        self.assertEqual(s.jizura_bg, "auto")

    def test_round_trip(self):
        s = Settings(lyrics_panel="jizura", jizura_palette="violet", jizura_bg="pine")
        again = Settings.from_dict(s.to_dict())
        self.assertEqual(again.lyrics_panel, "jizura")
        self.assertEqual(again.jizura_palette, "violet")
        self.assertEqual(again.jizura_bg, "pine")

    def test_old_data_falls_back_to_native(self):
        # 3.3.x 及更早的 data.json 没有这三个键 → 必须落到原生面板，不能升级后突然换脸
        s = Settings.from_dict({"volume": 0.5, "theme": "light"})
        self.assertEqual(s.lyrics_panel, "native")
        self.assertEqual(s.jizura_palette, "random")
        self.assertEqual(s.jizura_bg, "auto")

    def test_unknown_values_converge(self):
        s = Settings.from_dict({"lyrics_panel": "hologram", "jizura_palette": "neon",
                                "jizura_bg": "#000000"})
        self.assertIn(s.lyrics_panel, LYRICS_PANELS)
        self.assertIn(s.jizura_palette, JIZURA_PALETTES)
        self.assertIn(s.jizura_bg, JIZURA_BACKGROUNDS)

    def test_non_dict_payload(self):
        s = Settings.from_dict(None)      # type: ignore[arg-type]
        self.assertEqual(s.lyrics_panel, "native")


class TestBridgeSurface(unittest.TestCase):
    """桥方法名是「字符串契约」，改错不会报错，只会静默失效。"""

    def test_bridge_methods_exist(self):
        for name in ("setLook", "setPalette", "setBg", "render", "setLyrics",
                     "setPlain", "clear", "setMeta", "setCover", "_repaint"):
            self.assertIn(name + "(", jp.PANEL_JS, msg=name)

    def test_panel_class_api(self):
        for name in ("set_synced", "set_plain", "set_empty", "update_position",
                     "set_meta", "set_cover", "set_palette", "set_background"):
            self.assertTrue(callable(getattr(jp.JizuraLyricsPanel, name, None)), msg=name)

    def test_engine_asset_exists(self):
        import os
        self.assertTrue(os.path.isfile(jp._engine_path()), msg=jp._engine_path())


class TestSmoothRenderBridge(unittest.TestCase):
    """v3.4.3：逐帧渲染从「Python 每帧发一次 JS」改成 JS 侧 rAF 自驱。

    这条改动的价值全在「少一次 IPC、多一帧稳定」，而它坏掉的表现是**画面不动或
    卡成 PPT**，不会抛异常 —— 所以用字符串契约把它钉住。
    """

    def test_js_has_raf_loop(self):
        self.assertIn("requestAnimationFrame", jp.PANEL_JS)
        self.assertIn("cancelAnimationFrame", jp.PANEL_JS)

    def test_bridge_methods_exist(self):
        for name in ("play(", "pause(", "sync(", "setFit(", "_applyFit("):
            self.assertIn(name, jp.PANEL_JS, msg=name)

    def test_fit_cover_keeps_aspect(self):
        """全屏必须 cover（等比放大裁边）而不是拉伸：拉伸会把字拉扁。"""
        self.assertIn("object-fit:cover", jp.PANEL_JS)
        self.assertNotIn("object-fit:fill", jp.PANEL_JS)

    def test_sync_interval_is_coarse_enough(self):
        """校正要比帧间隔粗：比一帧还密就退回「每帧一次 IPC」了。"""
        self.assertGreaterEqual(jp._SYNC_INTERVAL_MS, 50)
        self.assertLessEqual(jp._SYNC_INTERVAL_MS, 200)


class TestPythonBridgeCalls(unittest.TestCase):
    """借真实方法 + 假 self：只验「发了什么 JS」，不起 WebEngine。"""

    def _fake(self):
        sent: list[str] = []

        class _Fake:
            _ready = True
            _mode = "synced"
            _position_ms = 0
            _last_sync = 0.0
            _fit = "contain"
            _playing = False

            def _js(self, code):
                sent.append(code)

        _Fake.set_fit = jp.JizuraLyricsPanel.set_fit
        _Fake.update_position = jp.JizuraLyricsPanel.update_position
        _Fake.set_playing = jp.JizuraLyricsPanel.set_playing
        _Fake._apply_play_state = jp.JizuraLyricsPanel._apply_play_state
        return _Fake(), sent

    def test_set_fit_cover_and_contain(self):
        obj, sent = self._fake()
        obj.set_fit("cover")
        obj.set_fit("contain")
        self.assertEqual(sent, ['__panel.setFit("cover");', '__panel.setFit("contain");'])

    def test_set_fit_rejects_unknown(self):
        obj, sent = self._fake()
        obj.set_fit("stretch")
        self.assertEqual(sent, ['__panel.setFit("contain");'])

    def test_update_position_throttles(self):
        obj, sent = self._fake()
        obj.update_position(1000)
        obj.update_position(1060)          # 同一瞬间的第二次应被节流掉
        self.assertEqual(sent, ["__panel.sync(1000);"])

    def test_set_playing_starts_and_stops_loop(self):
        obj, sent = self._fake()
        obj.set_playing(True)
        obj.set_playing(True)              # 同态重复不重发
        obj.set_playing(False)
        self.assertEqual(sent, ["__panel.play(0);", "__panel.pause(0);"])


if __name__ == "__main__":
    unittest.main()
