# -*- coding: utf-8 -*-
"""ElidedLabel 省略行为单测（延后省略 + full_text + 销毁安全）。"""
import itertools
import os
import re
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


class TestPlayerBarLayout(unittest.TestCase):
    """播放栏宽度必须适配窗口：过宽会把信息列挤空并导致布局抖动（v2.1.3 回归）。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_player_bar_fits_min_window(self):
        from ui.player_bar import PlayerBar
        pb = PlayerBar()
        # MainWindow.setMinimumSize(1100, 720)：播放栏最小宽不得超过窗口最小宽，
        # 否则信息列被挤到 0（副标题全成「…」）、布局在约束边界反复重算导致
        # 窗口/播放栏抖动、进度手柄跟着乱跳。当前实测 ~1098。
        self.assertLessEqual(pb.minimumSizeHint().width(), 1100,
                             "PlayerBar 最小宽度不能超过窗口最小宽度 1100")

    def test_float_bar_not_overlap_cover(self):
        from ui.float_bar import FloatBar
        from ui.player_bar import PlayerBar
        from ui.sidebar import SIDEBAR_WIDTH
        pb = PlayerBar()
        fb = FloatBar()
        fb.adjustSize()
        # v2.1.8：浮动条宽度 = 侧边栏内容宽度（248 - 左右 12），右缘对齐内容右边界 236
        self.assertLessEqual(12 + fb.sizeHint().width(), SIDEBAR_WIDTH - 12,
                             "浮动条右缘应与侧边栏内容右边界对齐，不得跨进内容区")
        self.assertLessEqual(12 + fb.sizeHint().width(),
                             pb.layout().contentsMargins().left(),
                             "浮动条右端不得超过播放栏左缩进，避免压封面")
        # v2.6.1 单行布局：四个控件同一条水平线，整条高度 = 圆钮直径
        tops = {w.geometry().top() for w in
                (fb.theme_toggle, fb.settings_btn, fb.import_btn, fb.dir_btn)}
        self.assertEqual(len(tops), 1, f"四个控件应在同一行，实测 top={tops}")
        self.assertEqual(fb.sizeHint().height(), fb.theme_toggle.height(),
                         "整条高度应等于圆钮直径")

    def test_player_bar_fits_min_window_with_long_title(self):
        """长标题/长艺人名不得把最小宽度顶爆（v2.1.5 复查发现 1185 > 1100）。

        根因：ElidedLabel 继承 QLabel 的 minimumSizeHint（按完整文本算宽度），
        一首「Blazing Heart (英文版)」+ 长艺人名就足以把播放栏撑到 1185px，
        超过窗口最小宽 1100 → 信息列被挤空、布局反复重算导致抖动。
        """
        from PySide6.QtGui import QPixmap
        from ui.player_bar import PlayerBar
        pb = PlayerBar()
        cover = QPixmap(48, 48)
        pb.update_track("Blazing Heart (英文版) - 原神-灼火之心 特别收录版",
                        "Chrissy Costanza/HOYO-MiX/上海爱乐乐团", cover)
        self.assertLessEqual(pb.minimumSizeHint().width(), 1100,
                             "长标题下 PlayerBar 最小宽度仍不得超过 1100")

    def test_time_labels_snug_to_slider(self):
        """左端时间右对齐、右端时间左对齐，两侧留白才对称。"""
        from PySide6.QtCore import Qt
        from ui.player_bar import PlayerBar
        pb = PlayerBar()
        self.assertTrue(pb.time_cur.alignment() & Qt.AlignmentFlag.AlignRight)
        self.assertFalse(pb.time_cur.alignment() & Qt.AlignmentFlag.AlignLeft)
        self.assertTrue(pb.time_total.alignment() & Qt.AlignmentFlag.AlignLeft)
        self.assertFalse(pb.time_total.alignment() & Qt.AlignmentFlag.AlignRight)
        self.assertEqual(pb.time_cur.objectName(), "TimeLabel")
        self.assertEqual(pb.time_total.objectName(), "TimeLabel")


class TestSliderKnob(unittest.TestCase):
    """进度/音量手柄必须是**有色实心**圆钮。

    旧版 QSS 用白心 + 1px 灰边：浅色主题下白钮压在白色底上完全隐形，
    用户截图里根本看不到进度手柄在哪。这组用例直接采样像素，防止再退化。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def _knob_pixels(self, theme_name: str, object_name: str, value: int):
        """返回左端手柄区的像素列表（value=0 时钮在最左，已播放段为空，
        所以这一带出现的饱和蓝只可能来自钮芯本身）。"""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QSlider
        from ui.theme import apply_theme

        apply_theme(self.app, theme_name)
        s = QSlider(Qt.Orientation.Horizontal)
        s.setObjectName(object_name)
        s.setRange(0, 100)
        s.setValue(value)
        s.resize(160, 20)
        s.show()
        self.app.processEvents()
        img = s.grab().toImage()
        s.close()
        k = img.width() / 160.0          # 设备像素比
        return [img.pixelColor(x, y)
                for x in range(0, int(20 * k) + 1)
                for y in range(0, img.height())]

    @staticmethod
    def _is_saturated_blue(c) -> bool:
        """蓝通道主导且明显发蓝（#3b82f6 / #2f74ea / #6c8cff / #829fff 都算）。"""
        return c.blue() > 200 and (c.blue() - c.red()) > 60

    def test_handle_visible_on_light(self):
        pixels = self._knob_pixels("light", "SeekSlider", 0)
        self.assertTrue(any(self._is_saturated_blue(c) for c in pixels),
                        "进度手柄应绘制为强调色实心圆，不能在浅色底上隐形")

    def test_handle_visible_on_columbina(self):
        pixels = self._knob_pixels("columbina", "SeekSlider", 0)
        self.assertTrue(any(self._is_saturated_blue(c) for c in pixels),
                        "深色主题下进度手柄同样必须是强调色实心圆")

    def test_volume_handle_visible_on_light(self):
        pixels = self._knob_pixels("light", "VolumeSlider", 0)
        self.assertTrue(any(self._is_saturated_blue(c) for c in pixels),
                        "音量手柄同样不能是白心白环（会隐形）")

    def test_handle_round_not_square(self):
        """手柄必须是圆：四角像素不能是钮芯色（方块的特征是角落被填满）。

        QSS 里 `margin` 给的盒高不足时，Qt 会把圆压成圆角方块 —— 踩过。
        """
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QSlider
        from ui.theme import apply_theme

        apply_theme(self.app, "light")
        s = QSlider(Qt.Orientation.Horizontal)
        s.setObjectName("SeekSlider")
        s.setRange(0, 100)
        s.setValue(0)
        s.resize(160, 20)
        s.show()
        self.app.processEvents()
        img = s.grab().toImage()
        s.close()

        # 手柄外接框左上角 (1,1) 若为钮芯色 → 说明是方块
        corner = img.pixelColor(1, 1)
        self.assertFalse(self._is_saturated_blue(corner),
                         "手柄四角不应被钮芯色填满（否则是方块而非圆）")


