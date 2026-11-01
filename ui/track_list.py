# -*- coding: utf-8 -*-
"""曲目列表（v2.1.4）：两行页头 + 列头 + 行（序号/封面/歌曲/艺人/专辑/格式/大小/时长/爱心/更多）。

v2.1.4 视觉与排序改造：
- 页头拆两行：第一行「大标题 + 播放全部/正在播放」，第二行「统计 + 排序」，
  标题字号与行距统一，信息层次（标题 > 统计 > 控件）一眼可辨；
- 列头与行共用同一套槽位（含尺寸常量与间距），修掉此前列头比行右移/左移的错位；
- 新增「大小」列（文件体积），同时作为排序维度；
- 排序改为「维度 + 方向」预设下拉（含「最近导入」「文件大小（大→小）」等），
  选中即确定升降序，控件本身即当前排序的展示；
- 当前行：强调色标题 + 序号位均衡器动效条；爱心/更多按钮、右键菜单、拖拽排序、
  空态、滚动位置保持等既有行为保持不变。
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QModelIndex, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from app.filesize import format_size
from app.lyrics import format_time
from app.models import Track, VIDEO_FORMATS
from app.sorting import SORT_PRESETS, preset_by_id
from ui import icons as ic
from ui.theme import current_theme
from ui.widgets import ChevronComboBox, ClickableCover, ElidedLabel, EqualizerBars

# 列宽（列头与行共用同一套常量，保证逐列对齐）
_LEAD_W, _COVER_W, _FMT_W, _SIZE_W, _TIME_W, _ROWBTN_W = 22, 40, 52, 56, 44, 28
# 弹性列伸展系数：歌曲 3 / 艺人 2 / 专辑 2
_STRETCH_TITLE, _STRETCH_ARTIST, _STRETCH_ALBUM = 3, 2, 2
# 行内容的内边距（见 QSS `QListWidget::item { margin: 2px 8px }` + TrackItemWidget 的 8/6）
_ITEM_MARGIN_H = 8
_ROW_PAD_L, _ROW_PAD_R = 8, 6
_HEAD_PAD_L = _ITEM_MARGIN_H + _ROW_PAD_L          # 16
_HEAD_PAD_R = _ITEM_MARGIN_H + _ROW_PAD_R          # 14
_ROW_PAD_V = 6
_ROW_H = 52
_SPACING = 8


class _TrackListWidget(QListWidget):
    """列表本体：拖拽时在落点画一条强调色插入线（v3.2.0）。

    为什么不用 Qt 自带的 drop indicator：每行都是 `setItemWidget` 塞进去的自定义
    控件，原生指示线画在行控件底下，被完全盖住 —— 拖动时看不见会落在哪，等于没有
    预览。这里自己算目标行、自己画，保证「实时预览位置」真的看得见。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drop_row: int | None = None
        # 关掉原生指示线，否则与自绘那条同时出现，看着像有两个落点
        self.setDropIndicatorShown(False)

    # ---- 拖拽预览 ----

    def _row_at(self, pos) -> int:
        """落点 → 插入位置：落在行的上半部分插到它前面，下半部分插到它后面。"""
        index = self.indexAt(pos)
        if not index.isValid():
            return self.count()          # 空白区 = 放到最后
        rect = self.visualItemRect(self.item(index.row()))
        if rect.height() and pos.y() > rect.center().y():
            return index.row() + 1
        return index.row()

    def _set_drop_row(self, row: int | None) -> None:
        if row != self._drop_row:
            self._drop_row = row
            self.viewport().update()

    def dragMoveEvent(self, event):  # noqa: N802
        super().dragMoveEvent(event)
        self._set_drop_row(self._row_at(event.position().toPoint()))

    def dragLeaveEvent(self, event):  # noqa: N802
        self._set_drop_row(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):  # noqa: N802
        self._set_drop_row(None)
        super().dropEvent(event)

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        if self._drop_row is None or not self.count():
            return
        row = min(self._drop_row, self.count() - 1)
        rect = self.visualItemRect(self.item(row))
        if not rect.isValid():
            return
        y = rect.bottom() - 1 if self._drop_row > row else rect.top() + 1
        color = QColor(current_theme().ACCENT)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(color, 2))
        painter.drawLine(rect.left() + 6, y, rect.right() - 6, y)
        # 两端各一个圆点：一条光秃秃的线容易被当成行分隔线
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for x in (rect.left() + 6, rect.right() - 6):
            painter.drawEllipse(QPoint(x, y), 3, 3)
        painter.end()


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


