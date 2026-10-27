# -*- coding: utf-8 -*-
"""左下浮动工具条。

布局（v2.1.8）：
    上排：圆形主题开关（单独一行）
    下排：一个「分段托盘」内嵌 正在播放 / 数据目录 / 设置
整条宽度固定为侧边栏内容宽度（248 - 左右 12 边距 = 224），右缘与侧边栏内容右边界
对齐，不再跨进内容区（v2.1.7 的 288px 条会把「设置」压到侧边栏竖线外面）。
把主题圆钮提到单独一行，是为了让下排托盘只占 224px 就能放下三个入口。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ui import icons as ic

_FLOAT_W = 224        # 与侧边栏内容宽度对齐（侧栏 248 - 左右各 12 边距）
_CIRCLE = 34          # 顶部主题圆钮直径
_TRAY_H = 34          # 托盘高度
_BTN_H = 28           # 托盘内按钮高度


class _HoverIconButton(QPushButton):
    """图标按钮基类：悬停时图标跟着点亮。

    QSS 的 `color` 只能染文字，染不动 QIcon（图标颜色烘焙在绘制参数里），
    所以必须在这里 enter/leave 时重绑颜色角色。`set_kind` 供状态切换用
    （如太阳/月亮），会保留当前悬停态再决定用哪个颜色角色。
    """

    def __init__(self, kind: str, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(14, 14))
        self._kind = kind
        ic.bind_icon(self, kind, 14, "dim")

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        ic.bind_icon(self, kind, 14, "text" if self.underMouse() else "dim")

    def enterEvent(self, event) -> None:  # noqa: N802
        ic.bind_icon(self, self._kind, 14, "text")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        ic.bind_icon(self, self._kind, 14, "dim")
        super().leaveEvent(event)


class _IconTextButton(_HoverIconButton):
    """托盘内的图标 + 文字入口，三个等分托盘宽度。"""

    def __init__(self, kind: str, text: str, parent=None) -> None:
        super().__init__(kind, text, parent)
        self.setObjectName("FloatTextBtn")
        self.setToolTip(text)
        self.setFixedHeight(_BTN_H)


class _ThemeToggle(_HoverIconButton):
    """纯图标圆形开关。"""

    def __init__(self, parent=None) -> None:
        super().__init__("sun", "", parent)
        self.setObjectName("ThemeToggle")
        self.setCheckable(True)
        self.setFixedSize(_CIRCLE, _CIRCLE)


class FloatBar(QWidget):
    theme_clicked = Signal()
    now_playing_clicked = Signal()
    data_dir_clicked = Signal()
    settings_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(_FLOAT_W)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(5)

        # 上排：主题开关单独一行，左对齐在托盘左端上方
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)
        self.theme_toggle = _ThemeToggle()
        self.theme_toggle.clicked.connect(self.theme_clicked.emit)
        top.addWidget(self.theme_toggle)
        top.addStretch(1)
        root.addLayout(top)

        # 下排：分段托盘（三个入口等分，撑满整条宽度）
        self.tray = QWidget()
        self.tray.setObjectName("FloatTray")
        self.tray.setFixedHeight(_TRAY_H)
        tray_lay = QHBoxLayout(self.tray)
        tray_lay.setContentsMargins(3, 2, 3, 2)
        tray_lay.setSpacing(2)

        self.np_btn = _IconTextButton("note", "正在播放")
        self.np_btn.clicked.connect(self.now_playing_clicked.emit)
        tray_lay.addWidget(self.np_btn, 1)

        self.dir_btn = _IconTextButton("folder", "数据目录")
        self.dir_btn.clicked.connect(self.data_dir_clicked.emit)
        tray_lay.addWidget(self.dir_btn, 1)

        self.settings_btn = _IconTextButton("settings", "设置")
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        tray_lay.addWidget(self.settings_btn, 1)

        root.addWidget(self.tray)

        self.set_theme_icon(True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(_FLOAT_W, _CIRCLE + 5 + _TRAY_H)

    def set_theme_icon(self, is_dark: bool) -> None:
        """深色主题下显示太阳（点它切到浅色），反之显示月亮；checked = 当前为浅色。"""
        self.theme_toggle.set_kind("sun" if is_dark else "moon")
        self.theme_toggle.setToolTip("切换到浅色主题" if is_dark else "切换到深色主题")
        self.theme_toggle.setChecked(not is_dark)