class TestTrackListLayout(unittest.TestCase):
    """列表页头 / 列头 / 排序控件（v2.1.4）。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def _tracks(self):
        from app.models import Track
        names = ["夜曲", "晴天", "晨间轻音乐"]
        return [Track(id=f"t{i}", path=f"C:/fake/{i}.mp3", title=name,
                      duration_ms=(i + 1) * 60000, added_at=i + 1)
                for i, name in enumerate(names)]

    def test_column_header_slots_match_row_slots(self):
        """列头槽位必须与行槽位一一对应，否则整列会错位（v2.1.4 修的就是这个）。"""
        from ui.track_list import TrackItemWidget, TrackList
        list_widget = TrackList()
        row = TrackItemWidget()
        self.assertEqual(list_widget._col_header_layout.count(), row.layout().count())
        self.assertEqual(list_widget._col_header_layout.spacing(), row.layout().spacing())

    def test_column_header_inset_matches_row_padding(self):
        """列头左右内缩 = 列表项 margin + 行内容内边距，两者相等才逐列对齐。"""
        from ui.track_list import TrackItemWidget, TrackList
        list_widget = TrackList()
        row = TrackItemWidget()
        margins = list_widget._col_header_layout.contentsMargins()
        row_pad = row.layout().contentsMargins()
        self.assertEqual(margins.left(), 8 + row_pad.left())
        self.assertEqual(margins.right(), 8 + row_pad.right())

    def test_sort_combo_lists_every_preset(self):
        from app.sorting import SORT_PRESETS
        from ui.track_list import TrackList
        combo = TrackList().sort_combo
        listed = [combo.itemData(i) for i in range(combo.count())]
        # 分隔符项的 itemData 为 None，过滤掉后应与预设表完全一致（含顺序）
        self.assertEqual([d for d in listed if d], [p.id for p in SORT_PRESETS])
        self.assertIn(None, listed)  # 分组分隔符存在

    def test_set_sort_is_silent(self):
        from ui.track_list import TrackList
        list_widget = TrackList()
        emitted = []
        list_widget.sort_changed.connect(emitted.append)
        list_widget.set_sort("size:desc")
        self.assertEqual(emitted, [], "程序化设置排序不应触发 sort_changed")
        self.assertEqual(list_widget.sort_combo.currentData(), "size:desc")

    def test_user_choice_emits_preset_id(self):
        from ui.track_list import TrackList
        list_widget = TrackList()
        emitted = []
        list_widget.sort_changed.connect(emitted.append)
        combo = list_widget.sort_combo
        target = next(i for i in range(combo.count()) if combo.itemData(i) == "duration:asc")
        combo.setCurrentIndex(target)
        self.assertEqual(emitted, ["duration:asc"])

    def test_legacy_sort_key_does_not_raise(self):
        from ui.track_list import TrackList
        list_widget = TrackList()
        list_widget.set_sort("added")  # 旧式纯维度 key
        self.assertEqual(list_widget.sort_combo.currentData(), "added:desc")

    def test_header_shows_total_duration(self):
        from ui.track_list import TrackList
        list_widget = TrackList()
        list_widget.set_header("音乐库", 3, 3_600_000)
        # count_label 保持原有「共 N 首」格式（E2E 依赖）
        self.assertEqual(list_widget.count_label.text(), "共 3 首")
        self.assertIn("1:00:00", list_widget.stats_label.text())
        self.assertFalse(list_widget.stats_label.isHidden())

    def test_header_hides_stats_when_empty(self):
        from ui.track_list import TrackList
        list_widget = TrackList()
        list_widget.set_header("音乐库", 0, 0)
        self.assertTrue(list_widget.stats_label.isHidden())

    def test_row_shows_size_column(self):
        from PySide6.QtGui import QPixmap
        from ui.track_list import TrackItemWidget, TrackList
        list_widget = TrackList()
        tracks = self._tracks()
        sizes = {"t0": 820 * 1024, "t1": int(8.4 * 1024 * 1024), "t2": 0}
        list_widget.set_tracks(tracks, lambda _t: QPixmap(40, 40), None,
                               size_getter=lambda t: sizes[t.id])
        first = list_widget.list.itemWidget(list_widget.list.item(0))
        second = list_widget.list.itemWidget(list_widget.list.item(1))
        self.assertIsInstance(first, TrackItemWidget)
        self.assertEqual(first.size.text(), "820 KB")
        self.assertEqual(second.size.text(), "8.4 MB")
        third = list_widget.list.itemWidget(list_widget.list.item(2))
        self.assertEqual(third.size.text(), "--")  # 大小未知

    def test_empty_state_hidden_when_has_tracks(self):
        from PySide6.QtGui import QPixmap
        from ui.track_list import TrackList
        list_widget = TrackList()
        list_widget.set_tracks(self._tracks(), lambda _t: QPixmap(40, 40), None)
        self.assertTrue(list_widget._empty_box.isHidden())
        self.assertTrue(list_widget.play_all_btn.isEnabled())
        list_widget.set_tracks([], lambda _t: QPixmap(40, 40), None)
        self.assertFalse(list_widget._empty_box.isHidden())
        self.assertFalse(list_widget.play_all_btn.isEnabled())


class TestThemeSizes(unittest.TestCase):
    """固定尺寸控件必须等于 QSS 声明的尺寸（padding 泄漏回归，v2.1.4）。

    基础 QPushButton 规则带 6px 10px 内边距，会叠加在 min/max-width 之上，
    实测虚胖 20px（34→54、40→60、46→66、36→58）。后果：播放键圆角失效变成
    椭圆、行内按钮撑歪列对齐、左下浮动条超宽被父控件裁掉（文字全看不见）。
    这类缺陷只在套用 QSS 后出现，所以必须带主题测。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])
        from ui.theme import apply_theme
        apply_theme(cls.app, "columbina")

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet("")

    def test_icon_buttons_keep_declared_size(self):
        from ui.player_bar import PlayerBar
        from ui.sidebar import Sidebar
        pb = PlayerBar()
        # 未 show 的控件 width() 还是 640x480 占位值，必须看 sizeHint（受 QSS min/max 约束）
        play = pb.play_btn.sizeHint()
        self.assertEqual((play.width(), play.height()), (40, 40),
                         "播放键应为 40x40 正圆（border-radius 20）")
        prev = pb.prev_btn.sizeHint()
        self.assertEqual((prev.width(), prev.height()), (34, 34))
        nav = next(iter(Sidebar()._nav_buttons.values())).sizeHint()
        # 侧栏图标导航与浮动条圆钮同尺寸（38 正圆），两者左缘同在 x=12
        self.assertEqual((nav.width(), nav.height()), (38, 38))

    def test_float_bar_fits_player_bar_indent(self):
        """浮动条右端不得超过播放栏左缩进，否则压住封面（且宽度不足会被裁）。"""
        from ui.float_bar import FloatBar
        from ui.player_bar import PlayerBar
        pb = PlayerBar()
        fb = FloatBar()
        fb.adjustSize()
        self.assertLessEqual(12 + fb.sizeHint().width(),
                             pb.layout().contentsMargins().left())
        # 每个文字按钮都得有正宽度，不能因父控件过窄被裁掉。
        # v2.6.1 单行后宽 65（4 个 12px 中文字 ≈ 48 + 左右内边距），下限 60。
        for btn in (fb.import_btn, fb.dir_btn):
            self.assertGreaterEqual(btn.sizeHint().width(), 60, btn.text())
            self.assertGreaterEqual(btn.width(), 60, btn.text())

    def test_sidebar_nickname_not_truncated(self):
        """昵称列不能被徽标卡死：「音乐爱好者」曾只显示「音乐爱…」。"""
        from ui.sidebar import Sidebar
        sb = Sidebar()
        sb.resize(248, 700)
        sb.show()
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(sb.nickname_label.text(), sb.nickname_label.full_text())
        self.assertGreaterEqual(sb.nickname_label.width(), 120)
        sb.close()


