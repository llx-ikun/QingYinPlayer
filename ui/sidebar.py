# -*- coding: utf-8 -*-
"""侧边栏（v2.0 QQ 音乐风）：用户卡片 / 图标导航 / 最近播放 / 歌单封面列表 / 导入。

- 用户卡片：首字母圆形头像 + 昵称 + 「本地模式」徽标，点击请求修改昵称；
- 图标导航：♥ 我喜欢 / ⌂ 资料库（方形图标按钮，激活态淡强调底）；
- 歌单列表：封面缩略图（歌单内第一首歌）+ 名称 + 数量，右键重命名/删除。
"""
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

from app.models import PLAYLIST_FAVORITES, PLAYLIST_LIBRARY, PLAYLIST_RECENT
from ui import icons as ic
from ui.widgets import ElidedLabel

SIDEBAR_WIDTH = 248


class Sidebar(QWidget):
    import_menu_requested = Signal()                 # 点击导入按钮（调用方弹菜单）
    view_requested = Signal(str)                     # library / recent / favorites / playlist_id
    create_playlist_requested = Signal()
    playlist_action = Signal(str, str)               # (playlist_id, "rename" | "delete")
    nickname_change_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(SIDEBAR_WIDTH)
        self._nav_buttons: dict[str, QPushButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 12)
        root.setSpacing(8)

        # ---- 用户卡片 ----
        self.user_card = QWidget()
        self.user_card.setObjectName("UserCard")
        self.user_card.setCursor(Qt.CursorShape.PointingHandCursor)
        self.user_card.setToolTip("点击修改昵称")
        card = QHBoxLayout(self.user_card)
        card.setContentsMargins(8, 8, 8, 8)
        card.setSpacing(10)
        self.avatar = QLabel("♫")
        self.avatar.setObjectName("Avatar")
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card.addWidget(self.avatar)
        card_col = QVBoxLayout()
        card_col.setSpacing(3)
        self.nickname_label = ElidedLabel("音乐爱好者")
        self.nickname_label.setObjectName("TrackTitle")
        # 昵称宽度应跟随可用空间，而不是自己的文字宽（否则长昵称会把列卡死）
        self.nickname_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                          QSizePolicy.Policy.Preferred)
        badge = QLabel("本地模式")
        badge.setObjectName("Badge")
        badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        card_col.addWidget(self.nickname_label)
        # 徽标外面套一层带 stretch 的行：QLabel 定宽/贴文字会把整个 QVBoxLayout
        # 的最大宽度压到该标签的 sizeHint（实测 66px），父布局便不再分配余量——
        # 「音乐爱好者」因此被省略成「音乐爱…」。加了 stretch 后列宽不再被卡住。
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(0)
        badge_row.addWidget(badge)
        badge_row.addStretch(1)
        card_col.addLayout(badge_row)
        card.addLayout(card_col, 1)
        root.addWidget(self.user_card)
        root.addSpacing(6)

        # ---- 图标导航 ----
        icon_nav = QHBoxLayout()
        icon_nav.setSpacing(8)
        for view_id, kind, tip in (
            (PLAYLIST_FAVORITES, "heart", "我喜欢"),
            (PLAYLIST_LIBRARY, "home", "资料库"),
        ):
            btn = QPushButton()
            btn.setObjectName("IconNav")
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            ic.bind_icon(btn, kind, 20, "dim")
            btn.setProperty("active", "false")
            btn.clicked.connect(lambda _=False, v=view_id: self.view_requested.emit(v))
            self._nav_buttons[view_id] = btn
            icon_nav.addWidget(btn)
        icon_nav.addStretch(1)
        root.addLayout(icon_nav)
        root.addSpacing(2)

        # ---- 最近播放（文本导航，带数量） ----
        self.recent_btn = QPushButton("最近播放")
        self.recent_btn.setObjectName("NavItem")
        self.recent_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(self.recent_btn, "clock", 16, "dim")
        self.recent_btn.clicked.connect(lambda: self.view_requested.emit(PLAYLIST_RECENT))
        root.addWidget(self.recent_btn)

        root.addSpacing(10)

        # ---- 歌单区标题 ----
        pl_header = QHBoxLayout()
        pl_header.setSpacing(4)
        pl_title = QLabel("自建歌单")
        pl_title.setObjectName("Dim")
        pl_header.addWidget(pl_title)
        pl_header.addStretch(1)
        add_btn = QPushButton()
        add_btn.setObjectName("ControlBtn")
        add_btn.setToolTip("新建歌单")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(add_btn, "plus", 15, "dim")
        add_btn.clicked.connect(self.create_playlist_requested.emit)
        pl_header.addWidget(add_btn)
        root.addLayout(pl_header)

        # ---- 歌单列表 ----
        self.playlist_list = QListWidget()
        self.playlist_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.playlist_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_list.customContextMenuRequested.connect(self._on_pl_menu)
        self.playlist_list.itemClicked.connect(self._on_pl_clicked)
        self.playlist_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.playlist_list, 1)

        # ---- 导入 ----
        import_btn = QPushButton("  导入音乐")
        import_btn.setObjectName("Primary")
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(import_btn, "plus", 16, "on_accent")
        import_btn.clicked.connect(self.import_menu_requested.emit)
        root.addWidget(import_btn)

        version = QLabel("v2.1.7 · 本地音乐与视频")
        version.setObjectName("Dim")
        root.addWidget(version)

        self.set_active_view(PLAYLIST_LIBRARY)

    # ---------- 对外 ----------

    def set_nickname(self, name: str) -> None:
        name = (name or "").strip() or "音乐爱好者"
        self.nickname_label.setText(name)
        self.avatar.setText(name[:1].upper())

    def set_favorite_count(self, count: int) -> None:
        btn = self._nav_buttons.get(PLAYLIST_FAVORITES)
        if btn is not None:
            btn.setToolTip(f"我喜欢 · {count}")

    def set_recent_count(self, count: int) -> None:
        self.recent_btn.setText(f"最近播放 · {count}" if count else "最近播放")

    def set_active_view(self, view_id: str) -> None:
        for vid, btn in self._nav_buttons.items():
            active = "true" if vid == view_id else "false"
            btn.setProperty("active", active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            ic.bind_icon(btn, "heart" if vid == PLAYLIST_FAVORITES else "home", 20,
                         "accent" if active == "true" else "dim")
        recent_active = view_id == PLAYLIST_RECENT
        self.recent_btn.setProperty("active", "true" if recent_active else "false")
        self.recent_btn.style().unpolish(self.recent_btn)
        self.recent_btn.style().polish(self.recent_btn)
        ic.bind_icon(self.recent_btn, "clock", 16, "accent" if recent_active else "dim")
        # 歌单列表选中态
        self.playlist_list.clearSelection()
        for row in range(self.playlist_list.count()):
            item = self.playlist_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == view_id:
                item.setSelected(True)
                break

    def refresh_playlists(self, playlists, cover_getter=None) -> None:
        """playlists: list[Playlist]；cover_getter: callable(playlist) -> QPixmap|None"""
        self.playlist_list.clear()
        for pl in playlists:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, pl.id)
            item.setSizeHint(self._pl_item_size())
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(6, 0, 8, 0)
            row_layout.setSpacing(8)

            cover = QLabel()
            cover.setFixedSize(36, 36)
            cover.setScaledContents(True)
            pixmap = cover_getter(pl) if cover_getter else None
            if pixmap is not None and not pixmap.isNull():
                cover.setPixmap(pixmap)
            else:
                from ui.theme import current_theme
                cover.setPixmap(ic.make_icon("note", current_theme().TEXT_DIM, 18).pixmap(18, 18))
            row_layout.addWidget(cover)

            text_col = QVBoxLayout()
            text_col.setSpacing(0)
            name = ElidedLabel(pl.name)
            name.setObjectName("TrackTitle")
            count = QLabel(f"{len(pl.track_ids)} 首")
            count.setObjectName("Dim")
            text_col.addWidget(name)
            text_col.addWidget(count)
            row_layout.addLayout(text_col, 1)
            self.playlist_list.addItem(item)
            self.playlist_list.setItemWidget(item, row)

    @staticmethod
    def _pl_item_size():
        from PySide6.QtCore import QSize
        return QSize(200, 48)

    # ---------- 内部 ----------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # 用户卡片区域点击 -> 请求修改昵称
        if event.button() == Qt.MouseButton.LeftButton:
            local = self.user_card.mapFrom(self, event.position().toPoint())
            if self.user_card.rect().contains(local):
                self.nickname_change_requested.emit()
        super().mousePressEvent(event)

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
