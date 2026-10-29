# -*- coding: utf-8 -*-
"""歌词面板：同步高亮 + 平滑自动滚动 + 点击跳转 + 播放动效。

v2.6.4 起引入「歌词播放动效」（单选）：
- none        无特效（当前行加粗 + 强调色，字号 +3，行为与之前一致）；
- zoom        当前行放大（字号 +6，更醒目）；
- typewriter  打字机（当前行按播放进度逐字出现）；
- karaoke     颜色覆盖（已唱的字用强调色，未唱的字保持淡色，随进度推进）。

逐字效果靠 `_LyricDelegate` 自绘：每行仍是 QListWidgetItem（`text()`/`foreground()`
等数据不变，测试兼容），但文字由 delegate 按「当前行 + 行内进度」分段绘制。
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (QLabel, QListWidget, QListWidgetItem, QMenu,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from app.lyrics import LyricLine, lyric_index_at
from app.models import LYRICS_EFFECTS
from ui.theme import ACCENT, current_theme

# 空状态默认文案：`set_empty(hint)` 传入临时文案后，下一次不带参数要能复原
EMPTY_HINT = "暂无歌词\n支持同名 .lrc 文件与内嵌歌词"

# 歌词行高：要容纳 zoom 放大后的字号（基础 13px + 6pt ≈ 19px），并留上下余量
_LINE_HEIGHT = 36

# 当前行字号放大档：none/typewriter/karaoke 用 +3（与历史一致），zoom 用 +6
_ZOOM_DELTA = 6
_NORMAL_DELTA = 3


def _normal_color() -> QColor:
    """歌词常态色随主题走。

    不能在类属性里 `QColor(TEXT_DIM)`：那是 import 时求值，模块级 `__getattr__`
    当时返回的是深色主题的值，之后切到浅色主题仍是旧的灰（被冻结）。
    """
    return QColor(current_theme().TEXT_DIM)


def _bump_font(font: QFont, delta: int) -> QFont:
    """把字号放大 delta，**优先像素单位**。

    踩坑：delegate 里 `option.font` 经 QSS `font-size: 13px` 后是 `pixelSize=13,
    pointSize=-1`（而 `item.font()` 却返回 `pointSize=9`，两条路径表示法不同）。
    若直接 `setPointSize(pointSize() + delta)` 会得到 `setPointSize(2)`，把当前行
    缩成 2pt 的一小截。
    """
    font = QFont(font)
    if font.pixelSize() > 0:
        font.setPixelSize(font.pixelSize() + delta)
    else:
        font.setPointSize(font.pointSize() + delta)
    return font


def _uncovered_color() -> QColor:
    """karaoke「未唱到的字」用半透明常态色：比已唱的强调色明显更暗。

    直接沿用 TEXT_DIM 会和强调色同属蓝紫调、对比太弱（深色主题下尤其如此），
    压到 ~35% 不透明度后，未唱部分沉进背景，已唱部分自然浮出来。
    """
    color = _normal_color()
    color.setAlpha(90)
    return color


class _LyricDelegate(QStyledItemDelegate):
    """自绘歌词行：背景透明，文字按效果（放大/打字机/颜色覆盖）绘制。"""

    def __init__(self, panel: "LyricsPanel"):
        super().__init__(panel)
        self._panel = panel

    def sizeHint(self, option, index):  # noqa: N802
        size = super().sizeHint(option, index)
        # 保证能容纳当前行放大后的字号（zoom 加 6px 是上限）
        metrics = QFontMetrics(_bump_font(option.font, _ZOOM_DELTA))
        size.setHeight(max(size.height(), metrics.height() + 12))
        return size

    def paint(self, painter, option, index):  # noqa: N802
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        rect = option.rect
        panel = self._panel
        is_current = panel._mode == "synced" and index.row() == panel._current_index
        self._paint_text(painter, rect, text, option.font, is_current)

    def _paint_text(self, painter, rect, text, base_font, is_current):
        effect = self._panel._effect if is_current else "none"
        progress = self._panel._progress_in_line if is_current else 0.0

        font = base_font
        if is_current:
            font = _bump_font(base_font, _ZOOM_DELTA if effect == "zoom" else _NORMAL_DELTA)
            font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()

        # 打字机：按行内进度截断文本，进度 0 时整行空白（从空开始逐字打出）
        if is_current and effect == "typewriter":
            n = round(len(text) * progress)
            text = text[:n]

        total_w = metrics.horizontalAdvance(text)
        x = rect.x() + (rect.width() - total_w) / 2.0
        y = rect.y() + (rect.height() + metrics.ascent() - metrics.descent()) / 2.0

        if is_current and effect == "karaoke" and progress > 0:
            n = round(len(text) * progress)
            head, tail = text[:n], text[n:]
            head_w = metrics.horizontalAdvance(head)
            painter.setPen(QColor(ACCENT))
            painter.drawText(int(x), int(y), head)
            painter.setPen(_uncovered_color())
            painter.drawText(int(x + head_w), int(y), tail)
        else:
            painter.setPen(QColor(ACCENT) if is_current else _normal_color())
            painter.drawText(int(x), int(y), text)


class LyricsPanel(QWidget):
    seek_requested = Signal(int)   # ms
    # 右键「重新联网匹配歌词」：负缓存（7 天）会让查不到的歌不再自动重试，
    # 这里给用户一个手动重来的入口
    retry_online_requested = Signal()
    # 右键「导入歌词文件 / 批量导入歌词」：用户自己提供歌词（v2.6.2）
    import_lyrics_requested = Signal()
    batch_import_requested = Signal()
    # 右键「在线搜索歌词」：联网也匹配不到时，去网页自己搜（v2.6.4）
    search_online_requested = Signal()
    # 右键「联网对齐歌词」：把纯文本歌词转成带时间轴的 LRC（v2.6.6）
    align_lyrics_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.list = QListWidget()
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.itemClicked.connect(self._on_clicked)
        self._delegate = _LyricDelegate(self)
        self.list.setItemDelegate(self._delegate)
        root.addWidget(self.list, 1)

        # 歌词来源小字（如「来源：LRCLIB」/「本地歌词 · 同名 .lrc」）：
        # 只在有歌词时显示，挂在列表下方，回答「这歌词是从哪来的」。
        self.source_label = QLabel("")
        self.source_label.setObjectName("LyricsSource")
        self.source_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_label.setVisible(False)
        root.addWidget(self.source_label)

        self.empty_label = QLabel(EMPTY_HINT)
        self.empty_label.setObjectName("Dim")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty_label)

        # 「没有歌词」时占满整块的是 empty_label，列表是隐藏的，所以两个都要挂菜单
        for widget in (self.list, self.empty_label):
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(self._show_menu)

        self._lines: list[LyricLine] = []
        self._plain: list[str] = []
        self._mode = "empty"  # empty | synced | plain
        self._current_index = -1
        self._progress_in_line = 0.0
        self._effect = "none"
        self._anim: QPropertyAnimation | None = None
        self.set_empty()

    # ---------- 对外 ----------

    def set_effect(self, effect: str) -> None:
        """切换歌词播放动效；非法值回落到 none。立即重绘。"""
        effect = effect if effect in LYRICS_EFFECTS else "none"
        if effect != self._effect:
            self._effect = effect
            self.list.viewport().update()

    def set_synced(self, lines: list[LyricLine]) -> None:
        self._mode = "synced" if lines else "empty"
        self._lines = list(lines)
        self._plain = []
        self._current_index = -1
        self._progress_in_line = 0.0
        self.list.clear()
        if lines:
            for line in lines:
                item = QListWidgetItem(line.text)
                item.setData(Qt.ItemDataRole.UserRole, line.time_ms)
                item.setForeground(_normal_color())
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.list.addItem(item)
        self._refresh_visibility()

    def set_plain(self, lines: list[str]) -> None:
        self._mode = "plain" if lines else "empty"
        self._plain = list(lines)
        self._lines = []
        self._current_index = -1
        self._progress_in_line = 0.0
        self.list.clear()
        if lines:
            for text in lines:
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, -1)
                item.setForeground(_normal_color())
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.list.addItem(item)
        self._refresh_visibility()

    def set_source(self, text: str | None) -> None:
        """显示/隐藏歌词来源小字。传空串或 None 即隐藏。"""
        self.source_label.setText(text or "")
        self.source_label.setVisible(bool(text))

    def set_empty(self, hint: str | None = None) -> None:
        self._mode = "empty"
        self._lines = []
        self._plain = []
        self._current_index = -1
        self._progress_in_line = 0.0
        self.list.clear()
        self.empty_label.setText(hint or EMPTY_HINT)
        self.set_source(None)
        self._refresh_visibility()

    def update_position(self, position_ms: int) -> None:
        if self._mode != "synced" or not self._lines:
            return
        index = lyric_index_at(self._lines, position_ms)
        progress = self._line_progress(index, position_ms)
        if index == self._current_index:
            # 行不变：只有逐字效果需要按进度重绘
            if (self._effect in ("typewriter", "karaoke")
                    and abs(progress - self._progress_in_line) > 0.01):
                self._progress_in_line = progress
                self.list.viewport().update()
            return
        self._current_index = index
        self._progress_in_line = progress
        if 0 <= index < self.list.count():
            self._smooth_scroll_to(self.list.item(index))
        self.list.viewport().update()

    # ---------- 内部 ----------

    def _line_progress(self, index: int, position_ms: int) -> float:
        """当前行内的播放进度 0~1（打字机/颜色覆盖按它推进）。"""
        if index < 0 or index >= len(self._lines):
            return 0.0
        start = self._lines[index].time_ms
        end = (self._lines[index + 1].time_ms if index + 1 < len(self._lines)
               else start + 3000)
        span = end - start
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (position_ms - start) / span))

    def _refresh_visibility(self) -> None:
        has = self._mode != "empty"
        self.list.setVisible(has)
        self.empty_label.setVisible(not has)

    def _smooth_scroll_to(self, item: QListWidgetItem) -> None:
        bar = self.list.verticalScrollBar()
        rect = self.list.visualItemRect(item)
        if rect.height() == 0:
            return
        target = rect.top() + rect.height() // 2 - self.list.viewport().height() // 2
        target = max(bar.minimum(), min(bar.maximum(), target))
        if target == bar.value():
            return
        if self._anim is None:
            self._anim = QPropertyAnimation(bar, b"value", self)
            self._anim.setDuration(260)
            self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.stop()
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.start()

    def _on_clicked(self, item: QListWidgetItem) -> None:
        if self._mode != "synced":
            return
        time_ms = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(time_ms, int) and time_ms >= 0:
            self.seek_requested.emit(time_ms)

    def _show_menu(self, pos) -> None:
        menu = QMenu(self)
        import_one = QAction("导入歌词文件…", menu)
        import_one.triggered.connect(self.import_lyrics_requested.emit)
        menu.addAction(import_one)
        import_batch = QAction("批量导入歌词…", menu)
        import_batch.triggered.connect(self.batch_import_requested.emit)
        menu.addAction(import_batch)
        menu.addSeparator()
        retry = QAction("重新联网匹配歌词", menu)
        retry.triggered.connect(self.retry_online_requested.emit)
        menu.addAction(retry)
        search = QAction("在线搜索歌词…", menu)
        search.triggered.connect(self.search_online_requested.emit)
        menu.addAction(search)
        align = QAction("联网对齐歌词（纯文本 → 时间轴）", menu)
        align.triggered.connect(self.align_lyrics_requested.emit)
        menu.addAction(align)
        sender = self.sender()
        anchor = sender.mapToGlobal(pos) if isinstance(sender, QWidget) else pos
        menu.exec(anchor)