class TestFloatBarStyle(unittest.TestCase):
    """浮动工具条的视觉契约。

    v2.1.2 起左下角一直是「三个孤立直角方块」：`#FloatTextBtn` 的
    border-radius 写了 16px，而按钮只有 28px 高 —— **超过短边一半时 Qt 直接
    退化成直角**（不圆、也不报错）。v2.2.2 又按需求改为「左列两个圆钮 +
    右侧两个独立按钮」，这组用例钉住：圆钮是正圆、按钮圆角合规、悬停可辨、
    「设置」确实在「主题」下方且用齿轮图标。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet("")

    @staticmethod
    def _decls(stylesheet: str, selector: str) -> list[str]:
        """取 QSS 里该选择器的**全部**声明块。

        同一个选择器会出现多次（固定尺寸控件会先被一条 `padding: 0px` 的
        合并规则命中，再单独声明圆角），只取第一处会读到错误的块。
        """
        out, start = [], 0
        while True:
            idx = stylesheet.find(selector + " {", start)
            if idx < 0:
                break
            end = stylesheet.find("}", idx)
            out.append(stylesheet[idx:end])
            start = end
        assert out, f"QSS 缺少规则: {selector}"
        return out

    @classmethod
    def _radius(cls, stylesheet: str, selector: str) -> float:
        for decl in cls._decls(stylesheet, selector):
            m = re.search(r"border-radius:\s*([\d.]+)px", decl)
            if m:
                return float(m.group(1))
        raise AssertionError(f"{selector} 没有声明 border-radius")

    def test_two_circle_buttons_same_size_and_row(self):
        """两个圆钮（主题 / 设置）同尺寸、同一水平线，且都是正圆图标钮。"""
        from ui.float_bar import FloatBar
        fb = FloatBar()
        fb.adjustSize()
        # v2.6.1 单行布局：由「上下竖排」改为「左右并排」
        self.assertEqual(fb.theme_toggle.geometry().top(), fb.settings_btn.geometry().top(),
                         "设置齿轮应与主题按钮同处一行")
        self.assertLess(fb.theme_toggle.geometry().left(), fb.settings_btn.geometry().left(),
                        "主题钮在左、设置齿轮在右")
        self.assertEqual(fb.theme_toggle.width(), fb.settings_btn.width())
        self.assertEqual(fb.theme_toggle.width(), fb.theme_toggle.height(), "主题钮应为正圆")
        self.assertEqual(fb.settings_btn.width(), fb.settings_btn.height(), "设置钮应为正圆")

    def test_single_row_layout_is_exactly_sidebar_width(self):
        """四个入口并成一排：总宽必须刚好 224，且互不重叠。

        38 + 6 + 38 + 6 + 65 + 6 + 65 = 224 = 侧栏内容宽。
        改任何一个尺寸都会破坏「右缘与侧栏内容右边界齐平」，所以锁死。
        """
        from ui.float_bar import FloatBar
        fb = FloatBar()
        fb.adjustSize()
        widgets = [fb.theme_toggle, fb.settings_btn, fb.import_btn, fb.dir_btn]
        # 依次排列、无重叠、无反向
        for prev, nxt in itertools.pairwise(widgets):
            self.assertLessEqual(prev.geometry().right(), nxt.geometry().left() + 1,
                                 f"{prev.toolTip() or prev.text()} 与右侧控件重叠")
        self.assertEqual(widgets[0].geometry().left(), 0)
        # QRect.right() 是「x + 宽 - 1」（含端点），所以要 +1 才是真正占到的右边界
        self.assertEqual(widgets[-1].geometry().right() + 1, fb.width(),
                         "最后一个控件应顶到整条右缘")
        self.assertEqual(fb.width(), 224, "整条宽必须等于侧栏内容宽")
        self.assertEqual(fb.height(), 38, "单行高度应等于圆钮直径 38")

    def test_settings_uses_gear_icon(self):
        """「设置」必须是齿轮图标，不是旧的三条推子线。"""
        from ui.float_bar import FloatBar
        fb = FloatBar()
        self.assertEqual(fb.settings_btn._kind, "gear", "设置钮应使用 gear 图标")
        self.assertEqual(fb.settings_btn.toolTip(), "设置")
        # 齿轮与其他图标同尺寸渲染（v2.2.2 放大后为 16px）
        self.assertEqual(fb.settings_btn.iconSize().width(), 16)

    def test_import_and_dir_are_separate_buttons(self):
        """导入音乐 / 数据目录是各自独立的按钮，不再共用分段托盘。"""
        from ui.float_bar import FloatBar
        fb = FloatBar()
        fb.adjustSize()
        self.assertFalse(hasattr(fb, "tray"), "不应再有分段托盘容器")
        self.assertEqual(fb.import_btn.text().replace("\n", ""), "导入音乐")
        self.assertEqual(fb.dir_btn.text().replace("\n", ""), "数据目录")
        # 两者是不同的控件，且都直接挂在浮动条上（没有中间托盘容器）
        self.assertIsNot(fb.import_btn, fb.dir_btn)
        for btn in (fb.import_btn, fb.dir_btn):
            self.assertIs(btn.parent(), fb, f"{btn.text()} 应直接挂在浮动条上")
        # 与两个圆钮同处一行：导入在数据目录左边，且都在圆钮右侧
        self.assertLess(fb.import_btn.geometry().left(), fb.dir_btn.geometry().left())
        self.assertGreater(fb.import_btn.geometry().left(),
                           fb.settings_btn.geometry().right(),
                           "文字按钮应在两个圆钮的右边")

    def test_width_matches_sidebar_content(self):
        """整条宽度必须等于侧边栏内容宽度，右缘才能与内容右边界对齐。"""
        from ui.float_bar import FloatBar
        from ui.sidebar import SIDEBAR_WIDTH, Sidebar
        fb = FloatBar()
        m = Sidebar().layout().contentsMargins()
        content = SIDEBAR_WIDTH - m.left() - m.right()
        self.assertEqual(fb.width(), content,
                         f"浮动条宽 {fb.width()} != 侧栏内容宽 {content}")

    def test_text_button_radius_within_half_height(self):
        """圆角不得超过按钮半高，否则 Qt 渲染成直角方块。"""
        from ui.float_bar import FloatBar
        from ui.theme import THEMES, build_stylesheet
        radius = self._radius(build_stylesheet(THEMES["light"]), "QPushButton#FloatTextBtn")
        fb = FloatBar()   # 必须持住引用，否则 children() 迭代中 C++ 对象就没了
        for btn in (fb.import_btn, fb.dir_btn):
            # 用 minimumHeight 而不是 sizeHint：按钮高度由 setFixedHeight 钉死，
            # sizeHint 仍会按图标+文字的默认意图算（26px），量到的不是渲染高度。
            half = btn.minimumHeight() / 2
            self.assertLessEqual(radius, half,
                                 f"radius {radius}px > 半高 {half}px，会被渲染成直角")

    def test_theme_toggle_is_a_circle(self):
        """圆钮是正圆：radius 必须接近半径（差 1px 内仍算圆）。"""
        from ui.float_bar import FloatBar
        from ui.theme import THEMES, build_stylesheet
        fb = FloatBar()
        radius = self._radius(build_stylesheet(THEMES["light"]), "QPushButton#CircleBtn")
        side = fb.theme_toggle.minimumHeight()
        self.assertGreaterEqual(radius, side / 2 - 1, "radius 太小，圆会变成圆角方块")
        # 两个圆钮同尺寸，读成同一族
        self.assertEqual(side, fb.settings_btn.minimumHeight())

    def test_hover_fill_is_distinguishable(self):
        """悬停底色与底座底色必须拉开差距 —— 否则鼠标划过去毫无反馈。"""
        from ui.theme import THEMES

        def rgb(c: str) -> tuple[int, int, int]:
            return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]

        for name, t in THEMES.items():
            base, hover = rgb(t.SURFACE), rgb(t.SURFACE_ACTIVE)
            delta = max(abs(a - b) for a, b in zip(base, hover, strict=True))
            self.assertGreaterEqual(
                delta, 12,
                f"{name} 主题悬停色 {t.SURFACE_ACTIVE} 与底座 {t.SURFACE} 差异过小（{delta}）")


class TestTrackListAlignment(unittest.TestCase):
    """列头与数据行必须逐列对齐（v2.1.4）。

    必须**先套用 QSS** 才测得出来：行内 ♥ / ⋯ 按钮的实际宽度由 QSS 的
    min/max-width 决定，而基础 QPushButton 规则带的 padding 会叠加进去
    （曾把 28px 撑成 48px，两个按钮多吃 40px，导致弹性列整体收缩、
    整表逐列漂移）。裸控件不带样式时尺寸恰好正确，测不出这个缺陷。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])
        from ui.theme import apply_theme
        apply_theme(cls.app, "columbina")

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet("")  # 不把样式泄漏给同进程的其他测试类

    def _aligned_pairs(self):
        from PySide6.QtGui import QPixmap
        from app.models import Track
        from ui.track_list import TrackList
        tracks = [Track(id=f"t{i}", path=f"C:/fake/{i}.mp3", title=name,
                        artist="周杰伦", album="叶惠美", duration_ms=215000, added_at=i)
                  for i, name in enumerate(["晴天", "夜曲", "晨间轻音乐", "海浪的声音"])]
        tl = TrackList()
        tl.resize(1000, 600)
        tl.show()
        tl.set_tracks(tracks, lambda _t: QPixmap(40, 40), None,
                      size_getter=lambda _t: 33_000)
        self.app.processEvents()
        row = tl.list.itemWidget(tl.list.item(0))
        head = [tl._col_header_layout.itemAt(i).widget()
                for i in range(tl._col_header_layout.count())]
        children = [row.leading, row.cover, row.title, row.artist, row.album,
                    row.fmt, row.size, row.duration, row.fav_btn, row.more_btn]
        names = ["序号", "封面", "歌曲", "艺人", "专辑", "格式", "大小", "时长", "爱心", "更多"]
        return tl, row, list(zip(names, head, children, strict=False))

    def test_columns_align_pixel_by_pixel(self):
        _tl, _row, pairs = self._aligned_pairs()
        for name, hw, rw in pairs:
            self.assertIsNotNone(hw, f"{name} 缺少列头槽位")
            self.assertEqual(hw.mapToGlobal(hw.rect().topLeft()).x(),
                             rw.mapToGlobal(rw.rect().topLeft()).x(),
                             f"{name} 列与列头未对齐")

    def test_row_buttons_match_header_slot_width(self):
        """行内按钮实际宽度必须等于列头占位槽宽度（padding 泄漏回归）。"""
        from ui.track_list import _ROWBTN_W
        _tl, row, _pairs = self._aligned_pairs()
        self.assertEqual(row.fav_btn.width(), _ROWBTN_W)
        self.assertEqual(row.more_btn.width(), _ROWBTN_W)


