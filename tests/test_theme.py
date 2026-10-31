# -*- coding: utf-8 -*-
"""主题调色板单测：两套配色（深色「午夜」/ 浅色「晨雾」）+ 内置背景预设（纯逻辑）。

v2.8.3 把主题从四套改成两套：主题只管配色，内置背景图（星空/云海）拆成「背景」
页的预设，跟主题不再联动。这里把「浅色=暖色系、深色=冷色系」固化成断言，避免
以后被随手改回绿色或换成低对比色。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.theme import COLUMBINA, LIGHT, THEMES, build_stylesheet  # noqa: E402


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
        self.assertEqual(set(THEMES), {"columbina", "light"})

    def test_every_field_is_hex_rgb(self):
        for theme in THEMES.values():
            for field in ("BG", "SURFACE", "SURFACE_HOVER", "SURFACE_ACTIVE", "BORDER",
                          "TEXT", "TEXT_DIM", "ACCENT", "ACCENT_HOVER", "ACCENT_DIM",
                          "ACCENT_SOFT", "DANGER", "HEART", "ON_ACCENT"):
                value = getattr(theme, field)
                self.assertRegex(value, r"^#[0-9a-f]{6}$", f"{theme.name}.{field}={value}")


class TestThemeHue(unittest.TestCase):
    """v2.8.3 重做配色：浅色改暖（晨雾米白 + 陶土橙），深色偏冷（午夜墨蓝 + 长春花紫）。"""

    def test_light_is_warm_neutral(self):
        """浅色底色带一点暖（米白），红通道不低于蓝，不再是冷调蓝灰。"""
        for field in ("BG", "SURFACE", "SURFACE_HOVER", "SURFACE_ACTIVE", "BORDER"):
            r, _g, b = _rgb(getattr(LIGHT, field))
            self.assertGreaterEqual(r, b, f"LIGHT.{field} 红通道应不低于蓝：{getattr(LIGHT, field)}")

    def test_light_accent_is_warm(self):
        r, _g, b = _rgb(LIGHT.ACCENT)
        self.assertGreater(r, b, f"浅色强调色应偏暖（陶土橙）：{LIGHT.ACCENT}")

    def test_dark_accent_is_cool(self):
        r, _g, b = _rgb(COLUMBINA.ACCENT)
        self.assertGreater(b, r, f"深色强调色应偏冷（长春花紫）：{COLUMBINA.ACCENT}")

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

    def test_dark_is_actually_dark(self):
        self.assertLess(_luminance(COLUMBINA.BG), 0.2)
        self.assertGreater(_luminance(COLUMBINA.TEXT), 0.7)

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

        custom = derive_accent(COLUMBINA, "#ff7a45")
        self.assertEqual(custom.name, COLUMBINA.name)
        self.assertEqual(custom.BG, COLUMBINA.BG)
        self.assertEqual(custom.TEXT, COLUMBINA.TEXT)
        self.assertEqual(custom.ACCENT, "#ff7a45")

    def test_hover_and_dim_are_distinguishable(self):
        """hover/dim 与主色必须肉眼可分（通道差 ≥ 12，回归浮动条同款阈值）。"""
        from ui.theme import _rgb, derive_accent

        for base in (COLUMBINA, LIGHT):
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

        for base in (COLUMBINA, LIGHT):
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
            self.assertEqual(derive_accent(COLUMBINA, bad).ACCENT, COLUMBINA.ACCENT, repr(bad))

    def test_soft_is_a_tint_between_surface_and_accent(self):
        from ui.theme import derive_accent, luminance

        light = derive_accent(LIGHT, "#ff7a45")
        self.assertGreater(luminance(light.SURFACE), luminance(light.ACCENT_SOFT))
        self.assertGreater(luminance(light.ACCENT_SOFT), 0.8)


class TestFontScale(unittest.TestCase):
    """字号缩放（v2.2）：改的是 QSS 里的 font-size，不重排布局。"""

    def test_scale_one_keeps_original_sizes(self):
        from ui.theme import build_stylesheet

        self.assertEqual(build_stylesheet(COLUMBINA, font_scale=1.0), build_stylesheet(COLUMBINA))

    def test_scaling_multiplies_every_font_size(self):
        import re

        from ui.theme import build_stylesheet

        base = [int(n) for n in re.findall(r"font-size:\s*(\d+)px", build_stylesheet(COLUMBINA))]
        big = [int(n) for n in re.findall(
            r"font-size:\s*(\d+)px", build_stylesheet(COLUMBINA, font_scale=1.25))]
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
            r"font-size:\s*(\d+)px", build_stylesheet(COLUMBINA, font_scale=FONT_SCALE_MIN))]
        self.assertTrue(sizes)
        self.assertGreaterEqual(min(sizes), 9)


class TestThemeCycle(unittest.TestCase):
    """主题是**两态循环**（深色 ↔ 浅色），不是四态。

    这里钉住三件容易改坏的事：默认主题、循环闭环、每个主题都有图标与中文名。
    改漏任何一个，主题钮都会出现「点了没反应」或「图标与目标主题对不上」。
    """

    def test_default_is_light(self):
        from ui.theme import DEFAULT_THEME
        self.assertEqual(DEFAULT_THEME, "light")

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

    def test_theme_icons_are_moon_and_sun(self):
        """主题钮画的是**下一个目标**：浅色→月亮（去深色）、深色→太阳（去浅色）。

        v2.5.1 之前深色目标用的是羽毛，16px 下糊成一团认不出来，用户圈图要求
        「画成月亮」。这两个图标也是彼此最好区分的组合（月牙 vs 圆点+细射线）。
        """
        from ui.theme import THEME_ICON
        self.assertEqual(THEME_ICON["columbina"], "moon")
        self.assertEqual(THEME_ICON["light"], "sun")

    def test_bg_gradient_only_for_columbina(self):
        """渐变底只给深色主题；浅色主题必须仍是纯色（否则 QSS 里多出无谓渐变）。"""
        from ui.theme import THEMES, build_stylesheet
        self.assertIn("qlineargradient", build_stylesheet(THEMES["columbina"]))
        self.assertNotIn("qlineargradient", build_stylesheet(THEMES["light"]))

    def test_order_is_dark_then_light(self):
        """两态循环顺序：深色 → 浅色。"""
        from ui.theme import THEME_ORDER
        self.assertEqual(THEME_ORDER, ("columbina", "light"))


class TestBuiltinBackgroundPresets(unittest.TestCase):
    """内置背景预设（v2.8.3）：星空 / 云海两张图，从主题里拆出来变成背景。

    钉住三件事：① 预设不再是主题（主题只有配色两套）；② 预设能翻成 image 配置、
    图真的存在且能解码 —— 路径写错在开发态表现正常，打包后却是一块空底；③ 深色
    预设的暗化明显、浅色预设只轻度暗化。
    """

    def test_presets_registered(self):
        from ui.theme import BACKGROUND_PRESETS, PRESET_BY_ID
        self.assertEqual({p.id for p in BACKGROUND_PRESETS}, {"starry", "clouds"})
        self.assertEqual(set(PRESET_BY_ID), {"starry", "clouds"})

    def test_theme_has_no_builtin_image_field(self):
        """主题已不再自带背景图：Theme 不该还有 BG_IMAGE 字段。"""
        self.assertFalse(hasattr(COLUMBINA, "BG_IMAGE"))
        self.assertFalse(hasattr(LIGHT, "BG_IMAGE"))

    def test_preset_config_is_image(self):
        from ui.theme import background_preset_config
        for pid in ("starry", "clouds"):
            cfg = background_preset_config(pid)
            self.assertIsNotNone(cfg, pid)
            self.assertEqual(cfg.type, "image")
            self.assertEqual(cfg.preset, pid)

    def test_unknown_preset_returns_none(self):
        from ui.theme import background_preset_config, preset_image_path
        self.assertIsNone(background_preset_config("不存在的预设"))
        self.assertIsNone(preset_image_path("不存在的预设"))

    def test_preset_image_exists(self):
        import os

        from ui.theme import preset_image_path
        for pid in ("starry", "clouds"):
            path = preset_image_path(pid)
            self.assertIsNotNone(path, pid)
            self.assertTrue(os.path.isfile(path), f"{pid} 的背景图不存在: {path}")
            self.assertGreater(os.path.getsize(path), 20_000, f"{pid} 的图太小，可能是占位")

    def test_image_is_decodable(self):
        """图能真的解码成像素 —— 只判断文件存在会放过「截断的 jpg」这种坏素材。"""
        from PySide6.QtGui import QImage
        from ui.theme import preset_image_path
        for pid in ("starry", "clouds"):
            img = QImage(preset_image_path(pid))
            self.assertFalse(img.isNull(), f"{pid} 的背景图解不出来")
            self.assertGreaterEqual(img.width(), 1280, f"{pid} 的背景图太窄，铺满会糊")

    def test_dark_preset_is_heavily_dimmed(self):
        """星空的图右上有亮月牙，正压着列表的时长/大小列 → 暗化必须明显。

        实测：月牙区域 p90 亮度 0.347，TEXT_DIM 亮度 0.367 —— 两者几乎一样亮，
        暗化 0.3 时对比只有 0.84（字比背景还暗，等于消失）。0.5 是能让月亮主体回到
        3:1 以上的最小值。云海用近白图、深色字天然够读，只需一点暗化把侧栏/播放栏
        从图里剥出来。两者调成同一个值说明没量过实际可读性。
        """
        from ui.theme import background_preset_config
        dark = background_preset_config("starry")
        light = background_preset_config("clouds")
        self.assertGreaterEqual(dark.dim, 0.40)
        self.assertLessEqual(light.dim, 0.20)
        self.assertGreater(dark.dim, light.dim)
        self.assertLess(dark.opacity, 1.0, "星空要掺一档底色削平高光")
        self.assertEqual(dark.blur, 0, "不靠模糊遮丑：糊掉的月亮就不像月亮了")


if __name__ == "__main__":
    unittest.main()
