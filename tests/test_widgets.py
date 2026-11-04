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
        from ui.main_window import WINDOW_MIN_WIDTH
        from ui.player_bar import PlayerBar
        pb = PlayerBar()
        # MainWindow.setMinimumSize(WINDOW_MIN_WIDTH, ...)：播放栏最小宽不得超过
        # 窗口最小宽，否则信息列被挤到 0（副标题全成「…」）、布局在约束边界反复
        # 重算导致窗口/播放栏抖动、进度手柄跟着乱跳。
        #
        # v2.8.0：这里原本写死 1100。窗口最小宽改成按布局实测值定之后，两个数字
        # 必须同源 —— 常量搬进 ui.main_window，测试直接引用，不再各自写死一遍。
        self.assertLessEqual(pb.minimumSizeHint().width(), WINDOW_MIN_WIDTH,
                             f"PlayerBar 最小宽度不能超过窗口最小宽度 {WINDOW_MIN_WIDTH}")

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
        """长标题/长艺人名不得把最小宽度顶爆（v2.1.5 复查发现 1185 > 窗口最小宽）。

        根因：ElidedLabel 继承 QLabel 的 minimumSizeHint（按完整文本算宽度），
        一首「Blazing Heart (英文版)」+ 长艺人名就足以把播放栏撑到 1185px，
        超过窗口最小宽 → 信息列被挤空、布局反复重算导致抖动。
        """
        from PySide6.QtGui import QPixmap
        from ui.main_window import WINDOW_MIN_WIDTH
        from ui.player_bar import PlayerBar
        pb = PlayerBar()
        cover = QPixmap(48, 48)
        pb.update_track("Blazing Heart (英文版) - 原神-灼火之心 特别收录版",
                        "Chrissy Costanza/HOYO-MiX/上海爱乐乐团", cover)
        self.assertLessEqual(pb.minimumSizeHint().width(), WINDOW_MIN_WIDTH,
                             f"长标题下 PlayerBar 最小宽度仍不得超过 {WINDOW_MIN_WIDTH}")

    def test_title_keeps_readable_width_at_min_window(self):
        """窗口缩到最小时，播放栏标题列不能被挤成几个像素（v2.8.0）。

        事故背景：把窗口默认尺寸调小之后，1044 宽下标题列只剩 44px ——
        「周杰伦」都显示成了「周杰伦…」。根因是进度条固定 200 宽，窗口一窄，
        被压缩的全是那条弹性最低的标题列。改成进度条弹性（120~200）后，
        窄窗时它先让位，标题列回到 84px。
        """
        from PySide6.QtGui import QPixmap
        from ui.main_window import WINDOW_MIN_WIDTH
        from ui.player_bar import PLAYER_BAR_HEIGHT, PlayerBar

        pb = PlayerBar()
        pb.show()
        pb.update_track("夜曲", "周杰伦", QPixmap(48, 48))
        pb.resize(WINDOW_MIN_WIDTH, PLAYER_BAR_HEIGHT)
        for _ in range(3):
            self.app.processEvents()
        try:
            self.assertGreaterEqual(
                pb.title.width(), 60,
                f"最小窗口下标题列只剩 {pb.title.width()}px，歌名会被截成一个字")
            # 进度条让位但不能塌：120 是它能收到的最小值
            self.assertGreaterEqual(pb.seek_slider.width(), 120)
            self.assertLessEqual(pb.seek_slider.width(), 200)
        finally:
            pb.close()

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
    def _is_saturated_accent(c) -> bool:
        """强调色实心圆：颜色要有明显饱和度（红/蓝任一主导），不是白/灰/底色。

        浅色主题的强调色是陶土橙、深色是长春花紫，两者都满足「主通道远高于
        其他通道 + 足够亮」；底色/轨道/白心都是低饱和的灰白，会被排除。
        """
        r, g, b = c.red(), c.green(), c.blue()
        return max(r, g, b) - min(r, g, b) > 40 and max(r, g, b) > 120

    def test_handle_visible_on_light(self):
        pixels = self._knob_pixels("light", "SeekSlider", 0)
        self.assertTrue(any(self._is_saturated_accent(c) for c in pixels),
                        "进度手柄应绘制为强调色实心圆，不能在浅色底上隐形")

    def test_handle_visible_on_columbina(self):
        pixels = self._knob_pixels("columbina", "SeekSlider", 0)
        self.assertTrue(any(self._is_saturated_accent(c) for c in pixels),
                        "深色主题下进度手柄同样必须是强调色实心圆")

    def test_volume_handle_visible_on_light(self):
        pixels = self._knob_pixels("light", "VolumeSlider", 0)
        self.assertTrue(any(self._is_saturated_accent(c) for c in pixels),
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
        self.assertFalse(self._is_saturated_accent(corner),
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
    """歌词播放动效：none/typewriter/karaoke 单选，非法值回落（v3.2.1 去掉 zoom）。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_default_and_invalid_fall_back_to_none(self):
        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        self.assertEqual(panel._effect, "none")
        panel.set_effect("bogus")
        self.assertEqual(panel._effect, "none")

    def test_removed_zoom_falls_back_to_none(self):
        """v3.2.1 删掉 zoom：老配置/老调用传进来必须安静地退成 none，不能崩。"""
        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        panel.set_effect("karaoke")
        panel.set_effect("zoom")
        self.assertEqual(panel._effect, "none", "zoom 已不是合法值，应回退 none")

    def test_set_effect_accepts_all_valid_values(self):
        from app.models import LYRICS_EFFECTS
        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        for effect in LYRICS_EFFECTS:
            panel.set_effect(effect)
            self.assertEqual(panel._effect, effect)

    def test_current_line_always_enlarged_regardless_of_effect(self):
        """v3.2.1：放大是默认行为，与动效无关。

        `_line_delta()` 签名里根本没有 effect 参数 —— 结构上就不可能再依赖动效。
        这里再钉一层：三档动效下当前行的增量都必须一样且 > 0。
        """
        from app.models import LYRICS_EFFECTS
        from ui.lyrics_panel import _CURRENT_DELTA, _line_delta

        self.assertGreater(_CURRENT_DELTA, 0)
        for _effect in LYRICS_EFFECTS:
            self.assertEqual(_line_delta(True), _CURRENT_DELTA)
            self.assertEqual(_line_delta(False), 0)

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
        panel.set_effect("karaoke")
        panel.set_plain(["纯文本歌词"])
        panel.update_position(1000)
        self.assertEqual(panel._current_index, -1)


class TestLyricsColor(unittest.TestCase):
    """歌词颜色覆盖（v2.9.0）：配置下发 / 逐句色 / 相位 / 动画定时器门控。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def _panel(self, trigger="progress", **kw):
        from app.lyrics import LyricLine
        from app.models import LyricsColorConfig
        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        panel.set_synced([LyricLine(1000, "第一句"), LyricLine(5000, "第二句")])
        cfg = LyricsColorConfig(enabled=True, trigger=trigger,
                                color_a="#ff6b9d", color_b="#7f7bff", **kw)
        panel.set_color_config(cfg)
        return panel

    def test_disabled_config_keeps_old_path(self):
        from app.models import LyricsColorConfig
        from ui.lyrics_panel import LyricsPanel

        panel = LyricsPanel()
        panel.set_synced([])
        panel.set_color_config(LyricsColorConfig(enabled=False))
        self.assertIsNone(panel._active_color_cfg(), "关闭时必须走旧渲染分支")

    def test_row_colors_use_configured_pair(self):
        panel = self._panel()
        a, b = panel._row_colors(0)
        self.assertEqual(a.name(), "#ff6b9d")
        self.assertEqual(b.name(), "#7f7bff")

    def test_per_line_color_overrides_global(self):
        panel = self._panel()
        panel.set_line_colors({5000: "#00ff00"})
        a, _b = panel._row_colors(1)
        self.assertEqual(a.name(), "#00ff00", "逐句色应覆盖全局色")
        a0, _ = panel._row_colors(0)
        self.assertEqual(a0.name(), "#ff6b9d", "没设逐句色的行仍用全局色")

    def test_single_color_mode_collapses_gradient(self):
        panel = self._panel(gradient=False)
        a, b = panel._row_colors(0)
        self.assertEqual(a.name(), b.name(), "单色模式两端颜色应相同")

    def test_empty_color_a_follows_theme_accent(self):
        from PySide6.QtGui import QColor

        from app.models import LyricsColorConfig

        panel = self._panel()
        panel.set_color_config(LyricsColorConfig(enabled=True, color_a="", color_b=""))
        a, _b = panel._row_colors(0)
        from ui.theme import ACCENT
        self.assertEqual(a.name(), QColor(ACCENT).name(), "留空应跟随主题强调色")

    def test_phase_depends_on_trigger(self):
        panel = self._panel(trigger="progress")
        self.assertAlmostEqual(panel._color_phase(0.4), 0.4, places=3)
        panel._anim_phase = 0.7
        panel.set_color_config(type(panel._color_cfg)(
            enabled=True, trigger="time", color_a="#ff6b9d"))
        self.assertAlmostEqual(panel._color_phase(0.4), panel._anim_phase, places=3)

    def test_time_mode_timer_follows_visibility(self):
        panel = self._panel(trigger="time")
        self.assertFalse(panel._color_timer.isActive(), "未显示时不该空转")
        panel.show()
        self.assertTrue(panel._color_timer.isActive(), "时间模式显示后应启动动画")
        panel.hide()
        self.assertFalse(panel._color_timer.isActive(), "隐藏后必须停掉动画")

    def test_progress_mode_never_starts_timer(self):
        panel = self._panel(trigger="progress")
        panel.show()
        self.assertFalse(panel._color_timer.isActive(), "进度模式由播放位置驱动，不需定时器")
        panel.hide()

    def test_tick_stops_when_disabled(self):
        from app.models import LyricsColorConfig

        panel = self._panel(trigger="time")
        panel.set_color_config(LyricsColorConfig(enabled=False))
        panel._on_color_tick()
        self.assertFalse(panel._color_timer.isActive())

    def test_bilingual_translation_shares_pair_and_scans_in_sync(self):
        """v2.9.1/v2.9.2：译文行与原文**同色**，且逐字扫光**同步**推进。

        踩坑一（v2.9.1）：译文被压 alpha 205 当次级色，浅色主题下洗成灰紫 →
        改为一律复用原文的 pair，层级只靠字号（-3px）。
        踩坑二（v2.9.2）：karaoke 的逐字进度按「两行字符总数」推进，英文原句长、
        中文译文短，扫光要走完全句七成以后才轮到译文；那之前译文整行都是
        `_dimmed(pair[0])` 的暗色单色 → 用户看到的就是「带翻译的歌词不会一起变色」。
        现在 karaoke 走 `sync=True`：两行各按自己的长度乘同一个进度，一起扫。
        """
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QImage, QPainter

        from app.lyrics import LyricLine
        from ui.lyrics_panel import _LyricDelegate

        main_text = "Let's go, hit that pedal"      # 24 字
        sub_text = "出发，油门踩到底"                  # 8 字

        panel = self._panel()
        panel.set_synced([LyricLine(0, main_text, sub_text)])
        panel.set_effect("karaoke")
        panel._current_index = 0
        panel._progress_in_line = 0.5

        calls = []
        original = _LyricDelegate._draw_line

        def spy(self_, *args, **kwargs):
            calls.append((args[2], args[6], kwargs))   # 文本 / 已显示字数 / 其余实参

        _LyricDelegate._draw_line = spy
        try:
            img = QImage(400, 80, QImage.Format.Format_ARGB32)
            painter = QPainter(img)
            panel._delegate._paint_block(
                painter, QRect(0, 0, 400, 72), main_text, sub_text,
                panel.list.font(), True, 0)
            painter.end()
        finally:
            _LyricDelegate._draw_line = original

        self.assertEqual(len(calls), 2, "原文与译文各画一次")
        _main_text, main_typed, main_kw = calls[0]
        _sub_text, sub_typed, sub_kw = calls[1]

        self.assertIsNotNone(main_kw.get("pair"), "当前句原文必须带颜色覆盖")
        self.assertEqual([(c.name(), c.alpha()) for c in sub_kw["pair"]],
                         [(c.name(), c.alpha()) for c in main_kw["pair"]],
                         "译文必须与原文同色同透明度，不能再压成次级色")

        self.assertEqual(main_typed, 12)
        self.assertEqual(sub_typed, 4, "译文要按自身长度同步扫，不能还是 0")
        self.assertGreater(sub_kw["band"][0], main_kw["band"][0],
                           "两行各用自己的纵向 band 做渐变轴")

    def test_karaoke_sync_typewriter_staggered(self):
        """karaoke 同步推进，typewriter 保留「原文打完再打译文」的连打节奏。"""
        from ui.lyrics_panel import _typed_split

        self.assertEqual(_typed_split(24, 8, 0.5, sync=True), (12, 4))
        self.assertEqual(_typed_split(24, 8, 0.5), (16, 0))
        self.assertEqual(_typed_split(24, 8, 1.0, sync=True), (24, 8))
        self.assertEqual(_typed_split(24, 0, 0.5, sync=True), (12, 0),
                         "单语歌词两模式必须一致")

    def test_flow_uses_each_line_band(self):
        """v2.9.1：vertical/diagonal 的渐变轴要用**本行**上下边界。

        原先传整条 item 的 rect，双语时译文行只能取到渐变的下半段，退化成单色。
        """
        from PySide6.QtGui import QColor

        from ui.lyrics_panel import _LyricDelegate

        pair = (QColor("#ff0000"), QColor("#00ff00"))
        grad = _LyricDelegate._flow((100.0, 120.0), 10.0, 200.0, pair, "vertical", 0.5)
        self.assertAlmostEqual(grad.start().y(), 100.0)
        self.assertAlmostEqual(grad.finalStop().y(), 120.0)

        flat = _LyricDelegate._flow((100.0, 120.0), 10.0, 200.0, pair, "horizontal", 0.5)
        self.assertAlmostEqual(flat.start().x(), 10.0)
        self.assertAlmostEqual(flat.finalStop().x(), 210.0)
        self.assertAlmostEqual(flat.start().y(), flat.finalStop().y(),
                               msg="horizontal 渐变轴必须水平")

    # ---------- v3.0.0 逐字时间轴接入 ----------

    def test_typed_from_words_uses_real_window(self):
        """逐字时间轴：`typed` 按真实字时间窗算，不再假设字与字匀速。

        这句 8 个字里，前 4 个字挤在 0~800ms、后 4 个拖到 800~4000ms。
        按句内线性插值，t=2000（句内 50%）会报 4 字；按真实窗口应仍停在第 4 字
        —— 因为第 5 字要 800ms 才开始，第 6 字才到 1600ms。这正是「拖腔」场景。
        """
        from app.lyrics import WordSpan
        from ui.lyrics_panel import _typed_from_words

        words = (WordSpan(0, 200, "谁"), WordSpan(200, 400, "也"),
                 WordSpan(400, 600, "捉"), WordSpan(600, 800, "摸"),
                 WordSpan(800, 2000, "不"), WordSpan(2000, 3000, "透"),
                 WordSpan(3000, 3500, "啊"), WordSpan(3500, 4000, "呀"))
        text = "谁也捉摸不透啊呀"
        self.assertEqual(_typed_from_words(words, text, 0, 4000), 0)
        self.assertEqual(_typed_from_words(words, text, 700, 4000), 4,
                         "第 5 字 800ms 才开始，700ms 时只能亮 4 个")
        self.assertEqual(_typed_from_words(words, text, 2400, 4000), 5,
                         "2400ms 在第 6 字窗口(2000~3000)的 40% 处 → "
                         "5 个字已过完 + round(1×0.4)=0 → 5")
        self.assertEqual(_typed_from_words(words, text, 4000, 4000), 8)
        self.assertEqual(_typed_from_words(words, text, 9999, 4000), 8,
                         "超出整句 → 整行已唱完")

    def test_typed_from_words_partial_word_rounds(self):
        """词元内按比例折算：一个 2 字词元走到 60% 只亮 1 个字。"""
        from app.lyrics import WordSpan
        from ui.lyrics_panel import _typed_from_words

        words = (WordSpan(0, 1000, "故事"),)
        self.assertEqual(_typed_from_words(words, "故事", 200, 1000), 0)
        self.assertEqual(_typed_from_words(words, "故事", 600, 1000), 1)
        self.assertEqual(_typed_from_words(words, "故事", 800, 1000), 2)

    def test_typed_from_words_last_span_unknown_end(self):
        """末字「终点未知」用行尾兜底，不能当零长度直接跳完。"""
        from app.lyrics import WordSpan
        from ui.lyrics_panel import _typed_from_words

        words = (WordSpan(0, 500, "故"), WordSpan(500, 0, "事"))
        self.assertEqual(_typed_from_words(words, "故事", 500, 1500), 1)
        self.assertEqual(_typed_from_words(words, "故事", 1000, 1500), 2)

    def test_typed_from_words_rejects_broken_data(self):
        """时间倒退 / 空数据 → 返回 None，调用方回退线性插值（坏 sidecar 不许乱跳）。"""
        from app.lyrics import WordSpan
        from ui.lyrics_panel import _typed_from_words

        bad = (WordSpan(500, 600, "故"), WordSpan(100, 200, "事"))
        self.assertIsNone(_typed_from_words(bad, "故事", 300, 2000))
        self.assertIsNone(_typed_from_words((), "故事", 300, 2000))
        self.assertIsNone(_typed_from_words(bad, "", 300, 2000))

    def test_typed_from_words_compresses_drag(self):
        """拖音压缩（v3.0.7）：单个字窗超上限时按上限走完并顺延，不卡在一个字上。

        实测现场《唯有追赶风的方向》"Freely, aloud~~~~"：whisper 把整段拖音算给了
        'u'（4770ms），旧实现扫光在 'u' 上卡 4.8 秒，用户看到的就是「这句唱完了，
        歌词却卡在中间不动，很久才切下一句」。
        """
        from app.lyrics import WordSpan
        from ui.lyrics_panel import _typed_from_words

        # "aloud"：'u' 占 600~5370（4770ms 拖音），'d' 在拖音末尾收尾
        words = (WordSpan(0, 100, "a"), WordSpan(100, 600, "lo"),
                 WordSpan(600, 5370, "u"), WordSpan(5370, 5450, "d"))
        text = "aloud"
        self.assertEqual(_typed_from_words(words, text, 0), 0)
        self.assertEqual(_typed_from_words(words, text, 600), 3, "a+lo 已过完")
        self.assertEqual(_typed_from_words(words, text, 1200), 4,
                         "'u' 压缩到 1200ms，走到中点只亮出 'alou'")
        self.assertEqual(_typed_from_words(words, text, 1880), 5,
                         "压缩后的有效终点：整句走完")
        self.assertEqual(_typed_from_words(words, text, 3000), 5,
                         "拖音剩余时间整句保持高亮 —— 旧实现在这里还是 4（卡住）")
        self.assertEqual(_typed_from_words(words, text, 5370), 5,
                         "'d' 的真实起点也已是整句完成态")

    def test_typed_from_words_drag_boundary_keeps_normal_line(self):
        """字窗都不超上限的行，压缩逻辑零影响（边界值 = 上限也不压）。"""
        from app.lyrics import WordSpan
        from ui.lyrics_panel import _typed_from_words

        # 最大字窗正好 1200ms（等于上限，不触发压缩）
        words = (WordSpan(0, 300, "谁"), WordSpan(300, 600, "也"),
                 WordSpan(600, 1800, "捉"))
        text = "谁也捉"
        self.assertEqual(_typed_from_words(words, text, 600), 2)
        self.assertEqual(_typed_from_words(words, text, 900), 2,
                         "600~1200 是 '捉' 的前半段，按真实比例仍是 2 字")
        self.assertEqual(_typed_from_words(words, text, 1200), 3)
        self.assertEqual(_typed_from_words(words, text, 1800), 3)

    def test_paint_block_prefers_word_times(self):
        """有逐字数据时 `_paint_block` 用字时间窗；译文按同比例推进。

        注意用**等长字窗**构造（每个 600ms，都不触发 v3.0.7 的拖音压缩）：
        验证的是「真实字窗优先于线性插值」——线性插值在 37.5% 处只亮 2 字，
        真实字窗已亮到第 5 字，二者可区分。
        """
        from app.lyrics import LyricLine, WordSpan

        text, sub = "谁也捉摸不透", "nobody knows"
        panel = self._panel()
        # 两句：句边界 1000~5000；进度 0.375 → 位置 2500ms
        panel.set_synced([LyricLine(1000, text, sub,
                                    words=(WordSpan(1000, 1600, "谁也"),
                                           WordSpan(1600, 2200, "捉摸"),
                                           WordSpan(2200, 2800, "不透"))),
                          LyricLine(5000, "下一句")])
        panel.set_effect("karaoke")
        panel._current_index = 0
        panel._progress_in_line = 0.375

        calls = self._spy_draw(panel, text, sub)
        main_typed, sub_typed = calls[0][1], calls[1][1]
        self.assertEqual(main_typed, 5,
                         "2500ms 在「不透」窗口(2200~2800)的 50% 处 → "
                         "4 个字已过完 + round(2×0.5)=1 → 5（线性插值只有 2）")
        self.assertEqual(sub_typed, round(len(sub) * main_typed / len(text)),
                         "译文按原文比例同步推进")

    def test_paint_block_without_words_keeps_v2_9_2(self):
        """无逐字数据时输出必须与 v2.9.2 逐字节一致（零回归硬约束）。"""
        from app.lyrics import LyricLine
        from ui.lyrics_panel import _typed_split

        text, sub = "Let's go, hit that pedal", "出发，油门踩到底"
        panel = self._panel()
        panel.set_synced([LyricLine(1000, text, sub)])
        panel.set_effect("karaoke")
        panel._current_index = 0
        panel._progress_in_line = 0.5

        calls = self._spy_draw(panel, text, sub)
        self.assertEqual((calls[0][1], calls[1][1]), _typed_split(len(text), len(sub),
                                                                 0.5, sync=True))

    def _spy_draw(self, panel, text, sub):
        """拦 `_draw_line`，记录每行的 (文本, typed, 其余实参)。"""
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QImage, QPainter

        from ui.lyrics_panel import _LyricDelegate

        calls = []
        original = _LyricDelegate._draw_line

        def spy(self_, *args, **kwargs):
            calls.append((args[2], args[6], args, kwargs))

        _LyricDelegate._draw_line = spy
        try:
            img = QImage(600, 90, QImage.Format.Format_ARGB32)
            painter = QPainter(img)
            panel._delegate._paint_block(
                painter, QRect(0, 0, 600, 80), text, sub,
                panel.list.font(), True, 0)
            painter.end()
        finally:
            _LyricDelegate._draw_line = original
        return calls


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

    # ---------- v3.0.0 AI 逐字对齐入口 ----------

    def test_ai_align_requires_synced_lyrics(self):
        """AI 对齐只做「字级」：没有行时间轴时入口必须置灰，别让人点了没反应。"""
        plain = self._actions(self._panel(False))
        self.assertIn("AI 对齐歌词（逐字）", plain)
        self.assertFalse(plain["AI 对齐歌词（逐字）"].isEnabled())
        synced = self._actions(self._panel(True))
        self.assertTrue(synced["AI 对齐歌词（逐字）"].isEnabled())

    def test_ai_align_label_states_precision(self):
        """文案要写清「逐字」，否则和「本地近似对齐」分不清哪个更准。"""
        label = next(t for t in self._actions(self._panel(True)) if t.startswith("AI 对齐"))
        self.assertIn("逐字", label)
        self.assertNotIn("近似", label)

    def test_ai_align_emits_signal(self):
        """点右键子菜单里的语言项要发出信号，且带出所选语言（v3.0.3）。"""
        panel = self._panel(True)
        got = []
        panel.align_ai_requested.connect(got.append)
        submenu = self._actions(panel)["AI 对齐歌词（逐字）"].menu()
        subs = {a.text(): a for a in submenu.actions()}
        subs["自动识别语言"].trigger()
        subs["按英文识别"].trigger()
        self.assertEqual(got, ["auto", "en"])

    def test_words_clear_emits_and_gates_on_synced(self):
        panel = self._panel(True)
        got = []
        panel.words_clear_requested.connect(lambda: got.append(1))
        self._actions(panel)["清除本曲逐字数据"].trigger()
        self.assertEqual(got, [1])
        self.assertFalse(self._actions(self._panel(False))["清除本曲逐字数据"].isEnabled())


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


class TestNowPlayingLayout(unittest.TestCase):
    """正在播放页分栏（v2.8.1）。

    需求来源：「左边显示太大，右边歌词显示不全」。两个独立成因：
    1. 封面写死 280×280，在 639 高的窗口里占掉内容区高度的 55%；
    2. 左列是一串普通 QLabel，长标题的 minimumSizeHint（实测 444px）把左列顶住，
       于是歌词只剩 268px —— 而歌词是居中绘制、不折行不省略的，长句直接被裁。

    这里不碰 MainWindow：`_AudioView` 自己就能建，不产生 QMediaPlayer。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def _view(self, w=796, h=507):
        from ui.now_playing import _AudioView

        view = _AudioView()
        view.resize(w, h)
        view.show()
        for _ in range(3):
            self.app.processEvents()
        return view

    def test_cover_is_capped_and_shrinks_with_view(self):
        from ui.now_playing import _COVER_MAX

        view = self._view()
        try:
            self.assertLessEqual(view.cover.width(), _COVER_MAX,
                                 "封面不能超过上限，否则窄窗下又是「左边太大」")
            self.assertEqual(view.cover.width(), view.cover.height(), "封面必须是正方形")
        finally:
            view.close()

    def test_left_column_is_exactly_cover_width(self):
        """左列宽度必须等于封面边长 —— 这是「歌词拿剩余宽度」的结构保证。"""
        view = self._view()
        try:
            self.assertEqual(view.left_box.width(), view.cover.width())
        finally:
            view.close()

    def test_lyrics_gets_the_rest_of_the_width(self):
        """796 宽视图里歌词至少要拿到 480px（修复前只有 268）。"""
        view = self._view()
        try:
            self.assertGreaterEqual(view.lyrics.width(), 480,
                                    f"歌词只分到 {view.lyrics.width()}px，右侧会被裁")
        finally:
            view.close()

    def test_long_title_does_not_push_lyrics(self):
        """长标题只许在自己的框里折行，不许把歌词挤窄（v2.8.1 的核心回归）。"""
        view = self._view()
        try:
            before = view.lyrics.width()
            view.title.setText("唯有追赶风的方向 (Only By Chasing the Wind)")
            view.artist.setText("知更鸟/HOYO-MiX/Chevy")
            for _ in range(3):
                self.app.processEvents()
            self.assertEqual(view.lyrics.width(), before,
                             "长标题把歌词挤窄了 —— 左列没定宽或标题没开 wordWrap")
            self.assertEqual(view.left_box.width(), view.cover.width())
        finally:
            view.close()


class TestWindowSize(unittest.TestCase):
    """窗口初始/最小尺寸（v2.8.0）。

    需求来源：「屏幕这个占比太大了」—— 原来写死 resize(1280, 800)，
    在 1920×1080@125%（逻辑可用区 1536×864）上一开就占 83%×93%。
    `initial_window_size` 是纯函数，喂不同屏幕就能验全部边界。
    """

    def _calc(self, w, h):
        from PySide6.QtCore import QSize
        from ui.main_window import initial_window_size
        return initial_window_size(QSize(w, h))

    def test_common_screen_is_about_two_thirds(self):
        """1536×864（1080p@125%）= 社区最常见的笔记本屏，应落在 65%~75%。"""
        size = self._calc(1536, 864)
        self.assertEqual((size.width(), size.height()), (1044, 639))
        self.assertLessEqual(size.width() / 1536, 0.72)
        self.assertLessEqual(size.height() / 864, 0.78)

    def test_never_smaller_than_minimum(self):
        """小屏（1024×600）也要托底到最小尺寸，不能算出比最小还小的窗口。"""
        from ui.main_window import WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH
        size = self._calc(1024, 600)
        self.assertGreaterEqual(size.width(), WINDOW_MIN_WIDTH)
        self.assertGreaterEqual(size.height(), WINDOW_MIN_HEIGHT)

    def test_never_larger_than_available(self):
        """可用区足够大时，结果不得溢出屏幕。"""
        for w, h in ((1536, 864), (1920, 1040), (2560, 1400), (3840, 2100)):
            size = self._calc(w, h)
            self.assertLessEqual(size.width(), w)
            self.assertLessEqual(size.height(), h)

    def test_big_screen_is_capped(self):
        """4K 屏不许开成一堵墙：宽高都要被上限截住。"""
        from ui.main_window import WINDOW_MAX_HEIGHT, WINDOW_MAX_WIDTH
        size = self._calc(3840, 2100)
        self.assertEqual((size.width(), size.height()),
                         (WINDOW_MAX_WIDTH, WINDOW_MAX_HEIGHT))

    def test_ratio_applies_between_floor_and_ceiling(self):
        """中间尺寸（1920 无缩放）走比例，而不是撞上下限。"""
        from ui.main_window import (
            WINDOW_H_RATIO, WINDOW_MAX_HEIGHT, WINDOW_MAX_WIDTH,
            WINDOW_MIN_HEIGHT, WINDOW_MIN_WIDTH, WINDOW_W_RATIO,
        )
        size = self._calc(1920, 1040)
        self.assertEqual(size.width(), int(1920 * WINDOW_W_RATIO))
        self.assertEqual(size.height(), int(1040 * WINDOW_H_RATIO))
        self.assertLess(size.width(), WINDOW_MAX_WIDTH)
        self.assertGreater(size.width(), WINDOW_MIN_WIDTH)
        self.assertLess(size.height(), WINDOW_MAX_HEIGHT)
        self.assertGreater(size.height(), WINDOW_MIN_HEIGHT)


class TestCoverSide(unittest.TestCase):
    """正在播放页封面边长（v2.8.1，纯函数）。"""

    def _side(self, w, h):
        from ui.now_playing import cover_side_for
        return cover_side_for(w, h)

    def test_typical_view_uses_ratio(self):
        # 1044 窗口 → 视图 796×507；实测封面 206（修复前写死 280）
        self.assertEqual(self._side(796, 507), 206)

    def test_capped_on_large_view(self):
        from ui.now_playing import _COVER_MAX
        self.assertEqual(self._side(1400, 900), _COVER_MAX)

    def test_floor_keeps_cover_readable(self):
        from ui.now_playing import _COVER_MIN
        self.assertGreaterEqual(self._side(300, 200), _COVER_MIN)

    def test_short_window_gives_way(self):
        """矮窗口下封面必须先让位，否则标题/艺人被挤出可视区。"""
        from ui.now_playing import _COVER_MIN
        for h in (400, 480, 507, 620):
            side = self._side(1200, h)
            self.assertLessEqual(side, max(_COVER_MIN, int(h * 0.44)),
                                 f"h={h} 时封面 {side} 超出高度预算")

    def test_monotonic_with_view_size(self):
        """视图变大，封面不该变小（防止比例写反）。"""
        sides = [self._side(600 + 100 * i, 500 + 60 * i) for i in range(6)]
        self.assertEqual(sides, sorted(sides))


class TestDropIndicatorPreview(unittest.TestCase):
    """v3.2.0 拖拽排序的「实时预览位置」：落点 → 插入行的换算 + 自绘那条线。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def _list(self):
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QListWidgetItem
        from ui.track_list import _TrackListWidget

        widget = _TrackListWidget()
        widget.resize(420, 300)
        for i in range(3):
            item = QListWidgetItem(f"row{i}")
            item.setSizeHint(QSize(400, 40))
            widget.addItem(item)
        widget.show()
        self.app.processEvents()
        return widget

    def test_row_at_top_half_inserts_before(self):
        from PySide6.QtCore import QPoint
        widget = self._list()
        try:
            rect = widget.visualItemRect(widget.item(0))
            row = widget._row_at(QPoint(20, rect.top() + 2))
            self.assertEqual(row, 0, "落在上半行 → 插到这一行之前")
        finally:
            widget.deleteLater()

    def test_row_at_bottom_half_inserts_after(self):
        from PySide6.QtCore import QPoint
        widget = self._list()
        try:
            rect = widget.visualItemRect(widget.item(0))
            row = widget._row_at(QPoint(20, rect.bottom() - 2))
            self.assertEqual(row, 1, "落在下半行 → 插到这一行之后")
        finally:
            widget.deleteLater()

    def test_row_at_empty_area_appends(self):
        from PySide6.QtCore import QPoint
        widget = self._list()
        try:
            bottom = widget.viewport().height() - 3
            self.assertEqual(widget._row_at(QPoint(20, bottom)), 3,
                             "空白区 → 放到末尾")
        finally:
            widget.deleteLater()

    def test_paint_with_drop_row_does_not_crash(self):
        """自绘插入线必须能安全重绘（QPainter 目标/坐标写错这里会崩或抛异常）。"""
        widget = self._list()
        try:
            for row in (None, 0, 1, 3):
                widget._drop_row = row
                pixmap = widget.grab()          # 触发 paintEvent
                self.assertFalse(pixmap.isNull())
        finally:
            widget.deleteLater()

    def test_native_indicator_disabled(self):
        """原生 drop indicator 必须关掉：它画在行控件底下看不见，还会和自绘那条打架。"""
        widget = self._list()
        try:
            self.assertFalse(widget.showDropIndicator())
        finally:
            widget.deleteLater()


class TestSidebarLyricsPanelToggle(unittest.TestCase):
    """侧边栏「歌词面板」切换行（v3.4.1）。

    这个按钮的文字就是状态出口：设置页里改、侧栏里点，都必须落到同一句话上，
    否则会出现「设置里写着视觉面板、侧栏还写着原生」的自相矛盾。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_click_emits_toggle(self):
        from ui.sidebar import Sidebar
        sb = Sidebar()
        hits = []
        sb.lyrics_panel_toggle.connect(lambda: hits.append(1))
        sb.panel_btn.click()
        self.assertEqual(len(hits), 1, "点一次只该切一次，不能重复发信号")

    def test_mode_written_into_text_and_active(self):
        from ui.sidebar import Sidebar
        sb = Sidebar()
        sb.set_lyrics_panel_mode("jizura")
        self.assertIn("视觉", sb.panel_btn.text())
        self.assertEqual(sb.panel_btn.property("active"), "true")
        sb.set_lyrics_panel_mode("native")
        self.assertIn("原生", sb.panel_btn.text())
        self.assertEqual(sb.panel_btn.property("active"), "false")


if __name__ == "__main__":
    unittest.main()