def _spacer(width: int) -> QWidget:
    """固定宽度的占位槽——列头用它对齐行里不带文字的槽位（序号/封面/行按钮）。"""
    w = QWidget()
    w.setFixedWidth(width)
    return w


def _elastic(label: QLabel) -> QLabel:
    """让弹性列的宽度只由 stretch 决定。

    QBoxLayout 是「先按 sizeHint 给底宽，再按 stretch 分余量」；列头文字（"歌曲"）
    与行内文字（"晴天"）sizeHint 不同，同 stretch 也会算出不同宽度，列会逐列漂移。
    忽略 sizeHint 后两侧宽度完全一致，列头才能与行严格对齐。
    """
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return label


def _frozen_label(text: str, width: int, align: Qt.AlignmentFlag) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("ColumnHeader")
    lbl.setFixedWidth(width)
    lbl.setAlignment(align)
    return lbl


class TrackItemWidget(QWidget):
    """列表行内容：[序号/动效条] [封面] [歌曲] [艺人] [专辑] [格式] [大小] [时长] [♥] [⋯]"""

    favorite_toggled = Signal(str, bool)  # (track_id, 目标状态)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(_ROW_H)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(_ROW_PAD_L, _ROW_PAD_V, _ROW_PAD_R, _ROW_PAD_V)
        layout.setSpacing(_SPACING)

        self.leading = QLabel()
        self.leading.setObjectName("Dim")
        self.leading.setFixedWidth(_LEAD_W)
        self.leading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.leading)

        self.cover = ClickableCover()
        # 行内容可用高度 = 52 - 6*2 = 40，封面正好铺满，避免缩放下采样
        self.cover.setFixedSize(_COVER_W, _COVER_W)
        self.cover.setScaledContents(True)
        layout.addWidget(self.cover)

        self.title = ElidedLabel()
        self.title.setObjectName("TrackTitle")
        layout.addWidget(_elastic(self.title), _STRETCH_TITLE)

        self.artist = ElidedLabel()
        self.artist.setObjectName("TrackSub")
        layout.addWidget(_elastic(self.artist), _STRETCH_ARTIST)

        self.album = ElidedLabel()
        self.album.setObjectName("TrackSub")
        layout.addWidget(_elastic(self.album), _STRETCH_ALBUM)

        self.fmt = QLabel()
        self.fmt.setObjectName("FmtBadge")
        self.fmt.setFixedSize(_FMT_W, 18)
        self.fmt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.fmt)

        self.size = QLabel()
        self.size.setObjectName("Dim")
        self.size.setFixedWidth(_SIZE_W)
        self.size.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.size)

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

    def set_data(self, track: Track, cover_pixmap, index: int, is_fav: bool,
                 size: int = 0) -> None:
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
        self.size.setText(format_size(size))
        self.size.setToolTip("文件大小：未知" if size <= 0 else f"文件大小：{format_size(size)}")
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


