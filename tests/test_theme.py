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
        self.assertEqual(set(THEMES), {"columbina", "dark", "light"})

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


class TestAccentOverride(unittest.TestCase):
    """自定义强调色（v2.2）：一个色值派生出整套色阶，且必须守住可读性下限。

    设计取舍：只让用户选**一个**色值，hover/dim/soft/on_accent 全部由它算出来。
    让用户手调四个色值既难用又会自相矛盾（浅 hover + 深 dim 混在一起根本没法看）。
    """

    def test_derived_theme_keeps_other_tokens(self):
        from ui.theme import derive_accent

        custom = derive_accent(DARK, "#ff7a45")
        self.assertEqual(custom.name, DARK.name)
        self.assertEqual(custom.BG, DARK.BG)
        self.assertEqual(custom.TEXT, DARK.TEXT)
        self.assertEqual(custom.ACCENT, "#ff7a45")

    def test_hover_and_dim_are_distinguishable(self):
        """hover/dim 与主色必须肉眼可分（通道差 ≥ 12，回归浮动条同款阈值）。"""
        from ui.theme import _rgb, derive_accent

        for base in (DARK, LIGHT):
            for accent in ("#6c8cff", "#ff7a45", "#22c55e", "#e11d48", "#0ea5e9"):
                custom = derive_accent(base, accent)
                for field in ("ACCENT_HOVER", "ACCENT_DIM"):
                    a, b = _rgb(custom.ACCENT), _rgb(getattr(custom, field))
                    self.assertGreaterEqual(
                        max(abs(a[i] - b[i]) for i in range(3)), 12,
                        f"{base.name}/{accent}: {field} 与 ACCENT 差异过小")

    def test_on_accent_contrast_for_any_accent(self):
        """任意强调色上，ON_ACCENT 都必须有 ≥3:1 对比度（播放键图标靠它可见）。"""
        from ui.theme import derive_accent

        for base in (DARK, LIGHT):
            for accent in ("#6c8cff", "#ff7a45", "#22c55e", "#e11d48",
                           "#0ea5e9", "#facc15", "#111827", "#f8fafc"):
                custom = derive_accent(base, accent)
                self.assertGreaterEqual(
                    _contrast(custom.ON_ACCENT, custom.ACCENT), 3.0,
                    f"{base.name}/{accent}: ON_ACCENT={custom.ON_ACCENT}")

    def test_invalid_accent_falls_back_to_theme_default(self):
        """脏数据（空/非 hex/三位缩写）不能炸，回退到主题原色。"""
        from ui.theme import derive_accent

        for bad in ("", None, "red", "#12", "#1234567", "javascript:alert(1)"):
            self.assertEqual(derive_accent(DARK, bad).ACCENT, DARK.ACCENT, repr(bad))

    def test_soft_is_a_tint_between_surface_and_accent(self):
        from ui.theme import derive_accent, luminance

        light = derive_accent(LIGHT, "#ff7a45")
        self.assertGreater(luminance(light.SURFACE), luminance(light.ACCENT_SOFT))
        self.assertGreater(luminance(light.ACCENT_SOFT), 0.8)


class TestFontScale(unittest.TestCase):
    """字号缩放（v2.2）：改的是 QSS 里的 font-size，不重排布局。"""

    def test_scale_one_keeps_original_sizes(self):
        from ui.theme import build_stylesheet

        self.assertEqual(build_stylesheet(DARK, font_scale=1.0), build_stylesheet(DARK))

    def test_scaling_multiplies_every_font_size(self):
        import re

        from ui.theme import build_stylesheet

        base = [int(n) for n in re.findall(r"font-size:\s*(\d+)px", build_stylesheet(DARK))]
        big = [int(n) for n in re.findall(
            r"font-size:\s*(\d+)px", build_stylesheet(DARK, font_scale=1.25))]
        self.assertEqual(len(base), len(big))
        for a, b in zip(base, big, strict=True):
            self.assertEqual(b, max(9, round(a * 1.25)), f"{a} → {b}")

    def test_scale_is_clamped_to_safe_range(self):
        """0.5 / 3.0 这种离谱值要夹到安全区间：布局没有为极端字号做准备。"""
        from ui.theme import FONT_SCALE_MAX, FONT_SCALE_MIN, clamp_font_scale

        self.assertEqual(clamp_font_scale(0.2), FONT_SCALE_MIN)
        self.assertEqual(clamp_font_scale(9.0), FONT_SCALE_MAX)
        self.assertEqual(clamp_font_scale("bad"), 1.0)
        self.assertEqual(clamp_font_scale(1.15), 1.15)

    def test_no_font_shrinks_below_readable_floor(self):
        """缩到最小档时 10px 的徽标会变 9px，不能更小。"""
        import re

        from ui.theme import FONT_SCALE_MIN, build_stylesheet

        sizes = [int(n) for n in re.findall(
            r"font-size:\s*(\d+)px", build_stylesheet(DARK, font_scale=FONT_SCALE_MIN))]
        self.assertTrue(sizes)
        self.assertGreaterEqual(min(sizes), 9)


class TestThemeCycle(unittest.TestCase):
    """v2.3「星月」主题接入后，主题是**三态循环**而不是深浅二态。

    这里钉住三件容易改坏的事：默认主题、循环闭环、每个主题都有图标与中文名。
    改漏任何一个，主题钮都会出现「点了没反应」或「图标与目标主题对不上」。
    """

    def test_default_is_columbina(self):
        from ui.theme import DEFAULT_THEME
        self.assertEqual(DEFAULT_THEME, "columbina")

    def test_cycle_covers_all_themes_and_closes(self):
        from ui.theme import THEME_NEXT, THEME_ORDER, THEMES
        self.assertEqual(set(THEME_ORDER), set(THEMES))
        seen, cur = [], THEME_ORDER[0]
        for _ in range(len(THEME_ORDER)):
            seen.append(cur)
            cur = THEME_NEXT[cur]
        self.assertEqual(cur, THEME_ORDER[0], "循环没有闭环")
        self.assertEqual(set(seen), set(THEMES), "循环遗漏了某个主题")

    def test_every_theme_has_icon_and_label(self):
        from ui.theme import THEME_ICON, THEME_LABEL, THEMES
        self.assertEqual(set(THEME_ICON), set(THEMES))
        self.assertEqual(set(THEME_LABEL), set(THEMES))

    def test_bg_gradient_only_for_columbina(self):
        """渐变底只给星月主题；深浅两色主题必须仍是纯色（否则 QSS 里多出无谓渐变）。"""
        from ui.theme import THEMES, build_stylesheet
        self.assertIn("qlineargradient", build_stylesheet(THEMES["columbina"]))
        for name in ("dark", "light"):
            self.assertNotIn("qlineargradient", build_stylesheet(THEMES[name]), name)


if __name__ == "__main__":
    unittest.main()