class TestLyricsThemeColor(unittest.TestCase):
    """歌词常态色必须跟随当前主题（不能被 import 时求值冻结）。

    曾把颜色写在类属性 `_NORMAL = QColor(TEXT_DIM)` 里：模块 import 的那一刻
    求值（当时是深色主题），之后切浅色主题仍是深灰 —— 浅色背景上对比度不足。
    改为在用的时候取 `current_theme().TEXT_DIM` 后，本组用例锁住行为。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def tearDown(self):
        from ui.theme import apply_theme
        apply_theme(self.app, "columbina")

    def _foreground_after(self, theme_name: str):
        from app.lyrics import LyricLine
        from ui.lyrics_panel import LyricsPanel
        from ui.theme import THEMES, apply_theme

        apply_theme(self.app, theme_name)
        panel = LyricsPanel()
        panel.set_synced([LyricLine(time_ms=0, text="第一行")])
        return panel.list.item(0).foreground().color().name(), THEMES[theme_name].TEXT_DIM

    def test_normal_color_follows_light_theme(self):
        actual, expected = self._foreground_after("light")
        self.assertEqual(actual.lower(), expected.lower())

    def test_normal_color_follows_columbina_theme(self):
        actual, expected = self._foreground_after("columbina")
        self.assertEqual(actual.lower(), expected.lower())

    def test_switching_theme_changes_color(self):
        """同一进程内先浅后深，颜色必须真的变化（冻结 bug 的核心表现）。"""
        light, _ = self._foreground_after("light")
        dark, _ = self._foreground_after("columbina")
        self.assertNotEqual(light, dark)

    def test_plain_lyrics_also_themed(self):
        from ui.lyrics_panel import LyricsPanel
        from ui.theme import THEMES, apply_theme

        apply_theme(self.app, "light")
        panel = LyricsPanel()
        panel.set_plain(["纯文本歌词"])
        self.assertEqual(
            panel.list.item(0).foreground().color().name().lower(),
            THEMES["light"].TEXT_DIM.lower(),
        )

    def test_empty_hint_restores_default(self):
        """临时提示（如「正在联网匹配歌词…」）之后，空状态文案必须能复原。

        曾写成「只有传了 hint 才 setText」：联网提示会永久留在面板上，
        下一首没歌词的歌也显示「正在联网匹配…」，看起来像卡死了。
        """
        from ui.lyrics_panel import EMPTY_HINT, LyricsPanel

        panel = LyricsPanel()
        panel.set_empty("正在联网匹配歌词…")
        self.assertEqual(panel.empty_label.text(), "正在联网匹配歌词…")
        panel.set_empty()
        self.assertEqual(panel.empty_label.text(), EMPTY_HINT)


class TestLyricsEffect(unittest.TestCase):
    """歌词播放动效（v2.6.4）：none/zoom/typewriter/karaoke 单选，非法值回落。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_default_and_invalid_fall_back_to_none(self):
        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        self.assertEqual(panel._effect, "none")
        panel.set_effect("bogus")
        self.assertEqual(panel._effect, "none")

    def test_set_effect_accepts_all_valid_values(self):
        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        for effect in ("zoom", "typewriter", "karaoke", "none"):
            panel.set_effect(effect)
            self.assertEqual(panel._effect, effect)

    def test_line_progress_mid_line_and_last_line(self):
        from app.lyrics import LyricLine
        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        panel.set_synced([LyricLine(0, "a"), LyricLine(2000, "b"), LyricLine(4000, "c")])
        # 第一行 0~2000ms，500ms 处进度 0.25
        self.assertAlmostEqual(panel._line_progress(0, 500), 0.25, places=2)
        # 最后一行无下一行，按固定 3000ms 行时长：5500ms 处进度 0.5
        self.assertAlmostEqual(panel._line_progress(2, 5500), 0.5, places=2)

    def test_update_position_advances_progress_for_karaoke(self):
        from app.lyrics import LyricLine
        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        panel.set_effect("karaoke")
        panel.set_synced([LyricLine(0, "第一行"), LyricLine(2000, "第二行")])
        panel.update_position(500)
        self.assertEqual(panel._current_index, 0)
        self.assertAlmostEqual(panel._progress_in_line, 0.25, places=2)

    def test_plain_mode_ignores_effect_for_current_line(self):
        """纯文本歌词没有时间轴，动效不应生效（不产生「当前行」）。"""
        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        panel.set_effect("zoom")
        panel.set_plain(["纯文本歌词"])
        panel.update_position(1000)
        self.assertEqual(panel._current_index, -1)


