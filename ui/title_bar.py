# -*- coding: utf-8 -*-
"""通栏自定义标题栏：logo / 视图导航 / 刷新 / 全局搜索 / 窗口按钮。

- 空白处拖拽移动窗口（未最大化走原生 startSystemMove，保留贴边；
  最大化时先还原到常规尺寸再跟手移动）；
- 双击空白处切换最大化；
- 搜索框为胶囊造型，leading 位放大镜图标。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from ui import icons as ic
from ui.theme import current_theme


class TitleBar(QWidget):
    back_clicked = Signal()
    forward_clicked = Signal()
    refresh_clicked = Signal()
    search_changed = Signal(str)
    minimize_clicked = Signal()
    maximize_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(48)
        self._restore_drag = False
        self._move_offset = None

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 4, 6, 4)
        root.setSpacing(6)

        # ---- logo + 名称 ----
        logo_icon = QLabel()
        logo_icon.setPixmap(ic.make_icon("note", current_theme().ACCENT, 20).pixmap(20, 20))
        root.addWidget(logo_icon)
        logo = QLabel("轻音")
        logo.setObjectName("Logo")
        root.addWidget(logo)
        root.addSpacing(14)

        # ---- 视图导航 ----
        self.back_btn = self._make_title_btn("back", "后退（Alt+Left）")
        self.back_btn.clicked.connect(self.back_clicked.emit)
        self.fwd_btn = self._make_title_btn("forward", "前进（Alt+Right）")
        self.fwd_btn.clicked.connect(self.forward_clicked.emit)
        self.refresh_btn = self._make_title_btn("refresh", "刷新当前视图")
        self.refresh_btn.clicked.connect(self.refresh_clicked.emit)
        root.addWidget(self.back_btn)
        root.addWidget(self.fwd_btn)
        root.addWidget(self.refresh_btn)
        root.addSpacing(10)

        # ---- 搜索 ----
        self.search_box = QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("搜索歌曲 / 艺人 / 专辑")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setMinimumWidth(260)
        self.search_box.setMaximumWidth(420)
        self.search_action = self.search_box.addAction(
            ic.make_icon("search", current_theme().TEXT_DIM, 14),
            QLineEdit.ActionPosition.LeadingPosition)
        self.search_box.textChanged.connect(self.search_changed.emit)
        root.addWidget(self.search_box)

        root.addStretch(1)

        # ---- 窗口按钮 ----
        self.min_btn = self._make_title_btn("minimize", "最小化")
        self.min_btn.clicked.connect(self.minimize_clicked.emit)
        self.max_btn = self._make_title_btn("maximize", "最大化 / 还原")
        self.max_btn.clicked.connect(self.maximize_clicked.emit)
        self.close_btn = self._make_title_btn("close", "关闭")
        self.close_btn.setObjectName("CloseBtn")
        self.close_btn.clicked.connect(self.close_clicked.emit)
        root.addWidget(self.min_btn)
        root.addWidget(self.max_btn)
        root.addWidget(self.close_btn)

        self.set_nav_enabled(False, False)

    # ---------- 对外 ----------

    def _make_title_btn(self, kind: str, tip: str) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("TitleBtn")
        btn.setToolTip(tip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(btn, kind, 15, "dim")
        return btn

    def set_nav_enabled(self, back: bool, forward: bool) -> None:
        self.back_btn.setEnabled(back)
        self.fwd_btn.setEnabled(forward)

    def set_maximized(self, maximized: bool) -> None:
        ic.set_icon_kind(self.max_btn, "restore" if maximized else "maximize")
        self.max_btn.setToolTip("还原" if maximized else "最大化")

    def set_search(self, text: str) -> None:
        self.search_box.setText(text)

    def clear_search(self) -> None:
        self.search_box.clear()

    def focus_search(self) -> None:
        self.search_box.setFocus()

    def refresh_icons(self) -> None:
        """主题切换：搜索框 leading 图标随主题重绘。"""
        self.search_action.setIcon(
            ic.make_icon("search", current_theme().TEXT_DIM, 14))

    # ---------- 拖拽 / 双击 ----------

    def _on_pressable_area(self, event) -> bool:
        """press 位置是否在空白拖拽区（避开按钮与搜索框）。"""
        child = self.childAt(event.position().toPoint())
        return child is None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._on_pressable_area(event):
            win = self.window()
            if win.isMaximized():
                # 记录还原比例：松手/移动时按光标相对位置还原窗口
                self._restore_drag = True
                self._restore_frac = (event.globalPosition().toPoint().x() - win.x()) / max(1, win.width())
            else:
                handle = win.windowHandle()
                if handle is not None:
                    handle.startSystemMove()
                else:  # 兜底：手动移动
                    self._move_offset = event.globalPosition().toPoint() - win.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._restore_drag:
            win = self.window()
            normal = win.normalGeometry()
            if not normal.isValid() or normal.width() < 200:
                normal = win.geometry()
            gpos = event.globalPosition().toPoint()
            x = gpos.x() - int(normal.width() * self._restore_frac)
            y = gpos.y() - 24
            win.setGeometry(x, y, normal.width(), normal.height())
            win.showNormal()
            self._restore_drag = False
            self._move_offset = gpos - win.pos()
            return
        if self._move_offset is not None:
            self.window().move(event.globalPosition().toPoint() - self._move_offset)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._restore_drag = False
        self._move_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._on_pressable_area(event):
            self.maximize_clicked.emit()
        super().mouseDoubleClickEvent(event)
