# -*- coding: utf-8 -*-
"""全屏歌词浮层（v3.4.3）。

把正在播放页里的**视觉歌词面板**临时搬进一个无边框全屏窗口，铺满整块屏幕显示，
Esc / F11 退出，音乐与播放进度完全不受影响。

为什么是「搬运」而不是「另建一块面板」：
- 另建一块就要再起一个 QtWebEngine 实例（Chromium 渲染进程 + 200MB 上下内存），
  而且内容要再喂一遍，切歌时两边容易不同步；
- 搬运只是 `setParent` + 加进本窗口的布局，页面不重新加载，画面是接着画的 ——
  这正是 `ui/video_view.py` 里视频全屏用的同一套办法（`enter` / `leave`）。

与视频全屏的区别（也是这里多做的一步）：视觉面板是固定 1280×720 的等比画布，
直接铺满会因为宽高比不一致而留黑边。所以进出全屏时同时切换面板的
`set_fit("cover" | "contain")` —— cover 等比放大到铺满、裁掉溢出部分，不留边也不变形。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

# 鼠标静止多久后隐藏光标 / 退出提示（ms）。全屏歌词要的是「只剩画面」。
_IDLE_MS = 2500


class LyricsFullscreenWindow(QWidget):
    """全屏歌词浮层。`enter()` 把面板搬进来，`leave()` 搬回去。"""

    exited = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("LyricsFullscreen")
        self.setWindowTitle("全屏歌词")
        # 不进任务栏缩略图之外的窗口管理；Esc 由自己处理，所以也不设关闭按钮
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setStyleSheet("#LyricsFullscreen { background: #000; }")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._layout = layout

        self._panel: QWidget | None = None
        self._restore = None

        # 退出提示：只在鼠标动的时候露一下，静止后连光标一起藏
        self._hint = QLabel("Esc 退出全屏", self)
        self._hint.setStyleSheet(
            "color: rgba(255,255,255,0.72); font-size: 13px;"
            "background: rgba(0,0,0,0.45); border-radius: 10px; padding: 4px 12px;"
        )
        self._hint.adjustSize()
        self._hint.hide()

        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(_IDLE_MS)
        self._idle.timeout.connect(self._go_idle)

    # ---------- 状态 ----------

    @property
    def active(self) -> bool:
        return self._panel is not None

    # ---------- 进入 / 退出 ----------

    def enter(self, panel: QWidget, restore, title: str = "") -> None:
        """把 `panel` 搬进浮层全屏显示。

        `restore(panel)` 由调用方提供，负责把面板放回原来的布局（这里不猜结构 ——
        面板原本在 QStackedWidget 里，放回时必须还原栈内下标）。
        """
        if self._panel is not None:
            return
        self._panel = panel
        self._restore = restore

        # 全屏到主窗口所在的那块屏（多显示器时别跑到主屏上去）
        screen = panel.window().screen() if panel.window() is not None else None
        if screen is not None:
            self.setScreen(screen)

        panel.setParent(None)
        self._layout.addWidget(panel)
        panel.show()
        self.showFullScreen()
        panel.setFocus(Qt.FocusReason.OtherFocusReason)
        self.raise_()
        self.activateWindow()
        self._go_idle()
        if title:
            self.setWindowTitle(f"全屏歌词 - {title}")
        # 全屏切换有窗口动画，控件尺寸是「陆续」到位的；Chromium 的合成器又比 Qt
        # 慢一拍，只在 enter 时套一次几何会停在旧视口上（画面缩在左上角 + 一块黑）。
        # 这里连补三次，覆盖动画/合成器两种延迟。
        for delay in (60, 200, 500):
            QTimer.singleShot(delay, self._refresh_fit)

    def _refresh_fit(self) -> None:
        """让面板按自己当前的 fit 模式重算几何（面板不一定有这个方法，鸭子类型）。"""
        if self._panel is None:
            return
        refresh = getattr(self._panel, "refresh_fit", None)
        if callable(refresh):
            refresh()

    def leave(self) -> None:
        """关闭浮层并把面板交还给调用方。幂等。"""
        if self._panel is None:
            return
        panel = self._panel
        restore = self._restore
        self._panel = None
        self._restore = None
        self._idle.stop()
        # 先藏自己再交接：否则面板会先在浮层里缩一下再消失，闪一帧
        self.hide()
        self.unsetCursor()
        self._hint.hide()
        self._layout.removeWidget(panel)
        panel.setParent(None)
        if restore is not None:
            restore(panel)

    # ---------- 交互 ----------

    def _go_idle(self) -> None:
        if not self.active:
            return
        self._hint.hide()
        self.setCursor(Qt.CursorShape.BlankCursor)

    def _wake(self) -> None:
        self.unsetCursor()
        self._hint.adjustSize()
        self._hint.move((self.width() - self._hint.width()) // 2, self.height() - 48)
        self._hint.show()
        self._hint.raise_()
        self._idle.start()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._wake()
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        # 双击也能退出（不知道 Esc 的人不用去猜）
        self.exited.emit()
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F11):
            self.exited.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        # 被系统关掉（Alt+F4 等）也要把面板交还，不能留个孤儿
        if self._panel is not None:
            self.exited.emit()
            event.ignore()
            return
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_fit()
        if self._hint.isVisible():
            self._hint.move((self.width() - self._hint.width()) // 2, self.height() - 48)
