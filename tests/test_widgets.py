# -*- coding: utf-8 -*-
"""ElidedLabel 省略行为单测（延后省略 + full_text + 销毁安全）。"""
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
        # 主题圆钮必须在托盘上方（提到上排，整条才能收进侧栏宽度）
        self.assertLess(fb.theme_toggle.geometry().top(), fb.tray.geometry().top(),
                        "主题按钮应位于托盘上方")

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

    def test_handle_visible_on_dark(self):
        pixels = self._knob_pixels("dark", "SeekSlider", 0)
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
        list_widget.set_header("资料库", 3, 3_600_000)
        # count_label 保持原有「共 N 首」格式（E2E 依赖）
        self.assertEqual(list_widget.count_label.text(), "共 3 首")
        self.assertIn("1:00:00", list_widget.stats_label.text())
        self.assertFalse(list_widget.stats_label.isHidden())

    def test_header_hides_stats_when_empty(self):
        from ui.track_list import TrackList
        list_widget = TrackList()
        list_widget.set_header("资料库", 0, 0)
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
        apply_theme(cls.app, "dark")

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
        self.assertEqual((nav.width(), nav.height()), (46, 46))

    def test_float_bar_fits_player_bar_indent(self):
        """浮动条右端不得超过播放栏左缩进，否则压住封面（且宽度不足会被裁）。"""
        from ui.float_bar import FloatBar
        from ui.player_bar import PlayerBar
        pb = PlayerBar()
        fb = FloatBar()
        fb.adjustSize()
        self.assertLessEqual(12 + fb.sizeHint().width(),
                             pb.layout().contentsMargins().left())
        # 每个文字按钮都得有正宽度，不能因父控件过窄被裁掉
        for btn in (fb.np_btn, fb.dir_btn, fb.settings_btn):
            self.assertGreater(btn.sizeHint().width(), 40, btn.text())

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
    """浮动工具条的视觉契约（v2.1.7）。

    v2.1.2 起左下角一直是「三个孤立直角方块」：`#FloatTextBtn` 的
    border-radius 写了 16px，而按钮只有 28px 高 —— **超过短边一半时 Qt 直接
    退化成直角**（不圆、也不报错），三层之间也没有容器，看起来像三个输入框。
    这组用例钉住「一个托盘 + 圆角胶囊 + 悬停可辨」三件事。
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

    def test_entries_share_one_tray(self):
        """三个入口必须在同一个托盘容器里（否则又退回三个孤立方块）。"""
        from ui.float_bar import FloatBar
        fb = FloatBar()
        self.assertTrue(hasattr(fb, "tray"), "浮动条缺托盘容器")
        for btn in (fb.np_btn, fb.dir_btn, fb.settings_btn):
            self.assertIs(btn.parent(), fb.tray, f"{btn.text()} 不在托盘内")

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
        for btn in (fb.np_btn, fb.dir_btn, fb.settings_btn):
            # 用 minimumHeight 而不是 sizeHint：按钮高度由 setFixedHeight 钉死，
            # sizeHint 仍会按图标+文字的默认意图算（26px），量到的不是渲染高度。
            half = btn.minimumHeight() / 2
            self.assertLessEqual(radius, half,
                                 f"radius {radius}px > 半高 {half}px，会被渲染成直角")

    def test_theme_toggle_is_a_circle(self):
        """主题按钮是正圆：radius 必须接近半径（差 1px 内仍算圆）。"""
        from ui.float_bar import FloatBar
        from ui.theme import THEMES, build_stylesheet
        fb = FloatBar()
        radius = self._radius(build_stylesheet(THEMES["light"]), "QPushButton#ThemeToggle")
        side = fb.theme_toggle.minimumHeight()
        self.assertGreaterEqual(radius, side / 2 - 1, "radius 太小，圆会变成圆角方块")
        # 与托盘同高才读成同一族
        self.assertEqual(side, fb.tray.minimumHeight())

    def test_hover_fill_is_distinguishable(self):
        """悬停底色与托盘底色必须拉开差距 —— 否则鼠标划过去毫无反馈。"""
        from ui.theme import THEMES

        def rgb(c: str) -> tuple[int, int, int]:
            return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]

        for name, t in THEMES.items():
            tray, hover = rgb(t.SURFACE), rgb(t.SURFACE_ACTIVE)
            delta = max(abs(a - b) for a, b in zip(tray, hover, strict=True))
            self.assertGreaterEqual(
                delta, 12,
                f"{name} 主题悬停色 {t.SURFACE_ACTIVE} 与托盘 {t.SURFACE} 差异过小（{delta}）")


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
        apply_theme(cls.app, "dark")

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
        apply_theme(self.app, "dark")

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

    def test_normal_color_follows_dark_theme(self):
        actual, expected = self._foreground_after("dark")
        self.assertEqual(actual.lower(), expected.lower())

    def test_switching_theme_changes_color(self):
        """同一进程内先浅后深，颜色必须真的变化（冻结 bug 的核心表现）。"""
        light, _ = self._foreground_after("light")
        dark, _ = self._foreground_after("dark")
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


if __name__ == "__main__":
    unittest.main()
