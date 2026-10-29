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

from app.lyrics import LyricLine, lyric_index_at, pair_bilingual
from app.models import LYRICS_EFFECTS
from ui.theme import ACCENT, current_theme

# 空状态默认文案：`set_empty(hint)` 传入临时文案后，下一次不带参数要能复原
EMPTY_HINT = "暂无歌词\n支持同名 .lrc 文件与内嵌歌词"

# 歌词行高：要容纳 zoom 放大后的字号（基础 13px + 6pt ≈ 19px），并留上下余量
_LINE_HEIGHT = 36

# 当前行字号放大档：none/typewriter/karaoke 用 +3（与历史一致），zoom 用 +6
_ZOOM_DELTA = 6
_NORMAL_DELTA = 3

# 译文比原文小多少（像素）。双语歌词里译文是次要信息，压小一档 + 降透明度，
# 让视线先落在正在唱的原文上。
_SUB_DELTA = -3

# 译文存在 item 的这个 role 上（主行文本仍放 DisplayRole，兼容旧测试读 item.text()）
_TRANSLATION_ROLE = Qt.ItemDataRole.UserRole + 1


def _normal_color() -> QColor:
    """歌词常态色随主题走。

    不能在类属性里 `QColor(TEXT_DIM)`：那是 import 时求值，模块级 `__getattr__`
    当时返回的是深色主题的值，之后切到浅色主题仍是旧的灰（被冻结）。
    """
    return QColor(current_theme().TEXT_DIM)


def _translation_color(is_current: bool) -> QColor:
    """译文色：比原文常态色更淡，当前句时提亮到接近常态（整句一起高亮）。

    非当前句用 165 而不是更低：深色主题下 TEXT_DIM 本身偏暗，再压透明度会在
    夜空底色上糊成一片（实测 150 时小字要凑近才认得出）。
    """
    color = _normal_color()
    color.setAlpha(240 if is_current else 165)
    return color


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


