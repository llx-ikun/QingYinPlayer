# -*- coding: utf-8 -*-
"""曲目列表（v2.0 表格形态）：列头 + 行（序号/封面/歌曲/艺人/专辑/格式徽标/时长/爱心/更多）。

- 当前行：强调色标题 + 序号位均衡器动效条 + 行底淡强调色；
- 爱心按钮切换「我喜欢」；更多按钮弹右键同款菜单；
- 保留：双击播放、拖拽排序（歌单自定义序）、空态、滚动位置保持。
"""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.lyrics import format_time
from app.models import Track, VIDEO_FORMATS
from ui import icons as ic
from ui.theme import current_theme
from ui.widgets import ClickableCover, ElidedLabel, EqualizerBars

SORT_OPTIONS = [
    ("custom", "自定义"),
    ("title", "标题"),
    ("artist", "艺人"),
    ("album", "专辑"),
    ("duration", "时长"),
    ("added", "添加时间"),
]

# 列宽（与列头保持一致）
_LEAD_W, _COVER_W, _FMT_W, _TIME_W, _ROWBTN_W = 22, 40, 52, 44, 28
# 弹性列伸展系数：歌曲 3 / 艺人 2 / 专辑 2
_STRETCH_TITLE, _STRETCH_ARTIST, _STRETCH_ALBUM = 3, 2, 2


def format_badge(fmt: str) -> tuple[str, str]:
    """格式 -> (徽标文案, tier)；tier=lossless 时徽标用强调色。"""
    f = (fmt or "").lower()
    if f in VIDEO_FORMATS:
        return "视频", "video"
    if f in ("flac", "wav", "aif", "aiff", "ape"):
        return "无损", "lossless"
    if f == "mp3":
        return "MP3", ""
    if f in ("m4a", "aac"):
        return "AAC", ""
    if f in ("ogg", "oga", "opus"):
        return "OGG", ""
    if f == "wma":
        return "WMA", ""
    return (fmt or "?").upper(), ""


