# -*- coding: utf-8 -*-
"""曲目列表：头部（标题/搜索/排序/视图切换）+ 列表行（封面/标题/时长）。"""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.lyrics import format_time
from app.models import Track
from ui import icons as ic
from ui.theme import ACCENT, TEXT, TEXT_DIM
from ui.widgets import ClickableCover, ElidedLabel, EqualizerBars

SORT_OPTIONS = [
    ("custom", "自定义"),
    ("title", "标题"),
    ("artist", "艺人"),
    ("album", "专辑"),
    ("duration", "时长"),
    ("added", "添加时间"),
]


class TrackItemWidget(QWidget):
    """列表行内容：[序号/动效条] [封面] [标题+副标题] [时长]"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 12, 6)
        layout.setSpacing(10)

        self.leading = QLabel()
        self.leading.setObjectName("Dim")
        self.leading.setFixedWidth(22)
        self.leading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.leading)

        self.cover = ClickableCover()
        self.cover.setFixedSize(40, 40)
        self.cover.setScaledContents(True)
        layout.addWidget(self.cover)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("TrackTitle")
        self.sub = ElidedLabel()
        self.sub.setObjectName("TrackSub")
        text_col.addWidget(self.title)
        text_col.addWidget(self.sub)
        layout.addLayout(text_col, 1)

        self.duration = QLabel()
        self.duration.setObjectName("Dim")
        self.duration.setFixedWidth(44)
        self.duration.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.duration)

        self._bars: EqualizerBars | None = None
        self._index = 0
        self._current = False

    def set_data(self, track: Track, cover_pixmap, index: int) -> None:
        self._index = index
        self.cover.setPixmap(cover_pixmap)
        self.title.setText(track.display_title)
        self.sub.setText(f"{track.display_artist} · {track.display_album}")
        self.duration.setText(format_time(track.duration_ms) if track.duration_ms else "--:--")
        self.set_current(self._current)

    def set_current(self, current: bool) -> None:
        self._current = current
        if current:
            if self._bars is None:
                self._bars = EqualizerBars(self)
                self._bars.move(1, (self.height() - self._bars.height()) // 2)
                self._bars.show()
            self._bars.start()
            self.leading.clear()
            self.title.setStyleSheet(f"color: {ACCENT}; font-weight: bold;")
        else:
            if self._bars is not None:
                self._bars.stop()
                self._bars.hide()
            self.leading.setText(str(self._index + 1))
            self.title.setStyleSheet("")


class TrackList(QWidget):
    track_activated = Signal(str, int)      # (track_id, 视图内索引)
    context_action = Signal(str, str)       # (track_id, action)
    reordered = Signal(str, int)            # (track_id, new_index)
    play_all_requested = Signal()
    sort_changed = Signal(str)
    search_changed = Signal(str)
    now_playing_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # ---- 头部 ----
        header = QHBoxLayout()
        header.setContentsMargins(20, 14, 20, 0)
        header.setSpacing(8)
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        self.title_label = QLabel("资料库")
        self.title_label.setObjectName("Title")
        self.count_label = QLabel("共 0 首")
        self.count_label.setObjectName("Dim")
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.count_label)
        header.addLayout(title_col)
        header.addStretch(1)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索歌曲 / 艺人 / 专辑")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFixedWidth(220)
        self.search_box.textChanged.connect(self.search_changed.emit)
        header.addWidget(self.search_box)

        self.sort_combo = QComboBox()
        for key, label in SORT_OPTIONS:
            self.sort_combo.addItem(label, key)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        header.addWidget(self.sort_combo)

        play_all_btn = QPushButton("  播放全部")
        play_all_btn.setObjectName("Ghost")
        play_all_btn.setIcon(ic.make_icon("play", TEXT, 14))
        play_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        play_all_btn.clicked.connect(self.play_all_requested.emit)
        header.addWidget(play_all_btn)

        self.np_btn = QPushButton()
        self.np_btn.setObjectName("ControlBtn")
        self.np_btn.setIcon(ic.make_icon("note", TEXT_DIM, 16))
        self.np_btn.setToolTip("正在播放")
        self.np_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.np_btn.clicked.connect(self.now_playing_requested.emit)
        header.addWidget(self.np_btn)
        root.addLayout(header)

        # ---- 列表 ----
        self.list = QListWidget()
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_menu)
        self.list.itemDoubleClicked.connect(self._on_double_clicked)
        self.list.model().rowsMoved.connect(self._on_rows_moved)
        root.addWidget(self.list, 1)

        # ---- 空状态 ----
        self.empty_label = QLabel("还没有歌曲\n点击左下角「导入音乐」开始吧")
        self.empty_label.setObjectName("Dim")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.hide()
        root.addWidget(self.empty_label)

        self._tracks: list[Track] = []
        self._current_tid: str | None = None
        self._drag_enabled = False
        self._in_playlist = False
        self._suppress_sort_signal = False

    # ---------- 对外 ----------

    def set_context_config(self, in_playlist: bool, drag_enabled: bool) -> None:
        """in_playlist: 是否歌单视图（启用移除/排序类菜单项）。"""
        self._in_playlist = in_playlist
        self.set_drag_enabled(drag_enabled)

    def set_header(self, title: str, count: int) -> None:
        self.title_label.setText(title)
        self.count_label.setText(f"共 {count} 首")

    def set_tracks(self, tracks: list[Track], cover_getter, current_tid: str | None) -> None:
        """cover_getter: callable(track) -> QPixmap"""
        self._tracks = list(tracks)
        self._current_tid = current_tid
        self.list.clear()
        for i, track in enumerate(self._tracks):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, track.id)
            item.setSizeHint(QSize(100, 56))
            self.list.addItem(item)
            row = TrackItemWidget()
            row.cover.clicked.connect(lambda _=False, t=track: self.track_activated.emit(t.id, self._tracks.index(t)))
            row.set_data(track, cover_getter(track), i)
            self.list.setItemWidget(item, row)
        self.empty_label.setVisible(not self._tracks)
        self.list.setVisible(bool(self._tracks))
        self.set_current_track(current_tid)

    def set_current_track(self, tid: str | None) -> None:
        self._current_tid = tid
        for i, track in enumerate(self._tracks):
            item = self.list.item(i)
            if item is None:
                continue
            row = self.list.itemWidget(item)
            if isinstance(row, TrackItemWidget):
                row.set_current(track.id == tid)

    def set_drag_enabled(self, enabled: bool) -> None:
        self._drag_enabled = enabled
        mode = QAbstractItemView.DragDropMode.InternalMove if enabled else QAbstractItemView.DragDropMode.NoDragDrop
        self.list.setDragDropMode(mode)
        self.list.setDragEnabled(enabled)
        self.list.setAcceptDrops(enabled)

    def set_sort(self, sort_key: str) -> None:
        self._suppress_sort_signal = True
        for i in range(self.sort_combo.count()):
            if self.sort_combo.itemData(i) == sort_key:
                self.sort_combo.setCurrentIndex(i)
                break
        self._suppress_sort_signal = False

    def set_search(self, text: str) -> None:
        self.search_box.setText(text)

    def search_text(self) -> str:
        return self.search_box.text().strip()

    def clear_search(self) -> None:
        self.search_box.clear()

    def set_now_playing_active(self, active: bool) -> None:
        self.np_btn.setProperty("active", "true" if active else "false")
        self.np_btn.style().unpolish(self.np_btn)
        self.np_btn.style().polish(self.np_btn)

    # ---------- 内部 ----------

    def _on_sort_changed(self, _index) -> None:
        if not self._suppress_sort_signal:
            self.sort_changed.emit(self.sort_combo.currentData())

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        tid = item.data(Qt.ItemDataRole.UserRole)
        if tid:
            self.track_activated.emit(tid, self.list.row(item))

    def _on_rows_moved(self, parent: QModelIndex, start: int, end: int, destination: int) -> None:
        if not self._drag_enabled or start < 0 or end < start:
            return
        moved = self._tracks[start:end + 1]
        if not moved:
            return
        new_index = destination if destination < start else destination - (end - start + 1)
        self.reordered.emit(moved[0].id, max(0, new_index))
        # 同步内部顺序，保持 UI 与数据一致
        rest = self._tracks[:start] + self._tracks[end + 1:]
        new_index = max(0, min(new_index, len(rest)))
        self._tracks = rest[:new_index] + moved + rest[new_index:]

    def _on_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        tid = item.data(Qt.ItemDataRole.UserRole)
        if not tid:
            return
        menu = QMenu(self)
        actions = [
            ("play", "播放", True),
            ("add_to_playlist", "添加到歌单…", True),
            ("remove_from_playlist", "从歌单移除", self._in_playlist),
            ("move_up", "上移", self._in_playlist),
            ("move_down", "下移", self._in_playlist),
            ("bind_lyrics", "选择歌词文件…", True),
            ("refresh", "重新读取歌曲信息", True),
            ("locate", "在文件资源管理器中显示", True),
            ("remove_from_library", "移除出资料库", True),
        ]
        buttons = {}
        for key, label, enabled in actions:
            act = menu.addAction(label)
            act.setEnabled(enabled)
            buttons[key] = act
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is None:
            return
        for key, act in buttons.items():
            if act == chosen:
                self.context_action.emit(tid, key)
                return