class TestBilingualLyricsPanel(unittest.TestCase):
    """双语歌词（v2.6.10）：一句 = 原文 + 译文，两行作为一个整体显示与动效。"""

    BILINGUAL = ["Who can surely know", "风将吹向何方",
                 "How the wind blows,", "谁也捉摸不透",
                 "When showers of notes", "当音符的骤雨",
                 "Fall like sparkles", "如星辉般洒落"]

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_plain_mode_pairs_lines(self):
        """未对齐的双语 txt 也按句显示，不是 8 行流水账。"""
        from ui.lyrics_panel import LyricsPanel, _TRANSLATION_ROLE

        panel = LyricsPanel()
        panel.set_plain(self.BILINGUAL)
        self.assertEqual(panel.list.count(), 4)
        item = panel.list.item(0)
        self.assertEqual(item.text(), "Who can surely know")
        self.assertEqual(item.data(_TRANSLATION_ROLE), "风将吹向何方")

    def test_synced_item_keeps_main_text_and_translation(self):
        """item.text() 仍是原文（兼容旧测试与 ElidedLabel 逻辑），译文另存 role。"""
        from PySide6.QtCore import Qt

        from app.lyrics import LyricLine
        from ui.lyrics_panel import LyricsPanel, _TRANSLATION_ROLE

        panel = LyricsPanel()
        panel.set_synced([LyricLine(0, "Who can surely know", "风将吹向何方"),
                          LyricLine(2000, "How the wind blows,", "谁也捉摸不透")])
        self.assertEqual(panel.list.count(), 2)
        self.assertEqual(panel.list.item(0).text(), "Who can surely know")
        self.assertEqual(panel.list.item(0).data(_TRANSLATION_ROLE), "风将吹向何方")
        self.assertEqual(panel.list.item(0).data(Qt.ItemDataRole.UserRole), 0)

    def test_item_height_grows_for_translation(self):
        """译文那一层必须有高度，否则会被裁掉半截。"""
        from app.lyrics import LyricLine
        from PySide6.QtWidgets import QStyleOptionViewItem

        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        panel.set_synced([LyricLine(0, "Who can surely know"),
                          LyricLine(2000, "Who can surely know", "风将吹向何方")])
        option = QStyleOptionViewItem()
        option.font = panel.list.font()
        model = panel.list.model()
        plain_h = panel._delegate.sizeHint(option, model.index(0, 0)).height()
        dual_h = panel._delegate.sizeHint(option, model.index(1, 0)).height()
        self.assertGreater(dual_h, plain_h)

    def test_current_sentence_highlights_whole_block(self):
        """整句一起高亮：当前句索引只需定位到「句」，译文跟着同一条目走。"""
        from app.lyrics import LyricLine
        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        panel.set_synced([LyricLine(0, "Who can surely know", "风将吹向何方"),
                          LyricLine(4000, "How the wind blows,", "谁也捉摸不透")])
        panel.update_position(4100)
        self.assertEqual(panel._current_index, 1)
        self.assertEqual(panel.list.currentRow(), -1)   # 不靠选中态渲染

    def test_typed_split_spans_both_lines(self):
        """逐字进度按两行字符总数推进：原文打完才轮到译文。"""
        from ui.lyrics_panel import _typed_split

        self.assertEqual(_typed_split(10, 6, 0.0), (0, 0))
        self.assertEqual(_typed_split(10, 6, 0.25), (4, 0))    # 16*0.25=4，都在原文
        self.assertEqual(_typed_split(10, 6, 0.625), (10, 0))  # 16*.625=10，原文刚满
        self.assertEqual(_typed_split(10, 6, 0.75), (10, 2))   # 12 字 → 译文 2 字
        self.assertEqual(_typed_split(10, 6, 1.0), (10, 6))

    def test_typed_split_without_translation(self):
        from ui.lyrics_panel import _typed_split

        self.assertEqual(_typed_split(10, 0, 0.5), (5, 0))
        self.assertEqual(_typed_split(10, 0, 1.0), (10, 0))



