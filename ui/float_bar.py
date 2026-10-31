# -*- coding: utf-8 -*-
"""左下浮动工具条。

布局（v2.6.1 起：单行四列）：
    [主题圆钮] [设置齿轮] [导入音乐] [数据目录]
整条宽度固定为侧边栏内容宽度（248 - 左右 12 边距 = 224），右缘与侧边栏内容右边界
对齐，不跨进内容区：38 + 4 + 38 + 4 + 68 + 4 + 68 = 224，高度 = 圆钮直径 38。

v2.6.1 之前是「左列竖排两个圆钮 + 右侧两个竖排文字按钮」的 224×82 网格。改成一行
的理由：整条从 82 压到 38，几乎不占播放栏高度，四个入口在同一水平线上、视线不用
上下扫；文字按钮也由竖排两行改回单行四字。

为什么把「正在播放」从浮动条移除：列表页头已有一个等价入口（`TrackList.np_btn`，
同样切到正在播放页），且点击播放栏封面也能切页，所以这里不再是唯一入口。
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ui import icons as ic

_FLOAT_W = 224        # 与侧栏内容宽度对齐（侧栏 248 - 左右各 12 边距）
_CIRCLE = 38          # 两个圆钮直径（也是整条高度）
_BTN_W = 68           # 文字按钮宽：见下方「为什么是 68 而不是 65」
_ICON = 16            # 图标尺寸（比 14 更醒目）
_GAP = 4              # 四个控件之间的水平间距：38+4+38+4+68+4+68 = 224
# 整条宽 224 刚好铺满侧栏内容宽；高 38 = 圆钮直径，单行为主、不侵占播放栏高度
#
# 为什么是 68 而不是 65：圆钮 2×38 + 3 个间距 = 224 里剩下的宽度全给两个文字按钮。
# 「导入音乐」4 个中文字在 12px 下 48px，但设置里字号可放大到 1.30 倍（12 → 16px），
# 那时 4 字 = 64px，65 宽扣掉 1px 边框只剩 63 → 会被裁掉一点点。68 留出安全余量，
# 配合 QSS 里 `padding: 0px`（否则基础 QPushButton 的左右 10px 内边距会再吃掉 20px）。


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


class _TextButton(QPushButton):
    """纯文字按钮（无图标）：固定宽高，文字单行居中。"""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("FloatTextBtn")
        self.setToolTip(text.replace("\n", ""))
        self.setFixedSize(_BTN_W, _CIRCLE)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(_BTN_W, _CIRCLE)


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
        row.setSpacing(_GAP)    # 38 + 4 + 38 + 4 + 68 + 4 + 68 = 224

        # 四个控件同一条水平线：主题 / 设置 / 导入音乐 / 数据目录
        self.theme_toggle = _CircleButton("moon")
        self.theme_toggle.setCheckable(True)
        self.theme_toggle.clicked.connect(self.theme_clicked.emit)
        row.addWidget(self.theme_toggle)

        self.settings_btn = _CircleButton("gear", "设置")
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        row.addWidget(self.settings_btn)

        self.import_btn = _TextButton("导入音乐")
        self.import_btn.clicked.connect(self.import_clicked.emit)
        row.addWidget(self.import_btn)

        self.dir_btn = _TextButton("数据目录")
        self.dir_btn.clicked.connect(self.data_dir_clicked.emit)
        row.addWidget(self.dir_btn)

        self.set_theme_icon("columbina")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(_FLOAT_W, _CIRCLE)

    def set_theme_icon(self, theme_name: str) -> None:
        """主题钮：图标与提示都指向「点下去会切到哪个主题」。

        两态循环 深色 ↔ 浅色，所以按钮上画的不是当前主题，
        而是下一个目标（月亮=深色 / 太阳=浅色）。具体是谁由 tooltip 说清
        （「切换到深色主题」）。
        """
        from ui.theme import THEME_ICON, THEME_LABEL, THEME_NEXT

        nxt = THEME_NEXT.get(theme_name, "columbina")
        self.theme_toggle.set_kind(THEME_ICON[nxt])
        self.theme_toggle.setToolTip(f"切换到{THEME_LABEL[nxt]}主题")
        # checked 只表示「当前是浅色」，纯装饰位
        self.theme_toggle.setChecked(THEME_ICON.get(theme_name) == "sun")