class TrackList(QWidget):
    track_activated = Signal(str, int)      # (track_id, 视图内索引)
    context_action = Signal(str, str)       # (track_id, action)
    reordered = Signal(list, int)            # (被拖动的 track_id 列表, 新位置)
    play_all_requested = Signal()
    sort_changed = Signal(str)              # 排序预设 id，形如 "size:desc"
    now_playing_requested = Signal()
    favorite_toggled = Signal(str, bool)    # (track_id, 目标收藏状态)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_page_header())
        root.addWidget(self._build_column_header())

        # ---- 列表 ----
        self.list = _TrackListWidget()
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_menu)
        self.list.itemDoubleClicked.connect(self._on_double_clicked)
        self.list.model().rowsMoved.connect(self._on_rows_moved)
        # 滚动条出现/消失会改变视口宽度，列头必须跟着让位，否则整列偏 10px
        self.list.verticalScrollBar().rangeChanged.connect(lambda *_: self._sync_header_inset())
        root.addWidget(self.list, 1)

        # ---- 空状态 ----
        root.addWidget(self._build_empty_state(), 1)

        self._tracks: list[Track] = []
        self._current_tid: str | None = None
        self._drag_enabled = False
        self._in_playlist = False
        self._suppress_sort_signal = False
        self._size_getter: Callable[[Track], int] = lambda _t: 0
        self._sync_header_inset()

    # ---------- 装配 ----------

    def _build_page_header(self) -> QWidget:
        head = QWidget()
        head.setObjectName("PageHeader")
        outer = QVBoxLayout(head)
        outer.setContentsMargins(20, 16, 20, 12)
        outer.setSpacing(10)

        # 第一行：标题 + 主操作
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.title_label = QLabel("音乐库")
        self.title_label.setObjectName("PageTitle")
        row1.addWidget(self.title_label)
        row1.addStretch(1)

        play_all_btn = QPushButton("  播放全部")
        play_all_btn.setObjectName("Ghost")
        play_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(play_all_btn, "play", 14, "text")
        play_all_btn.clicked.connect(self.play_all_requested.emit)
        self.play_all_btn = play_all_btn
        row1.addWidget(play_all_btn)

        self.np_btn = QPushButton()
        self.np_btn.setObjectName("ControlBtn")
        self.np_btn.setToolTip("正在播放")
        self.np_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ic.bind_icon(self.np_btn, "note", 16, "dim")
        self.np_btn.clicked.connect(self.now_playing_requested.emit)
        row1.addWidget(self.np_btn)
        outer.addLayout(row1)

        # 第二行：统计 + 排序
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.count_label = QLabel("共 0 首")
        self.count_label.setObjectName("Dim")
        row2.addWidget(self.count_label)

        self.stats_label = QLabel()
        self.stats_label.setObjectName("Stats")
        self.stats_label.hide()
        row2.addWidget(self.stats_label)
        row2.addStretch(1)

        sort_caption = QLabel("排序")
        sort_caption.setObjectName("Stats")
        row2.addWidget(sort_caption)

        self.sort_combo = ChevronComboBox()
        self.sort_combo.setObjectName("SortCombo")
        self.sort_combo.setToolTip("按维度与方向排序")
        self.sort_combo.setMaxVisibleItems(len(SORT_PRESETS) + 4)
        prev_group: str | None = None
        for preset in SORT_PRESETS:
            if prev_group is not None and preset.group != prev_group:
                self.sort_combo.insertSeparator(self.sort_combo.count())
            self.sort_combo.addItem(preset.label, preset.id)
            prev_group = preset.group
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        row2.addWidget(self.sort_combo)
        outer.addLayout(row2)
        return head

    def _build_column_header(self) -> QWidget:
        self._column_header = QWidget()
        self._column_header.setObjectName("ColumnHeaderBar")
        self._column_header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        col = QHBoxLayout(self._column_header)
        col.setContentsMargins(_HEAD_PAD_L, 2, _HEAD_PAD_R, 2)
        col.setSpacing(_SPACING)
        self._col_header_layout = col

        # 槽位与 TrackItemWidget 一一对应（含无文字的占位槽），否则列会整体错位
        col.addWidget(_spacer(_LEAD_W))
        col.addWidget(_spacer(_COVER_W))
        for text, stretch in (("歌曲", _STRETCH_TITLE), ("艺人", _STRETCH_ARTIST),
                              ("专辑", _STRETCH_ALBUM)):
            lbl = QLabel(text)
            lbl.setObjectName("ColumnHeader")
            col.addWidget(_elastic(lbl), stretch)
        col.addWidget(_frozen_label("格式", _FMT_W, Qt.AlignmentFlag.AlignCenter))
        col.addWidget(_frozen_label("大小", _SIZE_W,
                                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        col.addWidget(_frozen_label("时长", _TIME_W,
                                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        col.addWidget(_spacer(_ROWBTN_W))
        col.addWidget(_spacer(_ROWBTN_W))
        return self._column_header

    def _build_empty_state(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(20, 0, 20, 40)
        layout.setSpacing(8)
        layout.addStretch(1)
        glyph = QLabel("♫")
        glyph.setObjectName("EmptyGlyph")
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(glyph)
        self.empty_label = QLabel("还没有歌曲\n点击左下角「导入音乐」开始吧")
        self.empty_label.setObjectName("EmptyText")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label)
        layout.addStretch(1)
        self._empty_box = box
        box.hide()
        return box

    # ---------- 对外 ----------

    def set_context_config(self, in_playlist: bool, drag_enabled: bool) -> None:
        """in_playlist: 是否歌单视图（启用移除/排序类菜单项）。"""
        self._in_playlist = in_playlist
        self.set_drag_enabled(drag_enabled)

    def set_header(self, title: str, count: int, total_ms: int = 0) -> None:
        self.title_label.setText(title)
        self.count_label.setText(f"共 {count} 首")
        if count and total_ms > 0:
            self.stats_label.setText(f"· 总时长 {format_time(total_ms)}")
            self.stats_label.show()
        else:
            self.stats_label.clear()
            self.stats_label.hide()

    def set_tracks(self, tracks: list[Track], cover_getter, current_tid: str | None,
                   favorite_getter=None, size_getter=None) -> None:
        """cover_getter: callable(track) -> QPixmap；favorite_getter: callable(track) -> bool
        size_getter: callable(track) -> 字节数（用于「大小」列）"""
        # 保持滚动位置，避免刷新（如点心）后跳回转
        scroll_value = self.list.verticalScrollBar().value()
        self._tracks = list(tracks)
        self._current_tid = current_tid
        self._size_getter = size_getter or (lambda _t: 0)
        self.list.clear()
        for i, track in enumerate(self._tracks):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, track.id)
            item.setSizeHint(QSize(100, _ROW_H))
            self.list.addItem(item)
            row = TrackItemWidget()
            is_fav = bool(favorite_getter(track)) if favorite_getter else False
            row.favorite_toggled.connect(self.favorite_toggled.emit)
            row.more_btn.clicked.connect(
                lambda _=False, t=track, b=row.more_btn: self._show_row_menu(t.id, b))
            row.cover.clicked.connect(
                lambda _=False, t=track: self.track_activated.emit(t.id, self._tracks.index(t)))
            row.set_data(track, cover_getter(track), i, is_fav, self._size_getter(track))
            self.list.setItemWidget(item, row)
        has_tracks = bool(self._tracks)
        self._empty_box.setVisible(not has_tracks)
        self.list.setVisible(has_tracks)
        self._column_header.setVisible(has_tracks)
        self.play_all_btn.setEnabled(has_tracks)
        self.list.verticalScrollBar().setValue(scroll_value)
        self.set_current_track(current_tid)
        self._sync_header_inset()

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

    def set_sort(self, sort_id: str) -> None:
        """定位到指定排序预设（旧式纯维度 key 会被归一化，不报错）。"""
        target = preset_by_id(sort_id).id
        self._suppress_sort_signal = True
        for i in range(self.sort_combo.count()):
            if self.sort_combo.itemData(i) == target:
                self.sort_combo.setCurrentIndex(i)
                break
        self._suppress_sort_signal = False

    def set_now_playing_active(self, active: bool) -> None:
        ic.bind_icon(self.np_btn, "note", 16, "accent" if active else "dim")
        self.np_btn.setProperty("active", "true" if active else "false")
        self.np_btn.style().unpolish(self.np_btn)
        self.np_btn.style().polish(self.np_btn)

    # ---------- 内部 ----------

    def _sync_header_inset(self) -> None:
        """列头右侧让出滚动条宽度：滚动条一出现视口就变窄，列头不跟就会错位。"""
        scrollbar = self.list.verticalScrollBar()
        extra = scrollbar.width() if scrollbar.isVisible() else 0
        self._col_header_layout.setContentsMargins(_HEAD_PAD_L, 2, _HEAD_PAD_R + extra, 2)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_header_inset()

    def _on_sort_changed(self, _index) -> None:
        if self._suppress_sort_signal:
            return
        sort_id = self.sort_combo.currentData()  # 分隔符项为 None
        if sort_id:
            self.sort_changed.emit(sort_id)

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
        new_index = max(0, new_index)
        # v3.2.0：整块一起报（原来只报 moved[0]，多选拖一整段时上层只能看到第一首，
        # 落盘顺序会和眼睛看到的差一截）。上层负责把这几个 id 整体移动到新位置。
        self.reordered.emit([t.id for t in moved], new_index)
        # 同步内部顺序，保持 UI 与数据一致
        rest = self._tracks[:start] + self._tracks[end + 1:]
        new_index = max(0, min(new_index, len(rest)))
        self._tracks = rest[:new_index] + moved + rest[new_index:]

    def _menu_actions(self):
        # v3.2.0：去掉「上移 / 下移」—— 改成直接拖拽，拖动时有插入位置预览，
        # 一次能把歌拖到任意位置，比连点十几次上移快得多。
        return [
            ("play", "播放", True),
            ("add_to_playlist", "添加到歌单…", True),
            ("remove_from_playlist", "从歌单移除", self._in_playlist),
            ("bind_lyrics", "导入歌词文件…", True),
            ("refresh", "重新读取歌曲信息", True),
            ("locate", "在文件资源管理器中显示", True),
            ("remove_from_library", "移除出音乐库", True),
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
