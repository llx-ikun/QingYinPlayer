# -*- coding: utf-8 -*-
"""主题调色板单测：浅蓝主题的色相/对比度约束（纯逻辑，不依赖 Qt）。

背景：浅色主题原本是 QQ 绿（#31c27c），与深色主题的蓝紫强调色、应用图标的
蓝紫渐变都不一致，用户要求改为浅蓝。这里把「浅色 = 蓝色系」固化成断言，
避免以后被随手改回绿色或换成低对比色。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.theme import DARK, LIGHT, THEMES, build_stylesheet  # noqa: E402


def _rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float:
    r, g, b = _rgb(color)
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def _contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class TestPaletteFormat(unittest.TestCase):
    def test_all_themes_registered(self):
        self.assertEqual(set(THEMES), {"dark", "light"})

    def test_every_field_is_hex_rgb(self):
        for theme in THEMES.values():
            for field in ("BG", "SURFACE", "SURFACE_HOVER", "SURFACE_ACTIVE", "BORDER",
                          "TEXT", "TEXT_DIM", "ACCENT", "ACCENT_HOVER", "ACCENT_DIM",
                          "ACCENT_SOFT", "DANGER", "HEART", "ON_ACCENT"):
                value = getattr(theme, field)
                self.assertRegex(value, r"^#[0-9a-f]{6}$", f"{theme.name}.{field}={value}")


class TestLightIsBlue(unittest.TestCase):
    """浅色主题必须是浅蓝（不能回到 QQ 绿）。"""

    def test_accent_is_blue_dominant(self):
        for theme in (LIGHT, DARK):
            r, g, b = _rgb(theme.ACCENT)
            self.assertGreater(b, r, f"{theme.name} 强调色应偏蓝：{theme.ACCENT}")
            self.assertGreater(b, g, f"{theme.name} 强调色应偏蓝：{theme.ACCENT}")

    def test_light_surfaces_are_blue_tinted(self):
        """底色带一点蓝，整体呈浅蓝灰而非中性灰/暖灰。"""
        for field in ("BG", "SURFACE_HOVER", "SURFACE_ACTIVE", "BORDER"):
            r, g, b = _rgb(getattr(LIGHT, field))
            self.assertGreaterEqual(b, r, f"LIGHT.{field} 蓝通道应不低于红：{getattr(LIGHT, field)}")
            self.assertGreaterEqual(b, g, f"LIGHT.{field} 蓝通道应不低于绿：{getattr(LIGHT, field)}")

    def test_legacy_green_is_gone(self):
        """旧 QQ 绿（#31c27c 及其深浅变体）不得残留在样式表里。"""
        sheet = build_stylesheet(LIGHT).lower()
        for legacy in ("#31c27c", "#2fbd74", "#1e9e64", "#e2f5ea", "#e9f6ef"):
            self.assertNotIn(legacy, sheet, f"旧绿色 {legacy} 仍在浅色 QSS 中")


class TestContrast(unittest.TestCase):
    """可读性下限，防止为了「浅」把强调色换成看不清的淡色。"""

    def test_light_is_actually_light(self):
        self.assertGreater(_luminance(LIGHT.BG), 0.7)
        self.assertLess(_luminance(LIGHT.TEXT), 0.2)

    def test_body_text_contrast(self):
        for theme in THEMES.values():
            self.assertGreaterEqual(_contrast(theme.TEXT, theme.BG), 7.0, theme.name)
            self.assertGreaterEqual(_contrast(theme.TEXT, theme.SURFACE), 7.0, theme.name)

    def test_accent_readable_on_surface(self):
        """强调色同时用作文字色（导航激活、播放中标题、无损徽标）。"""
        for theme in THEMES.values():
            self.assertGreaterEqual(_contrast(theme.ACCENT, theme.SURFACE), 3.0, theme.name)

    def test_on_accent_readable_on_accent(self):
        """强调色底上的文字（播放键图标、头像首字母、主按钮）。"""
        for theme in THEMES.values():
            self.assertGreaterEqual(_contrast(theme.ON_ACCENT, theme.ACCENT), 3.0, theme.name)

    def test_accent_soft_is_a_tint_not_a_block(self):
        """ACCENT_SOFT 是淡底（选中行/激活导航），必须比 SURFACE 稍深但仍是浅色。"""
        self.assertGreater(_luminance(LIGHT.SURFACE), _luminance(LIGHT.ACCENT_SOFT))
        self.assertGreater(_luminance(LIGHT.ACCENT_SOFT), 0.8)


if __name__ == "__main__":
    unittest.main()