class TrackItemWidget(QWidget):
    """列表行内容：[序号/动效条] [封面] [歌曲] [艺人] [专辑] [格式] [时长] [♥] [⋯]"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 6, 6)
        layout.setSpacing(8)

        self.leading = QLabel()
        self.leading.setObjectName("Dim")
        self.leading.setFixedWidth(_LEAD_W)
        self.leading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.leading)

        self.cover = ClickableCover()
        self.cover.setFixedSize(_COVER_W - 4, _COVER_W - 4)
        self.cover.setScaledContents(True)
        layout.addWidget(self.cover)

        self.title = ElidedLabel()
        self.title.setObjectName("TrackTitle")
        layout.addWidget(self.title, _STRETCH_TITLE)

        self.artist = ElidedLabel()
        self.artist.setObjectName("TrackSub")
        layout.addWidget(self.artist, _STRETCH_ARTIST)

        self.album = ElidedLabel()
        self.album.setObjectName("TrackSub")
        layout.addWidget(self.album, _STRETCH_ALBUM)

        self.fmt = QLabel()
        self.fmt.setObjectName("FmtBadge")
        self.fmt.setFixedSize(_FMT_W, 18)
        self.fmt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.fmt)

        self.duration = QLabel()
        self.duration.setObjectName("Dim")
        self.duration.setFixedWidth(_TIME_W)
        self.duration.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.duration)

        self.fav_btn = self._make_row_btn("heart", "喜欢 / 取消喜欢")
        self.fav_btn.clicked.connect(self._on_fav_clicked)
        layout.addWidget(self.fav_btn)

        self.more_btn = self._make_row_btn("more", "更多操作")
        layout.addWidget(self.more_btn)

        self._bars: EqualizerBars | None = None
        self._index = 0
        self._current = False
        self._fav = False
        self._tid = ""

    def _make_row_btn(self, kind: str, tip: str) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("RowBtn")
        btn.setToolTip(tip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(btn, kind, 14, "dim")
        return btn

    # ---------- 数据 ----------

    def set_data(self, track: Track, cover_pixmap, index: int, is_fav: bool) -> None:
        self._index = index
        self._tid = track.id
        self._fav = is_fav
        self.cover.setPixmap(cover_pixmap)
        self.title.setText(track.display_title)
        self.artist.setText(track.display_artist)
        self.album.setText(track.display_album)
        text, tier = format_badge(track.fmt)
        self.fmt.setText(text)
        self.fmt.setProperty("tier", tier)
        self.fmt.style().unpolish(self.fmt)
        self.fmt.style().polish(self.fmt)
        self.fmt.setToolTip(f"格式：{track.fmt or '未知'}")
        self.duration.setText(format_time(track.duration_ms) if track.duration_ms else "--:--")
        self._apply_fav_icon()
        self.set_current(self._current)

    def _apply_fav_icon(self) -> None:
        # 图标颜色烘焙自绘制参数，QSS 的 color 管不了 QIcon，必须按状态重绑颜色角色
        ic.bind_icon(self.fav_btn, "heart_filled" if self._fav else "heart", 14,
                     "heart" if self._fav else "dim")
        self.fav_btn.setProperty("active", "true" if self._fav else "false")
        self.fav_btn.style().unpolish(self.fav_btn)
        self.fav_btn.style().polish(self.fav_btn)
        self.fav_btn.setToolTip("取消喜欢" if self._fav else "加入我喜欢")

    def set_favorite(self, is_fav: bool) -> None:
        self._fav = is_fav
        self._apply_fav_icon()

    def set_current(self, current: bool) -> None:
        self._current = current
        theme = current_theme()
        if current:
            if self._bars is None:
                self._bars = EqualizerBars(self, color=theme.ACCENT)
                self._bars.move(2, (self.height() - self._bars.height()) // 2)
                self._bars.show()
            self._bars.start()
            self.leading.clear()
            self.title.setStyleSheet(f"color: {theme.ACCENT}; font-weight: bold;")
        else:
            if self._bars is not None:
                self._bars.stop()
                self._bars.hide()
            self.leading.setText(str(self._index + 1))
            self.title.setStyleSheet("")

    def _on_fav_clicked(self) -> None:
        self.favorite_toggled.emit(self._tid, not self._fav)

    favorite_toggled = Signal(str, bool)  # (track_id, 目标状态)


class TrackList(QWidget):
    track_activated = Signal(str, int)      # (track_id, 视图内索引)
    context_action = Signal(str, str)       # (track_id, action)
    reordered = Signal(str, int)            # (track_id, new_index)
    play_all_requested = Signal()
    sort_changed = Signal(str)
    now_playing_requested = Signal()
    favorite_toggled = Signal(str, bool)    # (track_id, 目标收藏状态)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

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

        self.sort_combo = QComboBox()
        for key, label in SORT_OPTIONS:
            self.sort_combo.addItem(label, key)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        header.addWidget(self.sort_combo)

        play_all_btn = QPushButton("  播放全部")
        play_all_btn.setObjectName("Ghost")
        play_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(play_all_btn, "play", 14, "text")
        play_all_btn.clicked.connect(self.play_all_requested.emit)
        header.addWidget(play_all_btn)

        self.np_btn = QPushButton()
        self.np_btn.setObjectName("ControlBtn")
        self.np_btn.setToolTip("正在播放")
        self.np_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(self.np_btn, "note", 16, "dim")
        self.np_btn.clicked.connect(self.now_playing_requested.emit)
        header.addWidget(self.np_btn)
        root.addLayout(header)

        # ---- 列头 ----
        self._column_header = QWidget()
        col_header = QHBoxLayout(self._column_header)
        col_header.setContentsMargins(8, 2, 6, 2)
        col_header.setSpacing(8)
        col_header.addSpacing(_LEAD_W)
        col_header.addSpacing(_COVER_W)
        for text, stretch in (("歌曲", _STRETCH_TITLE), ("艺人", _STRETCH_ARTIST), ("专辑", _STRETCH_ALBUM)):
            lbl = QLabel(text)
            lbl.setObjectName("ColumnHeader")
            col_header.addWidget(lbl, stretch)
        fmt_lbl = QLabel("格式")
        fmt_lbl.setObjectName("ColumnHeader")
        fmt_lbl.setFixedWidth(_FMT_W)
        fmt_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col_header.addWidget(fmt_lbl)
        time_lbl = QLabel("时长")
        time_lbl.setObjectName("ColumnHeader")
        time_lbl.setFixedWidth(_TIME_W)
        time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        col_header.addWidget(time_lbl)
        col_header.addSpacing(_ROWBTN_W * 2)
        root.addWidget(self._column_header)

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

    def set_tracks(self, tracks: list[Track], cover_getter, current_tid: str | None,
                   favorite_getter=None) -> None:
        """cover_getter: callable(track) -> QPixmap；favorite_getter: callable(track) -> bool"""
        # 保持滚动位置，避免刷新（如点心）后跳回转
        scroll_value = self.list.verticalScrollBar().value()
        self._tracks = list(tracks)
        self._current_tid = current_tid
        self.list.clear()
        for i, track in enumerate(self._tracks):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, track.id)
            item.setSizeHint(QSize(100, 52))
            self.list.addItem(item)
            row = TrackItemWidget()
            is_fav = bool(favorite_getter(track)) if favorite_getter else False
            row.favorite_toggled.connect(self.favorite_toggled.emit)
            row.more_btn.clicked.connect(
                lambda _=False, t=track, b=row.more_btn: self._show_row_menu(t.id, b))
            row.cover.clicked.connect(
                lambda _=False, t=track: self.track_activated.emit(t.id, self._tracks.index(t)))
            row.set_data(track, cover_getter(track), i, is_fav)
            self.list.setItemWidget(item, row)
        self.empty_label.setVisible(not self._tracks)
        self.list.setVisible(bool(self._tracks))
        self._column_header.setVisible(bool(self._tracks))
        self.list.verticalScrollBar().setValue(scroll_value)
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

    def set_now_playing_active(self, active: bool) -> None:
        ic.bind_icon(self.np_btn, "note", 16, "accent" if active else "dim")
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

    def _menu_actions(self):
        return [
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

    def _build_menu(self, tid: str) -> tuple[QMenu, dict]:
        menu = QMenu(self)
        buttons = {}
        for key, label, enabled in self._menu_actions():
            act = menu.addAction(label)
            act.setEnabled(enabled)
            buttons[key] = act
        return menu, buttons

    def _show_row_menu(self, tid: str, button: QPushButton) -> None:
        menu, buttons = self._build_menu(tid)
        chosen = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        self._emit_chosen(tid, chosen, buttons)

    def _on_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        tid = item.data(Qt.ItemDataRole.UserRole)
        if not tid:
            return
        menu, buttons = self._build_menu(tid)
        chosen = menu.exec(self.list.mapToGlobal(pos))
        self._emit_chosen(tid, chosen, buttons)

    def _emit_chosen(self, tid: str, chosen, buttons: dict) -> None:
        if chosen is None:
            return
        for key, act in buttons.items():
            if act == chosen:
                self.context_action.emit(tid, key)
                return
