# -*- coding: utf-8 -*-
"""左下浮动工具条。

布局（v2.2.2）：
    左列：主题圆钮（上）+ 齿轮设置圆钮（下），竖排
    右侧：导入音乐 / 数据目录 两个**独立**按钮并排（不再共用分段托盘）
整条宽度固定为侧边栏内容宽度（248 - 左右 12 边距 = 224），右缘与侧边栏内容右边界
对齐，不跨进内容区。

为什么把「正在播放」从浮动条移除：列表页头已有一个等价入口（`TrackList.np_btn`，
同样切到正在播放页），且点击播放栏封面也能切页，所以这里不再是唯一入口。
空出来的横向空间给「导入音乐」，让主操作离手更近。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ui import icons as ic

_FLOAT_W = 224        # 与侧边栏内容宽度对齐（侧栏 248 - 左右各 12 边距）
_CIRCLE = 38          # 左列圆钮直径
_BTN_W = 86           # 右侧独立按钮宽
_BTN_H = 38           # 右侧独立按钮高（与圆钮同高，横向读成一行）
_ICON = 16            # 图标尺寸（比 14 更醒目）
_GAP_V = 6            # 左列两个圆钮的竖向间距
_GAP_H = 8            # 左右两列的水平间距
_GAP_BTN = 6          # 右侧两个按钮的水平间距
# 38 + 8 + 86 + 6 + 86 = 224，刚好铺满整条宽度，不需要 stretch
# 高度 = 38 + 6 + 38 = 82（播放栏 84，仍放得下，不会被窗口底边裁掉）


class _HoverIconButton(QPushButton):
    """图标按钮基类：悬停时图标跟着点亮。

    QSS 的 `color` 只能染文字，染不动 QIcon（图标颜色烘焙在绘制参数里），
    所以必须在这里 enter/leave 时重绑颜色角色。`set_kind` 供状态切换用
    （如太阳/月亮），会保留当前悬停态再决定用哪个颜色角色。
    """

    def __init__(self, kind: str, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(_ICON, _ICON))
        self._kind = kind
        ic.bind_icon(self, kind, _ICON, "dim")

    def set_kind(self, kind: str) -> None:
        self._kind = kind
        ic.bind_icon(self, kind, _ICON, "text" if self.underMouse() else "dim")

    def enterEvent(self, event) -> None:  # noqa: N802
        ic.bind_icon(self, self._kind, _ICON, "text")
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        ic.bind_icon(self, self._kind, _ICON, "dim")
        super().leaveEvent(event)


class _IconTextButton(_HoverIconButton):
    """图标 + 文字按钮：右侧的独立入口，固定宽高。"""

    def __init__(self, kind: str, text: str, parent=None) -> None:
        super().__init__(kind, text, parent)
        self.setObjectName("FloatTextBtn")
        self.setToolTip(text)
        self.setFixedSize(_BTN_W, _BTN_H)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(_BTN_W, _BTN_H)


class _CircleButton(_HoverIconButton):
    """纯图标圆形按钮（主题 / 设置）。"""

    def __init__(self, kind: str, tooltip: str = "", parent=None) -> None:
        super().__init__(kind, "", parent)
        self.setObjectName("CircleBtn")
        self.setToolTip(tooltip)
        self.setFixedSize(_CIRCLE, _CIRCLE)


class FloatBar(QWidget):
    theme_clicked = Signal()
    import_clicked = Signal()
    data_dir_clicked = Signal()
    settings_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(_FLOAT_W)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        # ---- 左列：主题（上）+ 设置齿轮（下），竖排 ----
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(_GAP_V)

        self.theme_toggle = _CircleButton("sun")
        self.theme_toggle.setCheckable(True)
        self.theme_toggle.clicked.connect(self.theme_clicked.emit)
        left.addWidget(self.theme_toggle)

        self.settings_btn = _CircleButton("gear", "设置")
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        left.addWidget(self.settings_btn)
        left.addStretch(1)
        row.addLayout(left)
        row.addSpacing(_GAP_H)

        # ---- 右侧：导入音乐 / 数据目录，两个独立按钮并排，与主题钮同一行 ----
        right_wrap = QVBoxLayout()
        right_wrap.setContentsMargins(0, 0, 0, 0)
        right_wrap.setSpacing(0)
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(_GAP_BTN)

        self.import_btn = _IconTextButton("plus", "导入音乐")
        self.import_btn.clicked.connect(self.import_clicked.emit)
        right.addWidget(self.import_btn)

        self.dir_btn = _IconTextButton("folder", "数据目录")
        self.dir_btn.clicked.connect(self.data_dir_clicked.emit)
        right.addWidget(self.dir_btn)

        right_wrap.addLayout(right)
        right_wrap.addStretch(1)
        row.addLayout(right_wrap, 1)

        self.set_theme_icon("columbina")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(_FLOAT_W, _CIRCLE * 2 + _GAP_V)

    def set_theme_icon(self, theme_name: str) -> None:
        """主题钮：图标与提示都指向「点下去会切到哪个主题」。

        三态循环 星月 → 深色 → 浅色 → 星月，所以按钮上画的不是当前主题，
        而是下一个目标（羽毛=星月 / 月亮=深色 / 太阳=浅色）。
        """
        from ui.theme import THEME_ICON, THEME_LABEL, THEME_NEXT

        nxt = THEME_NEXT.get(theme_name, "columbina")
        self.theme_toggle.set_kind(THEME_ICON[nxt])
        self.theme_toggle.setToolTip(f"切换到{THEME_LABEL[nxt]}主题")
        self.theme_toggle.setChecked(theme_name == "light")
