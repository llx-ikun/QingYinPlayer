# -*- coding: utf-8 -*-
"""左下浮动工具条。

结构（v2.1.7 重排）：
    圆形主题开关 + 一个「分段托盘」内嵌 正在播放 / 数据目录 / 设置
托盘是浮起的一张卡片（SURFACE + 细边），内部按钮透明、悬停时才凹下一层，
读起来像一组并列的工具入口，而不是三个各自独立的输入框。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ui import icons as ic

_TRAY_H = 36          # 托盘 / 圆形按钮的直径（含 1px 边框）
_BTN_H = 30           # 托盘内按钮高度（托盘 36 上下各留 2px + 1px 边框）


class _HoverIconButton(QPushButton):
    """图标按钮基类：悬停时图标跟着点亮。

    QSS 的 `color` 只能染文字，染不动 QIcon（图标颜色烘焙在绘制参数里），
    所以必须在这里 enter/leave 时重绑颜色角色。`set_kind` 供状态切换用
    （如太阳/月亮），会保留当前悬停态再决定用哪个颜色角色。
    """

    def __init__(self, kind: str, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(16, 16))
        self._kind = kind
        ic.bind_icon(self, kind, 16, "dim")

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        ic.bind_icon(self, kind, 16, "text" if self.underMouse() else "dim")

    def enterEvent(self, event) -> None:  # noqa: N802
        ic.bind_icon(self, self._kind, 16, "text")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        ic.bind_icon(self, self._kind, 16, "dim")
        super().leaveEvent(event)


class _IconTextButton(_HoverIconButton):
    """托盘内的图标 + 文字入口。"""

    def __init__(self, kind: str, text: str, parent=None) -> None:
        super().__init__(kind, text, parent)
        self.setObjectName("FloatTextBtn")
        self.setToolTip(text)
        # 宽度交给 sizeHint（内容宽 + QSS 的左右内边距）：托盘没有分隔线，
        # 视觉上数的是「文字之间的空隙」，等宽分段会让「设置」两侧明显空出一截。
        self.setFixedHeight(_BTN_H)


class _ThemeToggle(_HoverIconButton):
    """纯图标圆形开关。"""

    def __init__(self, parent=None) -> None:
        super().__init__("sun", "", parent)
        self.setObjectName("ThemeToggle")
        self.setCheckable(True)
        self.setFixedSize(_TRAY_H, _TRAY_H)


class FloatBar(QWidget):
    theme_clicked = Signal()
    now_playing_clicked = Signal()
    data_dir_clicked = Signal()
    settings_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(44)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.theme_toggle = _ThemeToggle()
        self.theme_toggle.clicked.connect(self.theme_clicked.emit)
        root.addWidget(self.theme_toggle)

        # 分段托盘：三个并列工具入口
        self.tray = QWidget()
        self.tray.setObjectName("FloatTray")
        self.tray.setFixedHeight(_TRAY_H)
        tray_lay = QHBoxLayout(self.tray)
        tray_lay.setContentsMargins(3, 2, 3, 2)
        tray_lay.setSpacing(2)

        self.np_btn = _IconTextButton("note", "正在播放")
        self.np_btn.clicked.connect(self.now_playing_clicked.emit)
        tray_lay.addWidget(self.np_btn)

        self.dir_btn = _IconTextButton("folder", "数据目录")
        self.dir_btn.clicked.connect(self.data_dir_clicked.emit)
        tray_lay.addWidget(self.dir_btn)

        self.settings_btn = _IconTextButton("settings", "设置")
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        tray_lay.addWidget(self.settings_btn)

        root.addWidget(self.tray)

        self.set_theme_icon(True)

    def set_theme_icon(self, is_dark: bool) -> None:
        """深色主题下显示太阳（点它切到浅色），反之显示月亮；checked = 当前为浅色。"""
        self.theme_toggle.set_kind("sun" if is_dark else "moon")
        self.theme_toggle.setToolTip("切换到浅色主题" if is_dark else "切换到深色主题")
        self.theme_toggle.setChecked(not is_dark)
