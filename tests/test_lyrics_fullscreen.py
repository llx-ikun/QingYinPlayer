# -*- coding: utf-8 -*-
"""全屏歌词浮层（v3.4.3）：搬运/交还、Esc 退出、幂等。

这里**不启动 QtWebEngine**：浮层本身对「搬来的是谁」没有假设，用普通 QWidget
就能把真正的风险点钉死 —— 面板有没有真的从原布局摘走、退出后有没有被交还、
重复进出会不会把面板弄丢（丢了就是「全屏一次，歌词永久消失」这种事故）。
"""
from __future__ import annotations

import sys
import unittest

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QWidget


def _ensure_app():
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication(sys.argv[:1])
    return _app


class TestLyricsFullscreenWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = _ensure_app()

    def setUp(self):
        from ui.lyrics_fullscreen import LyricsFullscreenWindow

        self.win = LyricsFullscreenWindow()
        self.host = QWidget()
        self.layout = QHBoxLayout(self.host)
        self.panel = QWidget()
        self.layout.addWidget(self.panel)
        self.restored: list = []

    def tearDown(self):
        self.win.leave()
        self.win.deleteLater()
        self.host.deleteLater()

    def _enter(self):
        self.win.enter(self.panel, lambda p: self.restored.append(p))
        return self.win

    # ---------- 搬运 / 交还 ----------

    def test_enter_moves_panel_into_overlay(self):
        self.assertFalse(self.win.active)
        self._enter()
        self.assertTrue(self.win.active)
        self.assertIs(self.panel.parent(), self.win)
        self.assertEqual(self.layout.count(), 0)   # 原布局里已摘走

    def test_leave_restores_panel_via_callback(self):
        self._enter()
        self.win.leave()
        self.assertFalse(self.win.active)
        self.assertEqual(self.restored, [self.panel])
        self.assertIsNone(self.panel.parent())     # 交还后由调用方接管
        self.assertFalse(self.win.isVisible())

    def test_leave_is_idempotent(self):
        self._enter()
        self.win.leave()
        self.win.leave()                           # 再喊一次不能崩、不能再回调
        self.assertEqual(len(self.restored), 1)

    def test_enter_twice_keeps_single_owner(self):
        self._enter()
        self.win.enter(self.panel, lambda p: None)  # 重复进入应是 no-op
        self.assertIs(self.panel.parent(), self.win)
        self.assertEqual(len(self.restored), 0)

    # ---------- 键盘 / 关闭 ----------

    def test_escape_emits_exited(self):
        self._enter()
        got = []
        self.win.exited.connect(lambda: got.append(1))
        self.win.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(got, [1])

    def test_f11_emits_exited(self):
        self._enter()
        got = []
        self.win.exited.connect(lambda: got.append(1))
        self.win.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F11, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(got, [1])

    def test_close_while_active_defers_to_exited(self):
        """Alt+F4 之类：不能直接把面板吞掉，要先通知调用方交还。"""
        self._enter()
        got = []
        self.win.exited.connect(lambda: got.append(1))
        self.win.closeEvent(QEvent(QEvent.Type.Close))
        self.assertEqual(got, [1])
        self.assertTrue(self.win.active)           # 等调用方 leave()


class TestStackRoundTrip(unittest.TestCase):
    """真实形态：面板住在 QStackedWidget 的下标 1 上，进出一次必须回到原位。"""

    @classmethod
    def setUpClass(cls):
        cls._app = _ensure_app()

    def test_detach_and_attach_restores_stack_index(self):
        from ui.lyrics_fullscreen import LyricsFullscreenWindow

        win = LyricsFullscreenWindow()
        stack = QStackedWidget()
        native = QWidget()
        visual = QWidget()
        stack.addWidget(native)                    # 0
        stack.addWidget(visual)                    # 1
        stack.setCurrentIndex(1)
        try:
            # 模拟 now_playing.detach_jizura / attach_jizura
            stack.removeWidget(visual)
            visual.setParent(None)
            win.enter(visual, lambda p: (p.setParent(None), stack.addWidget(p),
                                         stack.setCurrentWidget(p)))
            self.assertTrue(win.active)
            self.assertEqual(stack.count(), 1)
            win.leave()
            self.assertEqual(stack.count(), 2)
            self.assertIs(stack.currentWidget(), visual)   # 回到下标 1 且是当前页
        finally:
            win.deleteLater()
            stack.deleteLater()
