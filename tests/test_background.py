# -*- coding: utf-8 -*-
"""自定义背景（v2.2）：图片导入 / 铺满裁切 / 模糊近似 / 半透明样式表。

这些用例都要 QApplication（QPixmap 依赖 QGuiApplication），跑在 offscreen 下；
offscreen 不能验证「好不好看」，只验证「尺寸对、能画出来、不崩」——
外观由 tools/shot.py 在真实平台截图人眼验收。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import BackgroundConfig  # noqa: E402


def setUpModule():
    from PySide6.QtWidgets import QApplication
    global _app
    _app = QApplication.instance() or QApplication(sys.argv[:1])


def _make_image(path: str, width: int = 800, height: int = 400) -> str:
    """造一张两色图（左亮右暗），用来判断有没有真的画上去。"""
    from PySide6.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    from PySide6.QtGui import QPainter

    painter = QPainter(image)
    painter.fillRect(0, 0, width // 2, height, QColor("#ffffff"))
    painter.fillRect(width // 2, 0, width // 2, height, QColor("#000000"))
    painter.end()
    image.save(path)
    return path


class TestPreparePixmap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_bg_")
        self.image = _make_image(os.path.join(self.tmp, "wide.png"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_output_matches_target_size(self):
        from ui.background import prepare_pixmap

        result = prepare_pixmap(self.image, 400, 300, 0)
        self.assertIsNotNone(result)
        self.assertEqual((result.width(), result.height()), (400, 300))

    def test_missing_file_returns_none(self):
        from ui.background import prepare_pixmap

        self.assertIsNone(prepare_pixmap(os.path.join(self.tmp, "nope.png"), 100, 100, 0))
        self.assertIsNone(prepare_pixmap("", 100, 100, 0))
        self.assertIsNone(prepare_pixmap(self.image, 0, 100, 0))

    def test_blur_keeps_size_and_changes_pixels(self):
        """模糊不能改变尺寸；且必须真的把边缘糊掉（左右两色交界处像素应介于两者）。"""
        from ui.background import prepare_pixmap

        sharp = prepare_pixmap(self.image, 400, 200, 0)
        blurred = prepare_pixmap(self.image, 400, 200, 30)
        self.assertEqual((blurred.width(), blurred.height()), (400, 200))
        self.assertNotEqual(sharp.toImage().pixelColor(199, 100).name(),
                            blurred.toImage().pixelColor(199, 100).name())

    def test_cache_returns_same_object_for_same_key(self):
        from ui.background import prepare_pixmap

        first = prepare_pixmap(self.image, 200, 100, 5)
        second = prepare_pixmap(self.image, 200, 100, 5)
        self.assertIs(first, second)

    def test_aspect_ratio_not_distorted(self):
        """800×400 的图铺到 200×200：应等比放大后居中裁切，而不是压扁。"""
        from ui.background import prepare_pixmap

        result = prepare_pixmap(self.image, 200, 200, 0)
        image = result.toImage()
        # 原图左右各半（白/黑）；居中裁切后仍应是左白右黑，而不是整体变灰
        self.assertGreater(image.pixelColor(20, 100).lightness(),
                           image.pixelColor(180, 100).lightness())


class TestBackgroundLayer(unittest.TestCase):
    def test_inactive_when_type_none(self):
        from ui.background import BackgroundLayer

        layer = BackgroundLayer()
        layer.set_config(BackgroundConfig())
        self.assertFalse(layer.is_active())

    def test_active_for_every_visual_type(self):
        from ui.background import BackgroundLayer

        layer = BackgroundLayer()
        for bg_type in ("color", "gradient", "image"):
            layer.set_config(BackgroundConfig(type=bg_type))
            self.assertTrue(layer.is_active(), bg_type)

    def test_paints_each_type_without_crashing(self):
        from ui.background import BackgroundLayer

        layer = BackgroundLayer()
        layer.resize(200, 120)
        for config in (
            BackgroundConfig(type="color", color="#3b82f6"),
            BackgroundConfig(type="gradient", color="#1e3a8a", color2="#7c3aed"),
            BackgroundConfig(type="image", image=""),          # 图片缺失也不能崩
            BackgroundConfig(type="color", color="#ffffff", dim=0.6, opacity=0.5),
        ):
            layer.set_config(config)
            pixmap = layer.grab()
            self.assertEqual((pixmap.width(), pixmap.height()), (200, 120))

    def test_opacity_controls_strength(self):
        """不透明度 1.0 与 0.2 在同一底色上必须看得出差别。

        不能用 grab()：它会先把控件画到不透明白底上，白色背景 × 任何透明度都
        是白的（断言永远相等）。改为 render 到一张黑图上，透明度才看得出来。
        """
        from PySide6.QtGui import QColor, QImage

        from ui.background import BackgroundLayer

        layer = BackgroundLayer()
        layer.resize(80, 60)

        def lightness_at(opacity: float) -> int:
            layer.set_config(BackgroundConfig(type="color", color="#ffffff",
                                              opacity=opacity))
            canvas = QImage(80, 60, QImage.Format.Format_ARGB32)
            canvas.fill(QColor("#000000"))
            layer.render(canvas)
            return canvas.pixelColor(40, 30).lightness()

        self.assertGreater(lightness_at(1.0), lightness_at(0.2))


class TestImportBackground(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_bgs_")
        self.src = _make_image(os.path.join(self.tmp, "wall paper.png"))
        self.dest_dir = os.path.join(self.tmp, "bgs")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_copies_into_data_dir(self):
        from app.library import import_background

        stored = import_background(self.src, self.dest_dir)
        self.assertTrue(os.path.isfile(stored))
        self.assertTrue(stored.startswith(self.dest_dir))
        self.assertEqual(os.path.getsize(stored), os.path.getsize(self.src))

    def test_name_gets_signature_suffix(self):
        """文件名带指纹后缀：两个不同目录的同名图片不会互相覆盖。"""
        from app.library import import_background

        stored = import_background(self.src, self.dest_dir)
        name = os.path.basename(stored)
        self.assertTrue(name.endswith(".png"))
        stem = os.path.splitext(name)[0]
        self.assertRegex(stem, r"_[0-9a-f]{8}$")
        self.assertTrue(stem.startswith("wall"))

    def test_same_image_reused(self):
        from app.library import import_background

        first = import_background(self.src, self.dest_dir)
        second = import_background(self.src, self.dest_dir)
        self.assertEqual(first, second)
        self.assertEqual(len(os.listdir(self.dest_dir)), 1)


class TestScrimStylesheet(unittest.TestCase):
    """有背景时面板必须半透明——否则背景被完全盖住，用户会以为"设了没反应"。"""

    def test_panels_become_translucent(self):
        from ui.theme import DARK, build_stylesheet

        sheet = build_stylesheet(DARK, scrim=0.78)
        self.assertIn("rgba(", sheet)
        self.assertNotIn(f"QWidget#Sidebar {{ background: {DARK.SURFACE}; }}", sheet)

    def test_window_root_stays_opaque(self):
        """窗口根底色必须不透明：否则降低背景不透明度时透出的是桌面。"""
        from ui.theme import DARK, build_stylesheet

        sheet = build_stylesheet(DARK, scrim=0.78)
        self.assertIn(f"QWidget#WindowRoot {{ background: {DARK.BG}; }}", sheet)

    def test_dialogs_stay_opaque(self):
        """对话框是独立顶层窗口，半透明会直接看到桌面。"""
        from ui.theme import DARK, build_stylesheet

        sheet = build_stylesheet(DARK, scrim=0.78)
        self.assertIn(f"QDialog#SettingsDialog, QDialog#QueuePanel, QMenu, QToolTip, QMessageBox,\n"
                      f"QLineEdit, QTextEdit, QComboBox, QComboBox QAbstractItemView,\n"
                      f"QLabel#Toast {{ background: {DARK.SURFACE}; }}", sheet)

    def test_no_scrim_keeps_original_stylesheet(self):
        from ui.theme import DARK, build_stylesheet

        self.assertEqual(build_stylesheet(DARK), build_stylesheet(DARK, scrim=None))
        self.assertNotIn("rgba(", build_stylesheet(DARK))


class TestThemeDecor(unittest.TestCase):
    """v2.3「空月」主题的底层装饰：淡月牙 + 星点。

    只验证「该画时画了、不该画时什么都没画」，好不好看交给真实平台截图。
    注意不能用 grab()：它先铺不透明白底，测不出「透明」与「极淡」。
    """

    def _non_black_samples(self, decor: str) -> int:
        from PySide6.QtGui import QColor, QImage
        from ui.background import BackgroundLayer

        layer = BackgroundLayer()
        layer.resize(420, 300)
        layer.set_config(BackgroundConfig())
        layer.set_decor(decor, "#7ec8e8")
        img = QImage(420, 300, QImage.Format.Format_ARGB32)
        img.fill(QColor("#000000"))
        layer.render(img)
        count = 0
        for x in range(0, 420, 3):
            for y in range(0, 300, 3):
                if img.pixelColor(x, y).lightness() > 2:
                    count += 1
        return count

    def test_decor_paints_when_enabled(self):
        self.assertGreater(self._non_black_samples("columbina"), 8, "空月装饰没有画出来")

    def test_no_decor_paints_nothing(self):
        self.assertEqual(self._non_black_samples(""), 0, "没有装饰时不该画任何东西")

    def test_decor_does_not_count_as_custom_background(self):
        from ui.background import BackgroundLayer
        layer = BackgroundLayer()
        layer.set_config(BackgroundConfig())
        layer.set_decor("columbina", "#7ec8e8")
        self.assertFalse(layer.is_active(), "主题装饰不算自定义背景，不该触发面板半透明")


if __name__ == "__main__":
    unittest.main()