class TestLyricsAutoscroll(unittest.TestCase):
    """歌词自动滚动定位（v2.6.11）：当前句要滚到视口中央，且不会回跳。

    坑：`visualItemRect()` 返回**视口坐标**（随滚动变化），`bar.value()` 是**内容
    坐标**。直接把 `rect.top()` 当滚动目标会漏掉已滚过的距离 —— 每句只往前挪一点点，
    当前句永远沉在视口底部被裁掉，表现为「歌词一直往上滚动但始终滚不到位」。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def _panel(self, rows: int = 20, bilingual: bool = False):
        from app.lyrics import LyricLine
        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        panel.resize(300, 340)
        panel.show()          # 需要真实布局才有 visualItemRect
        lines = [LyricLine(i * 3000, f"Lyric line {i}",
                           f"第 {i} 句译文" if bilingual else "")
                 for i in range(rows)]
        panel.set_synced(lines)
        return panel

    def test_target_centers_item_after_already_scrolled(self):
        """滚到目标值后该项必须**真的居中**——这条直接验证语义，也覆盖「漏加 value」。

        已经滚过一段距离（value>0）时，如果目标只按视口坐标算，设过去后该项会停在
        视口下方十几行的地方，永远居不了中。
        """
        panel = self._panel()
        bar = panel.list.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0, "20 行歌词应超出一屏，否则测不到滚动")
        bar.setValue(min(150, bar.maximum()))
        item = panel.list.item(12)
        target = panel._scroll_target(item)
        bar.setValue(target)
        rect = panel.list.visualItemRect(item)
        offset = rect.top() + rect.height() // 2 - panel.list.viewport().height() // 2
        self.assertLessEqual(abs(offset), 2, f"滚到目标后应居中，实际偏差 {offset}px")

    def test_target_uses_content_coordinates(self):
        """目标必须包含当前滚动偏移（value），否则等于退回「只按视口算」的老 bug。"""
        panel = self._panel()
        bar = panel.list.verticalScrollBar()
        bar.setValue(min(150, bar.maximum()))
        item = panel.list.item(12)
        rect = panel.list.visualItemRect(item)
        target = panel._scroll_target(item)
        naive = (rect.top() + rect.height() // 2
                 - panel.list.viewport().height() // 2)
        self.assertEqual(target, bar.value() + naive)
        self.assertNotEqual(target, naive)

    def test_scroll_value_never_goes_backwards(self):
        from PySide6.QtTest import QTest

        panel = self._panel(rows=20, bilingual=True)
        bar = panel.list.verticalScrollBar()
        values = []
        for i in range(6, 14):
            panel.update_position(i * 3000 + 100)
            QTest.qWait(300)
            values.append(bar.value())
        self.assertEqual(values, sorted(values), f"滚动条回跳了：{values}")
        self.assertGreater(values[-1], values[0], "整段播放应确实向下滚动")


class TestLyricsMenu(unittest.TestCase):
    """歌词右键菜单（v2.6.12 / v2.7.0）。

    历史坑：两个对齐入口原来只差「本地 / 联网」两个字，用户点了本地那个、
    又以为跑的是联网精确对齐，于是把「本地近似」的误差当成联网对齐的 bug 报上来。
    v2.7.0 移除联网精确对齐后只保留本地近似对齐——因此断言只剩一个对齐入口、
    写明「本地近似」，不再有联网入口；偏移微调只在已有时间轴时可用。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def _panel(self, synced: bool):
        from app.lyrics import LyricLine
        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        if synced:
            panel.set_synced([LyricLine(1000, "第一句"), LyricLine(5000, "第二句")])
        else:
            panel.set_plain(["第一句", "第二句"])
        return panel

    def _actions(self, panel) -> dict:
        return {a.text(): a for a in panel._build_menu().actions()}

    def test_single_local_align_entry(self):
        """v2.7.0：只保留一个本地近似对齐入口，且不再有联网入口。"""
        labels = [t for t in self._actions(self._panel(False)) if "转成 .lrc" in t]
        self.assertEqual(len(labels), 1, f"应只有一个对齐入口：{labels}")
        self.assertIn("本地", labels[0])
        self.assertIn("近似", labels[0], "本地对齐必须写明是近似结果")
        self.assertFalse(any("联网" in t for t in labels),
                         "v2.7.0 已移除联网精确对齐，不应再有联网对齐入口")

    def test_shift_actions_disabled_without_synced_lyrics(self):
        actions = self._actions(self._panel(False))
        self.assertFalse(actions["整体提前 0.5 秒"].isEnabled())
        self.assertFalse(actions["整体延后 0.5 秒"].isEnabled())

    def test_shift_actions_emit_half_second(self):
        panel = self._panel(True)
        got = []
        panel.shift_lyrics_requested.connect(got.append)
        actions = self._actions(panel)
        self.assertTrue(actions["整体提前 0.5 秒"].isEnabled())
        actions["整体提前 0.5 秒"].trigger()
        actions["整体延后 0.5 秒"].trigger()
        self.assertEqual(got, [-500, 500])


