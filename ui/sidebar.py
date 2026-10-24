# -*- coding: utf-8 -*-
"""侧边栏：Logo / 导航（资料库·最近播放）/ 歌单列表 / 导入入口。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.models import PLAYLIST_LIBRARY, PLAYLIST_RECENT
from ui import icons as ic
from ui.theme import ACCENT, TEXT_DIM


class Sidebar(QWidget):
    import_menu_requested = Signal()                 # 点击导入按钮（调用方弹菜单）
    view_requested = Signal(str)                     # library / recent / playlist_id
    create_playlist_requested = Signal()
    playlist_action = Signal(str, str)               # (playlist_id, "rename" | "delete")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(216)
        self._nav_buttons: dict[str, QPushButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 16, 12, 12)
        root.setSpacing(10)

        # Logo
        logo_row = QHBoxLayout()
        logo_row.setSpacing(8)
        logo_icon = QLabel()
        logo_icon.setPixmap(ic.make_icon("note", ACCENT, 22).pixmap(22, 22))
        logo_row.addWidget(logo_icon)
        logo = QLabel("轻音")
        logo.setObjectName("Logo")
        logo_row.addWidget(logo)
        logo_row.addStretch(1)
        root.addLayout(logo_row)

        sub = QLabel("本地音乐播放器")
        sub.setObjectName("Dim")
        root.addWidget(sub)
        root.addSpacing(10)

        # 导航
        for view_id, label, icon_kind in (
            (PLAYLIST_LIBRARY, "资料库", "library"),
            (PLAYLIST_RECENT, "最近播放", "clock"),
        ):
            btn = QPushButton(f"  {label}")
            btn.setObjectName("NavItem")
            btn.setIcon(ic.make_icon(icon_kind, TEXT_DIM, 17))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, v=view_id: self.view_requested.emit(v))
            self._nav_buttons[view_id] = btn
            root.addWidget(btn)

        root.addSpacing(12)

        # 歌单区标题
        pl_header = QHBoxLayout()
        pl_header.setSpacing(4)
        pl_title = QLabel("歌单")
        pl_title.setObjectName("Dim")
        pl_header.addWidget(pl_title)
        pl_header.addStretch(1)
        add_btn = QPushButton()
        add_btn.setObjectName("ControlBtn")
        add_btn.setIcon(ic.make_icon("plus", TEXT_DIM, 15))
        add_btn.setToolTip("新建歌单")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self.create_playlist_requested.emit)
        pl_header.addWidget(add_btn)
        root.addLayout(pl_header)

        # 歌单列表
        self.playlist_list = QListWidget()
        self.playlist_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.playlist_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_list.customContextMenuRequested.connect(self._on_pl_menu)
        self.playlist_list.itemClicked.connect(self._on_pl_clicked)
        self.playlist_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.playlist_list, 1)

        # 导入
        import_btn = QPushButton("  导入音乐")
        import_btn.setObjectName("Primary")
        import_btn.setIcon(ic.make_icon("plus", "#ffffff", 16))
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.clicked.connect(self.import_menu_requested.emit)
        root.addWidget(import_btn)

        version = QLabel("v1.0 · 纯本地播放")
        version.setObjectName("Dim")
        root.addWidget(version)

        self.set_active_view(PLAYLIST_LIBRARY)

    # ---------- 对外 ----------

    def set_active_view(self, view_id: str) -> None:
        for vid, btn in self._nav_buttons.items():
            btn.setProperty("active", "true" if vid == view_id else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        # 歌单列表选中态
        self.playlist_list.clearSelection()
        for row in range(self.playlist_list.count()):
            item = self.playlist_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == view_id:
                item.setSelected(True)
                break

    def refresh_playlists(self, playlists) -> None:
        """playlists: list[Playlist]"""
        self.playlist_list.clear()
        for pl in playlists:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, pl.id)
            item.setSizeHint(self._pl_item_size())
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 0, 10, 0)
            row_layout.setSpacing(6)
            name = QLabel(pl.name)
            name.setObjectName("TrackTitle")
            row_layout.addWidget(name)
            row_layout.addStretch(1)
            count = QLabel(f"{len(pl.track_ids)} 首")
            count.setObjectName("Dim")
            row_layout.addWidget(count)
            self.playlist_list.addItem(item)
            self.playlist_list.setItemWidget(item, row)

    @staticmethod
    def _pl_item_size():
        from PySide6.QtCore import QSize
        return QSize(180, 38)

    # ---------- 内部 ----------

    def _on_pl_clicked(self, item: QListWidgetItem) -> None:
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid:
            self.view_requested.emit(pid)

    def _on_pl_menu(self, pos) -> None:
        item = self.playlist_list.itemAt(pos)
        if item is None:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        if not pid:
            return
        menu = QMenu(self)
        rename = menu.addAction("重命名")
        delete = menu.addAction("删除歌单")
        action = menu.exec(self.playlist_list.mapToGlobal(pos))
        if action == rename:
            self.playlist_action.emit(pid, "rename")
        elif action == delete:
            self.playlist_action.emit(pid, "delete")
