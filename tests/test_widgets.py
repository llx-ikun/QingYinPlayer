# -*- coding: utf-8 -*-
"""ElidedLabel 省略行为单测（延后省略 + full_text + 销毁安全）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from ui.widgets import ElidedLabel  # noqa: E402

LONG = "一个超级无敌长的歌单名字测试省略号行为"


class TestElidedLabel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_settext_shows_full_text_before_events(self):
        """同步刷新后（事件循环前）必须读得到完整文本——列表行刚创建时
        布局会先给 sizeHint 宽度，同步省略会把「新名字」截成「新…」。"""
        lbl = ElidedLabel(LONG)
        lbl.resize(150, 20)
        self.assertEqual(lbl.text(), LONG)

    def test_elides_after_event_loop(self):
        lbl = ElidedLabel(LONG)
        lbl.resize(150, 20)
        self.app.processEvents()
        self.assertNotEqual(lbl.text(), LONG)
        self.assertIn("…", lbl.text())
        self.assertEqual(lbl.full_text(), LONG)
        self.assertEqual(lbl.toolTip(), LONG)

    def test_short_text_not_elided(self):
        lbl = ElidedLabel("夜曲")
        lbl.resize(150, 20)
        self.app.processEvents()
        self.assertEqual(lbl.text(), "夜曲")

    def test_empty_text(self):
        lbl = ElidedLabel("")
        lbl.resize(50, 20)
        self.app.processEvents()
        self.assertEqual(lbl.text(), "")

    def test_relide_on_resize_when_visible(self):
        """可见控件变窄后应按新宽度重新省略（隐藏控件 resize 不派发
        resizeEvent 是 Qt 固有行为，与产品无关，故用可见宿主验证）。"""
        host = QWidget()
        QVBoxLayout(host).addWidget(ElidedLabel(LONG))
        host.resize(300, 60)
        host.show()
        self.app.processEvents()
        wide = host.findChild(ElidedLabel).text()
        self.assertEqual(wide, LONG)  # 300px 放得下
        host.resize(120, 60)
        self.app.processEvents()
        narrow = host.findChild(ElidedLabel).text()
        self.assertIn("…", narrow)
        self.assertLess(len(narrow), len(wide))
        host.close()

    def test_settext_reelides_on_next_loop(self):
        lbl = ElidedLabel("短")
        lbl.resize(100, 20)
        self.app.processEvents()
        lbl.setText(LONG)
        self.assertEqual(lbl.text(), LONG)  # 事件循环前全量
        self.app.processEvents()
        self.assertIn("…", lbl.text())  # 下一轮按宽度省略

    def test_timer_safe_after_delete(self):
        """控件删除后挂起的省略定时器不得引发 RuntimeError。"""
        lbl = ElidedLabel("临时标签")
        lbl.resize(60, 20)
        lbl.setParent(None)
        lbl.deleteLater()
        self.app.processEvents()
        self.app.processEvents()  # 不炸即通过


if __name__ == "__main__":
    unittest.main()