class TestIconRendering(unittest.TestCase):
    """图标按设备像素渲染（v2.5）：高分屏上不能把 16px 位图放大糊掉。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_paint_scales_bitmap_with_dpr(self):
        from PySide6.QtGui import QColor

        from ui.icons import _paint

        base = _paint("gear", 16, QColor("#2c3552"), 1.0)
        self.assertEqual((base.width(), base.height()), (16, 16))
        self.assertAlmostEqual(base.devicePixelRatio(), 1.0)

        hidpi = _paint("gear", 16, QColor("#2c3552"), 1.5)
        self.assertEqual((hidpi.width(), hidpi.height()), (24, 24),
                         "125%/150% 屏应渲染 24 设备像素，而不是放大 16px 位图")
        self.assertAlmostEqual(hidpi.devicePixelRatio(), 1.5)

    def test_make_icon_returns_dpr_aware_pixmap(self):
        from ui.icons import device_ratio, make_icon

        dpr = device_ratio()
        icon = make_icon("gear", "#2c3552", 16)
        pixmap = icon.pixmap(16, 16)
        # 逻辑尺寸始终是 16，物理尺寸随屏幕缩放
        self.assertLessEqual(pixmap.width(), round(16 * dpr) + 1)
        self.assertGreaterEqual(pixmap.width(), 16)

    def test_gear_has_hollow_center_and_solid_ring(self):
        """齿轮必须"实心环 + 镂空轴孔"。

        `subtracted()` 写错（比如两个 QPainterPath 没交集）时会退化成实心圆，
        整窗里就变成一个点，这是 v2.2 出现过的症状。
        """
        from PySide6.QtGui import QColor

        from ui.icons import _paint

        size = 72
        img = _paint("gear", size, QColor("#000000"), 1.0).toImage()
        center = img.pixelColor(size // 2, size // 2)
        self.assertEqual(center.alpha(), 0, "轴孔必须镂空")
        ring = img.pixelColor(size // 2, size // 2 - round(size * 0.22))
        self.assertGreater(ring.alpha(), 200, "轴孔外侧应当是实心环体")
        corner = img.pixelColor(2, 2)
        self.assertEqual(corner.alpha(), 0, "图标四周必须留白")

    def test_gear_teeth_reach_near_canvas_edge(self):
        """齿顶要接近画布边缘，否则图标在按钮里显得小。"""
        from PySide6.QtGui import QColor

        from ui.icons import _paint

        size = 72
        img = _paint("gear", size, QColor("#000000"), 1.0).toImage()
        widest = max(x for x in range(size)
                     if any(img.pixelColor(x, y).alpha() > 40 for y in range(size)))
        self.assertGreaterEqual(widest, round(size * 0.92),
                                "齿顶应占到画布的 92% 以上")


    def test_moon_is_crescent_not_disc(self):
        """月亮必须是月牙：被"咬掉"的那一侧镂空，另一侧是实体。

        用 arcMoveTo + arcTo 拼两段弧会在弧端点之间连一条直线弦，月牙被削平成
        "灰色 D"；用一个圆上叠一个背景色圆则会遮住别的元素。所以这里既查「缺口
        真的透了」也查「实体那边真的实」。
        """
        from PySide6.QtGui import QColor

        from ui.icons import _paint

        size = 96
        img = _paint("moon", size, QColor("#000000"), 1.0).toImage()
        # 整体转了 -30°，缺口方向是屏幕上的右上（0.866, -0.5）
        bite = (round(size * (0.5 + 0.30 * 0.866)), round(size * (0.5 - 0.30 * 0.5)))
        body = (round(size * (0.5 - 0.30 * 0.866)), round(size * (0.5 + 0.30 * 0.5)))
        self.assertEqual(img.pixelColor(*bite).alpha(), 0, "缺月的那一侧必须镂空")
        self.assertGreater(img.pixelColor(*body).alpha(), 200, "另一侧必须是实体")

    def test_moon_fills_the_canvas(self):
        """既不裁切、也不画得太小（图标在按钮里显小的典型原因）。"""
        from PySide6.QtGui import QColor

        from ui.icons import _paint

        size = 96
        img = _paint("moon", size, QColor("#000000"), 1.0).toImage()
        xs, ys = [], []
        for y in range(size):
            for x in range(size):
                if img.pixelColor(x, y).alpha() > 40:
                    xs.append(x)
                    ys.append(y)
        self.assertGreater(min(xs), 0, "左缘贴边 → 被画布裁掉了")
        self.assertLess(max(xs), size - 1, "右缘贴边 → 被画布裁掉了")
        self.assertGreater(min(ys), 0)
        self.assertLess(max(ys), size - 1)
        # 实测（20/24/72/96 一致）：横向占 ~77~80%、纵向 ~85~90%（斜开口导致偏窄）
        self.assertGreaterEqual(max(xs) - min(xs), round(size * 0.72), "横向没占满")
        self.assertGreaterEqual(max(ys) - min(ys), round(size * 0.80), "纵向没占满")


if __name__ == "__main__":
    unittest.main()