def _typed_split(main_len: int, sub_len: int, progress: float) -> tuple[int, int]:
    """逐字推进时，原文 / 译文各自已显示的字数。

    进度按**两行字符总数**算：原文唱完自然轮到译文，两行连着打出而不是各打各的。
    只数主行的话，译文会永远整行一次性蹦出来，和原文的节奏脱节。
    """
    if progress <= 0:
        return 0, 0
    total = main_len + sub_len
    typed = round(total * progress)
    main_typed = min(typed, main_len)
    return main_typed, max(0, typed - main_len)


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
        height = max(size.height(), metrics.height() + 12)
        # 双语：一层原文 + 一层译文，高度要按两层算，否则译文会被裁掉半截
        if index.data(_TRANSLATION_ROLE):
            sub_metrics = QFontMetrics(_bump_font(option.font, _ZOOM_DELTA + _SUB_DELTA))
            height = max(height, metrics.height() + sub_metrics.height() + 14)
        size.setHeight(height)
        return size

    def paint(self, painter, option, index):  # noqa: N802
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        sub = index.data(_TRANSLATION_ROLE) or ""
        panel = self._panel
        is_current = panel._mode == "synced" and index.row() == panel._current_index
        self._paint_block(painter, option.rect, text, sub, option.font, is_current)

    def _paint_block(self, painter, rect, text, sub, base_font, is_current):
        """画「一句」：原文一行 +（可选）译文一行，两行作为一个整体垂直居中。"""
        panel = self._panel
        effect = panel._effect if is_current else "none"
        progress = panel._progress_in_line if is_current else 0.0

        delta = (_ZOOM_DELTA if effect == "zoom" else _NORMAL_DELTA) if is_current else 0
        main_font = _bump_font(base_font, delta)
        if is_current:
            main_font.setBold(True)
        main_metrics = QFontMetrics(main_font)
        main_h = main_metrics.height()

        sub_font = _bump_font(base_font, delta + _SUB_DELTA)
        sub_metrics = QFontMetrics(sub_font)
        sub_h = sub_metrics.height() if sub else 0

        top = rect.y() + (rect.height() - (main_h + sub_h)) / 2.0

        # 逐字进度按「两行字符总数」推进：原文唱完自然轮到译文
        main_typed, sub_typed = len(text), len(sub)
        if is_current and effect in ("typewriter", "karaoke"):
            main_typed, sub_typed = _typed_split(len(text), len(sub), progress)

        main_sung = QColor(ACCENT) if is_current else _normal_color()
        self._draw_line(painter, rect, text, main_font, main_metrics,
                        top + main_metrics.ascent(), main_typed,
                        main_sung, _uncovered_color(), is_current, effect)
        if sub:
            self._draw_line(painter, rect, sub, sub_font, sub_metrics,
                            top + main_h + sub_metrics.ascent(), sub_typed,
                            _translation_color(is_current), _translation_color(False),
                            is_current, effect)

    def _draw_line(self, painter, rect, text, font, metrics, baseline, typed,
                   sung_color, unsung_color, is_current, effect):
        """水平居中画一行；当前行的逐字效果按 `typed`（已显示字数）分段上色。"""
        if not text:
            return
        painter.setFont(font)
        total_w = metrics.horizontalAdvance(text)
        x = int(rect.x() + (rect.width() - total_w) / 2.0)
        y = int(baseline)

        if not is_current or effect in ("none", "zoom"):
            painter.setPen(sung_color)
            painter.drawText(x, y, text)
            return

        head, tail = text[:typed], text[typed:]
        if head:
            painter.setPen(sung_color)
            painter.drawText(x, y, head)
        if tail and effect == "karaoke":
            # 打字机不画未打出的部分；颜色覆盖则把未唱的字画成半透明
            painter.setPen(unsung_color)
            painter.drawText(x + metrics.horizontalAdvance(head), y, tail)


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
    # 右键「转成 .lrc 文件（本地近似对齐）」：纯文本歌词本地对齐成 LRC（v2.6.9）
    align_local_requested = Signal()
    # 右键「转成 .lrc 文件（联网精确对齐）」：联网 LyricTimestamps 对齐（v2.6.6，兜底）
    align_lyrics_requested = Signal()
    # 右键「整体提前/延后 0.5s」：消掉对齐后的系统性偏移（v2.6.12）
    shift_lyrics_requested = Signal(int)

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
                if line.translation:
                    item.setData(_TRANSLATION_ROLE, line.translation)
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
            # 纯文本阶段同样按「句」显示：双语 txt 未对齐前也是 原文 + 译文 两行一层，
            # 而不是 74 行流水账（对不上号的那种样子）。
            for main, sub in pair_bilingual(lines):
                item = QListWidgetItem(main)
                item.setData(Qt.ItemDataRole.UserRole, -1)
                if sub:
                    item.setData(_TRANSLATION_ROLE, sub)
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

    def _scroll_target(self, item: QListWidgetItem) -> int | None:
        """算出「让这一项垂直居中」需要把滚动条挪到哪个值。

        ⚠️ 这里是踩过的坑：`visualItemRect()` 返回的是**视口坐标**（该项相对当前
        可视区左上角的位置，会随滚动变化），而 `bar.value()` 是**内容坐标**（像素
        偏移）。直接拿 `rect.top()` 当目标会漏掉已经滚过的距离 —— 结果是每句只往前
        挪一点点，当前唱的句子永远沉在视口下方被裁掉，用户看到的就是「歌词一直往上
        滚动但始终滚不到位」。必须先换算成内容坐标（value + top）。

        动画进行中再次调用也安全：`bar.value()` 与 `rect.top()` 的中间值相加，仍等于
        该项的内容坐标，不会因为半路重算而漂移。
        """
        rect = self.list.visualItemRect(item)
        if rect.height() == 0:
            return None
        bar = self.list.verticalScrollBar()
        target = (bar.value() + rect.top() + rect.height() // 2
                  - self.list.viewport().height() // 2)
        return max(bar.minimum(), min(bar.maximum(), target))

    def _smooth_scroll_to(self, item: QListWidgetItem) -> None:
        bar = self.list.verticalScrollBar()
        target = self._scroll_target(item)
        if target is None or target == bar.value():
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

    def _build_menu(self) -> QMenu:
        """构建右键菜单（不 exec），便于单测直接检查文案与可用状态。"""
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
        # 两个对齐入口名字必须能一眼区分：本地是纯信号处理估算（可能差几秒），
        # 联网是上传音频做强制对齐（准，但要 Key）。旧文案只差「本地/联网」两个字，
        # 实测过用户点错、以为跑的是联网对齐。
        align_local = QAction("转成 .lrc 文件（本地近似·免 Key）", menu)
        align_local.setStatusTip("离线分析音频节奏，大致跟唱；可能整体差几秒")
        align_local.triggered.connect(self.align_local_requested.emit)
        menu.addAction(align_local)
        align_online = QAction("转成 .lrc 文件（联网精确·需 Key）", menu)
        align_online.setStatusTip("上传音频做强制对齐，逐句卡准；需在设置里填 API Key")
        align_online.triggered.connect(self.align_lyrics_requested.emit)
        menu.addAction(align_online)
        menu.addSeparator()
        earlier = QAction("整体提前 0.5 秒", menu)
        earlier.setStatusTip("对齐后整条时间轴偏晚／偏早时微调（写回 .lrc）")
        earlier.triggered.connect(lambda: self.shift_lyrics_requested.emit(-500))
        menu.addAction(earlier)
        later = QAction("整体延后 0.5 秒", menu)
        later.setStatusTip("对齐后整条时间轴偏晚／偏早时微调（写回 .lrc）")
        later.triggered.connect(lambda: self.shift_lyrics_requested.emit(500))
        menu.addAction(later)
        for action in (earlier, later):
            action.setEnabled(self._mode == "synced")
        return menu

    def _show_menu(self, pos) -> None:
        menu = self._build_menu()
        sender = self.sender()
        anchor = sender.mapToGlobal(pos) if isinstance(sender, QWidget) else pos
        menu.exec(anchor)
