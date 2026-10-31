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

from PySide6.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, Qt, QTimer,
                            Signal)
from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QFontMetrics,
                           QLinearGradient, QPainter, QPen)
from PySide6.QtWidgets import (QLabel, QListWidget, QListWidgetItem, QMenu,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from app.lyrics import LyricLine, is_structure_marker, lyric_index_at, pair_bilingual
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


def _marker_color() -> QColor:
    """段落标记行（`[Verse 1]` / `(间奏)`）用更淡的色。

    它不是唱词，压暗一点才不会让人以为在等这一句开口；也顺带把它和真歌词区分开
    （v2.7.3）。
    """
    color = _normal_color()
    color.setAlpha(140)
    return color


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


def _typed_split(main_len: int, sub_len: int, progress: float,
                 sync: bool = False) -> tuple[int, int]:
    """逐字推进时，原文 / 译文各自已显示的字数。

    两种口径，按动效类型选：

    - `sync=False`（typewriter，v2.6.10 起的口径）：进度按**两行字符总数**算，
      原文打完自然轮到译文，两行连着打出而不是各打各的。只数主行的话，译文会
      永远整行一次性蹦出来，和原文的节奏脱节。
    - `sync=True`（karaoke，v2.9.2）：两行**各按自己的长度**乘同一个进度，也就是
      同一时刻亮起的比例一样 —— 译文跟着主歌词一起扫。
      为什么 karaoke 必须这样：扫光是一种「唱到哪儿」的指示，译文是同一句的另一种
      文字，理应同步推进。走合并总数的话，英文原句长、中文译文短，逐字进度要走完
      全句七成以后才轮到译文，那段时间译文整行都是「未唱」的暗色 —— 用户看到的就是
      「带翻译的歌词不会一起变色」。
    """
    if progress <= 0:
        return 0, 0
    if sync:
        return (min(round(main_len * progress), main_len),
                min(round(sub_len * progress), sub_len))
    total = main_len + sub_len
    typed = round(total * progress)
    main_typed = min(typed, main_len)
    return main_typed, max(0, typed - main_len)


def _typed_from_words(words, text: str, position_ms: int,
                      line_end_ms: int = 0) -> int | None:
    """有逐字时间轴时，按**真实时间窗**求「已经唱到第几个字」（v3.0.0）。

    返回 None 表示「这份逐字数据没法用」，调用方回退 `_typed_split` 的线性插值
    —— 宁可退化成 v2.9.2 的老效果，也不能因为一份坏 sidecar 让高亮乱跳。

    为什么要它而不是「按句进度插值」：句内插值假设字与字匀速，前奏长、拖腔、
    一字一顿的地方全错；逐字时间轴是这些时间的实测值，直接用才是「逐字卡准」。

    判定口径（`typed` 是**字符下标**，不是词元下标）：
    - 落在某个字的时间窗内 → 按窗内比例把该字的字符数折算后四舍五入
      （「故事」是一个词元、窗口走到 60% → typed=1，即只亮出「故」）；
    - 还没到第一个字 → 0；过了最后一个字 → 整行（`len(text)`）。
    """
    n = len(text)
    if not words or n <= 0:
        return None
    # 时间必须单调不减，否则说明 sidecar 被改坏了：直接认输回退
    prev = -1
    for span in words:
        if span.start_ms < prev:
            return None
        prev = span.start_ms
    # 「终点未知」(end<=start) 的兜底时长：取已知窗口的平均值，没有已知值就用 250ms
    known = [s.end_ms - s.start_ms for s in words if s.end_ms > s.start_ms]
    avg = (sum(known) // len(known)) if known else 250
    if avg <= 0:
        avg = 250

    if position_ms <= words[0].start_ms:
        return 0
    typed = 0
    for i, span in enumerate(words):
        start = span.start_ms
        end = span.end_ms
        if end <= start:
            end = (words[i + 1].start_ms if i + 1 < len(words)
                   else max(line_end_ms, start + avg))
        if end <= start:
            end = start + 1
        if position_ms < start:
            return typed
        if position_ms < end:
            frac = (position_ms - start) / (end - start)
            return min(n, typed + int(len(span.text) * frac + 0.5))
        typed += len(span.text)
        if typed >= n:
            return n
    return n


def _uncovered_color() -> QColor:
    """karaoke「未唱到的字」用半透明常态色：比已唱的强调色明显更暗。

    直接沿用 TEXT_DIM 会和强调色同属蓝紫调、对比太弱（深色主题下尤其如此），
    压到 ~35% 不透明度后，未唱部分沉进背景，已唱部分自然浮出来。
    """
    color = _normal_color()
    color.setAlpha(90)
    return color


# v2.9.0 时间模式动画帧间隔（≈30fps）。每帧只重绘当前行，开销可忽略。
_ANIM_INTERVAL = 33


def _brighten(color: QColor, factor: int = 140) -> QColor:
    """派生渐变第二种颜色（提亮版）：用户没配 color_b 时用它。"""
    return QColor(color).lighter(factor)


def _dimmed(color: QColor) -> QColor:
    """颜色覆盖版的「未唱到的字」：同色系压到半透明，沉进背景。

    v2.9.2：alpha 90 → 110。90 时未唱段几乎看不见颜色，只像一团灰；
    抬到 110 后仍明显暗于已唱段，但底色还认得出是用户配的那个色系 ——
    双语歌词里译文行常常整行都处在未唱状态，太暗就会被当成「没变色」。
    """
    c = QColor(color)
    c.setAlpha(110)
    return c


class _LyricDelegate(QStyledItemDelegate):
    """自绘歌词行：背景透明，文字按效果（放大/打字机/颜色覆盖）绘制。"""

    def __init__(self, panel: "LyricsPanel"):
        super().__init__(panel)
        self._panel = panel
        # 字体/度量缓存：原来每帧每行都 new 一遍 QFont + QFontMetrics，是滚动与
        # 逐字动效的主要开销。一次播放里歌词字体基本不变，缓存命中率极高。
        self._font_cache: dict[tuple, tuple[QFont, QFontMetrics]] = {}

    def _font(self, base_font, delta: int, bold: bool = False):
        """按 (字体族, 字号, 字重, 增量, 粗体) 取缓存的 (QFont, QFontMetrics)。"""
        key = (base_font.family(), base_font.pixelSize(), base_font.pointSizeF(),
               base_font.weight(), delta, bold)
        hit = self._font_cache.get(key)
        if hit is None:
            font = _bump_font(base_font, delta)
            if bold:
                font.setBold(True)
            hit = (font, QFontMetrics(font))
            if len(self._font_cache) > 64:      # 拖字号会造很多键，封顶防无限涨
                self._font_cache.clear()
            self._font_cache[key] = hit
        return hit

    def sizeHint(self, option, index):  # noqa: N802
        size = super().sizeHint(option, index)
        # 保证能容纳当前行放大后的字号（zoom 加 6px 是上限）
        _font, metrics = self._font(option.font, _ZOOM_DELTA)
        height = max(size.height(), metrics.height() + 12)
        # 双语：一层原文 + 一层译文，高度要按两层算，否则译文会被裁掉半截
        if index.data(_TRANSLATION_ROLE):
            _sub_font, sub_metrics = self._font(option.font, _ZOOM_DELTA + _SUB_DELTA)
            height = max(height, metrics.height() + sub_metrics.height() + 14)
        size.setHeight(height)
        return size

    def paint(self, painter, option, index):  # noqa: N802
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        sub = index.data(_TRANSLATION_ROLE) or ""
        panel = self._panel
        is_current = panel._mode == "synced" and index.row() == panel._current_index
        self._paint_block(painter, option.rect, text, sub, option.font, is_current,
                          index.row())

    def _paint_block(self, painter, rect, text, sub, base_font, is_current, row):
        """画「一句」：原文一行 +（可选）译文一行，两行作为一个整体垂直居中。"""
        panel = self._panel
        effect = panel._effect if is_current else "none"
        progress = panel._progress_in_line if is_current else 0.0

        # 当前行铺一层很淡的强调色圆角底，让正在唱的这句「浮」起来。
        # alpha 30 很轻，任何主题/自定义背景下都不抢戏。
        if is_current:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            bg = QColor(ACCENT)
            bg.setAlpha(30)
            painter.setBrush(bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect.adjusted(10, 3, -10, -3), 9, 9)
            painter.restore()

        delta = (_ZOOM_DELTA if effect == "zoom" else _NORMAL_DELTA) if is_current else 0
        main_font, main_metrics = self._font(base_font, delta, bold=is_current)
        main_h = main_metrics.height()

        sub_font, sub_metrics = self._font(base_font, delta + _SUB_DELTA)
        sub_h = sub_metrics.height() if sub else 0

        top = rect.y() + (rect.height() - (main_h + sub_h)) / 2.0

        # 逐字进度：typewriter 沿「原文打完再打译文」的连打节奏；karaoke 两行同步
        # 推进（v2.9.2），译文跟着主歌词一起扫。
        #
        # v3.0.0：有逐字时间轴（AI 对齐产物 / 增强 LRC）时改用真实字时间窗求 `typed`，
        # 译文按同一比例推进。没有逐字数据时**逐字符**走原来的 `_typed_split`，
        # 输出与 v2.9.2 完全一致 —— 这是零回归的硬约束。
        main_typed, sub_typed = len(text), len(sub)
        if is_current and effect in ("typewriter", "karaoke"):
            main_typed, sub_typed = _typed_split(len(text), len(sub), progress,
                                                 sync=(effect == "karaoke"))
            words = panel._row_words(row)
            if words:
                start_ms, end_ms = panel._line_bounds(row)
                exact = _typed_from_words(words, text,
                                         int(start_ms + progress * (end_ms - start_ms)),
                                         end_ms)
                if exact is not None:
                    main_typed = exact
                    sub_typed = (round(len(sub) * exact / len(text)) if text and sub else 0)

        # v2.9.0：颜色覆盖只作用于当前句；未启用时 pair=None，完全走原有配色分支。
        # v2.9.1：译文行与原文**同色**（不再压 alpha 205）。原先那层「次级色」在
        # 浅色主题上会把译文洗成一片灰紫，用户观感就是「译文没跟着变色」；
        # 层级改由字号（-3px）承担，颜色保持一致才有「整句一起流动」的效果。
        cfg = panel._active_color_cfg()
        pair = None
        direction = "horizontal"
        transition = 0.08
        phase = 0.0
        if cfg is not None and is_current:
            pair = panel._row_colors(row)
            direction = cfg.direction
            transition = cfg.transition
            phase = panel._color_phase(progress)

        main_sung = QColor(ACCENT) if is_current else _normal_color()
        self._draw_line(painter, rect, text, main_font, main_metrics,
                        top + main_metrics.ascent(), main_typed,
                        main_sung, _uncovered_color(), is_current, effect,
                        pair=pair, direction=direction, transition=transition,
                        phase=phase, band=(top, top + main_h))
        if sub:
            # v2.9.2：译文行**参与**逐字扫光，进度与原文同步（见 `_typed_split`）。
            # 两行各用自己的 band 做渐变轴，颜色/相位/软边完全一致，视觉上就是
            # 「同一句在两种文字上一起扫」。
            self._draw_line(painter, rect, sub, sub_font, sub_metrics,
                            top + main_h + sub_metrics.ascent(), sub_typed,
                            _translation_color(is_current), _translation_color(False),
                            is_current, effect,
                            pair=pair, direction=direction,
                            transition=transition, phase=phase,
                            band=(top + main_h, top + main_h + sub_h))

    def _draw_line(self, painter, rect, text, font, metrics, baseline, typed,
                   sung_color, unsung_color, is_current, effect,
                   pair=None, direction="horizontal", transition=0.08, phase=0.0,
                   band=None):
        """水平居中画一行；当前行的逐字效果按 `typed`（已显示字数）分段上色。

        v2.8.1：超宽时先按行宽省略（右侧 ElideRight），避免被视口硬裁。
        v2.9.0：`pair=(a,b)` 非空时用双色「流动」渐变替代单色（颜色覆盖）；
        `direction` 决定渐变轴、`transition` 决定已唱/未唱交界软宽、`phase` 让色带移动。
        v2.9.1：`band=(top,bottom)` 是**这一行自己**的纵向范围（原文行 / 译文行各一份）。
        原先传整条 item 的 rect，vertical/diagonal 渐变会跨两行取色，译文只能取到
        下半段、退化成单色。
        """
        if not text:
            return
        painter.setFont(font)
        # 留 12px 呼吸：与当前行高亮底的 10px 内缩对齐，字不至于贴着底色边缘
        avail = rect.width() - 12
        if avail > 0 and metrics.horizontalAdvance(text) > avail:
            text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(avail))
        total_w = metrics.horizontalAdvance(text)
        x = int(rect.x() + (rect.width() - total_w) / 2.0)
        y = int(baseline)

        use_grad = pair is not None and is_current
        if band is None:
            band = (float(rect.top()), float(rect.bottom()))

        if not is_current or effect in ("none", "zoom"):
            if use_grad:
                painter.setPen(QPen(QBrush(self._flow(band, x, total_w, pair,
                                                      direction, phase)), 1))
            else:
                painter.setPen(sung_color)
            painter.drawText(x, y, text)
            return

        if effect == "typewriter":
            head = text[:typed]
            if head:
                if use_grad:
                    painter.setPen(QPen(QBrush(self._flow(band, x, total_w, pair,
                                                          direction, phase)), 1))
                else:
                    painter.setPen(sung_color)
                painter.drawText(x, y, head)
            return

        # karaoke：整行一次画出，用一段水平渐变在「已唱 / 未唱」交界处过渡。
        # 颜色覆盖启用时，已唱段用 a→b 双色，未唱段用同色系半透明。
        unsung = _dimmed(pair[0]) if use_grad else unsung_color
        if typed <= 0:
            painter.setPen(unsung)
            painter.drawText(x, y, text)
            return
        if typed >= len(text):
            if use_grad:
                painter.setPen(QPen(QBrush(self._flow(band, x, total_w, pair,
                                                      direction, phase)), 1))
            else:
                painter.setPen(sung_color)
            painter.drawText(x, y, text)
            return
        head_w = metrics.horizontalAdvance(text[:typed])
        span = max(total_w, 1)
        blend = max(1.0, transition * total_w)
        grad = QLinearGradient(float(x), 0.0, float(x + total_w), 0.0)
        grad.setColorAt(0.0, pair[0] if use_grad else sung_color)
        grad.setColorAt(max(0.0, (head_w - blend) / span),
                        pair[1] if use_grad else sung_color)
        grad.setColorAt(min(1.0, (head_w + blend) / span), unsung)
        grad.setColorAt(1.0, unsung)
        painter.setPen(QPen(QBrush(grad), 1))
        painter.drawText(x, y, text)

    @staticmethod
    def _flow(band, x, total_w, pair, direction, phase):
        """双色「流动」线性渐变：两端 = pair[0]，中间一条 pair[1] 色带随 phase 移动。

        v2.9.1：渐变轴改用 `band`（本行自己的上下边界），不再借整条 item 的 rect。
        """
        a, b = pair
        top, bottom = band
        if direction == "vertical":
            start, end = QPointF(x, top), QPointF(x, bottom)
        elif direction == "diagonal":
            start, end = QPointF(x, top), QPointF(x + total_w, bottom)
        else:
            start, end = QPointF(x, 0.0), QPointF(x + total_w, 0.0)
        grad = QLinearGradient(start, end)
        p = min(max(phase, 0.02), 0.98)
        grad.setColorAt(0.0, a)
        grad.setColorAt(p, b)
        grad.setColorAt(1.0, a)
        return grad


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
    # v3.0.0 右键「AI 对齐歌词（逐字）」：本地 whisper 给每个字真实时间轴
    # v3.0.3 改为携带识别语言（auto/zh/en），右键可直接指定，兜底给英文歌用
    align_ai_requested = Signal(str)
    # v3.0.0 右键「清除本曲逐字数据」：对齐结果不满意时退回线性插值
    words_clear_requested = Signal()
    # 右键「整体提前/延后 0.5s」：消掉对齐后的系统性偏移（v2.6.12）
    shift_lyrics_requested = Signal(int)
    # 右键「逐句打轴」：播放中按空格给每一句手动盖时间戳（v2.7.4）
    tap_requested = Signal()
    # v2.9.0 逐句颜色：请求给这一句取色 / 清除这一句 / 清除本曲（由 MainWindow 落地）
    line_color_requested = Signal(int)        # 行下标
    line_color_clear_requested = Signal(int)  # 行下标
    song_colors_clear_requested = Signal()

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
        # v2.7.7：联网匹配的进度文案比原来的空状态提示长得多
        # （"联网匹配 3/3 · LRCLIB、网易云、QQ音乐" 实测 242px，可用宽仅 276px），
        # 而字号最大能放大到 1.30 倍 —— 不开启自动换行就会被直接裁掉。
        self.empty_label.setWordWrap(True)
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
        # v2.9.0 颜色覆盖：配置（None/未启用=旧路径）、逐句色（time_ms->hex）、动画相位
        self._color_cfg = None
        self._line_color_map: dict[int, str] = {}
        self._anim_phase = 0.0
        self._color_timer = QTimer(self)
        self._color_timer.setInterval(_ANIM_INTERVAL)
        self._color_timer.timeout.connect(self._on_color_tick)
        # 打轴模式（v2.7.4）：此时不跟随播放位置滚动，高亮与滚动全由外部驱动
        self._tapping = False
        self.set_empty()

    # ---------- 对外 ----------

    def set_tapping(self, on: bool) -> None:
        """进入/退出打轴模式。

        打轴时**不能**让 `update_position` 带着走：用户在逐句盖时间戳，画面必须停在
        待打的那一句上，否则一按空格高亮就被播放位置抢回去。
        """
        self._tapping = bool(on)

    def highlight_index(self, index: int) -> None:
        """把第 index 句设为当前句并滚到视口中间（打轴推进/回退用）。"""
        if not (0 <= index < self.list.count()):
            return
        self._current_index = index
        self._progress_in_line = 0.0
        self.list.viewport().update()
        self._smooth_scroll_to(self.list.item(index))

    def set_effect(self, effect: str) -> None:
        """切换歌词播放动效；非法值回落到 none。立即重绘。"""
        effect = effect if effect in LYRICS_EFFECTS else "none"
        if effect != self._effect:
            self._effect = effect
            self.list.viewport().update()

    def set_color_config(self, cfg) -> None:
        """下发歌词颜色覆盖配置（v2.9.0）。传 None/未启用 = 回到旧配色。"""
        self._color_cfg = cfg
        self._anim_phase = 0.0
        self._sync_color_timer()
        self.list.viewport().update()

    def set_line_colors(self, mapping) -> None:
        """下发逐句颜色：`{time_ms: '#rrggbb'}`（键与歌词行时间戳对应）。"""
        self._line_color_map = dict(mapping or {})
        self.list.viewport().update()

    def line_time(self, row: int) -> int | None:
        """第 row 句的时间戳（ms）；越界/纯文本返回 None。供主窗口按句存颜色用。"""
        if 0 <= row < len(self._lines):
            return self._lines[row].time_ms
        return None

    def _row_words(self, row: int):
        """第 row 句的逐字时间轴；没有则返回空元组（v3.0.0）。

        空元组 = 该句走线性插值，与 v2.9.2 完全一致。渲染层只认这个开关。
        """
        if 0 <= row < len(self._lines):
            return self._lines[row].words or ()
        return ()

    def _line_bounds(self, row: int) -> tuple[int, int]:
        """第 row 句的起止时间 `(start_ms, end_ms)`。

        末句没有「下一句」可参照，沿用 +3000ms 的兜底（与 `_line_progress` 同口径）。
        逐字求解也用它做「终点未知」的字的时间上限，所以必须与进度算法同源。
        """
        if 0 <= row < len(self._lines):
            start = self._lines[row].time_ms
            end = (self._lines[row + 1].time_ms if row + 1 < len(self._lines)
                   else start + 3000)
            return start, end
        return 0, 0

    def _active_color_cfg(self):
        """返回启用中的颜色配置；None 表示走旧逻辑（这是唯一的开关判断）。"""
        cfg = self._color_cfg
        if cfg is not None and getattr(cfg, "enabled", False):
            return cfg
        return None

    def _row_colors(self, row: int) -> tuple[QColor, QColor]:
        """当前句的 (a, b) 颜色：逐句色 > 全局色 > 主题强调色。"""
        cfg = self._color_cfg
        custom = None
        if 0 <= row < len(self._lines):
            custom = self._line_color_map.get(self._lines[row].time_ms)
        if custom:
            a = QColor(custom)
            b = _brighten(a) if cfg.gradient else QColor(a)
            return a, b
        a = QColor(cfg.color_a) if cfg.color_a else QColor(ACCENT)
        b = QColor(cfg.color_b) if cfg.color_b else _brighten(a)
        if not cfg.gradient:
            b = QColor(a)
        return a, b

    def _color_phase(self, progress: float) -> float:
        """进度模式用行内进度当相位；时间模式用连续动画相位。"""
        cfg = self._color_cfg
        if cfg is not None and cfg.trigger == "time":
            return self._anim_phase
        return max(0.0, min(1.0, progress))

    def _sync_color_timer(self) -> None:
        """时间模式才需要动画定时器；隐藏 / 无同步歌词 / 未启用都停掉。"""
        cfg = self._active_color_cfg()
        need = (cfg is not None and cfg.trigger == "time"
                and self._mode == "synced" and self.isVisible())
        if need and not self._color_timer.isActive():
            self._color_timer.start()
        elif not need and self._color_timer.isActive():
            self._color_timer.stop()

    def _on_color_tick(self) -> None:
        cfg = self._active_color_cfg()
        if cfg is None:
            self._color_timer.stop()
            return
        self._anim_phase = (self._anim_phase
                            + float(cfg.speed) * _ANIM_INTERVAL / 1000.0) % 1.0
        if 0 <= self._current_index < self.list.count():
            self._update_row(self._current_index)   # 只刷当前行，绝不整块重绘

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._sync_color_timer()

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        self._sync_color_timer()

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
                # 段落标记行压暗：它不是唱词（v2.7.3）
                item.setForeground(_marker_color() if is_structure_marker(main)
                                   else _normal_color())
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
        if self._tapping:
            return                      # 打轴模式下位置驱动的高亮会跟用户抢焦点
        if self._mode != "synced" or not self._lines:
            return
        index = lyric_index_at(self._lines, position_ms)
        progress = self._line_progress(index, position_ms)
        if index == self._current_index:
            # 行不变：只有逐字效果 / 进度驱动的颜色扫光需要按进度重绘，只刷当前行
            needs_progress = (
                self._effect in ("typewriter", "karaoke")
                or (self._active_color_cfg() is not None
                    and self._color_cfg.trigger == "progress")
            )
            if needs_progress and abs(progress - self._progress_in_line) > 0.01:
                self._progress_in_line = progress
                self._update_row(index)
            return
        self._current_index = index
        self._progress_in_line = progress
        if 0 <= index < self.list.count():
            self._smooth_scroll_to(self.list.item(index))
        self.list.viewport().update()

    def _update_row(self, index: int) -> None:
        """只重绘第 index 行（行内进度更新时用，避免整块 viewport 全量重绘）。"""
        if not (0 <= index < self.list.count()):
            self.list.viewport().update()
            return
        rect = self.list.visualItemRect(self.list.item(index))
        if rect.isValid():
            self.list.viewport().update(rect)
        else:
            self.list.viewport().update()

    # ---------- 内部 ----------

    def _line_progress(self, index: int, position_ms: int) -> float:
        """当前行内的播放进度 0~1（打字机/颜色覆盖按它推进）。"""
        if index < 0 or index >= len(self._lines):
            return 0.0
        start, end = self._line_bounds(index)
        span = end - start
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (position_ms - start) / span))

    def _refresh_visibility(self) -> None:
        has = self._mode != "empty"
        self.list.setVisible(has)
        self.empty_label.setVisible(not has)
        self._sync_color_timer()

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

    def _build_menu(self, row: int = -1) -> QMenu:
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
        # 右键「转成 .lrc 文件（本地近似对齐）」：离线把纯文本歌词配成带时间轴 LRC。
        # 纯信号处理估算（可能整体差几秒），配合下面的「整体提前/延后」微调。
        align_local = QAction("转成 .lrc 文件（本地近似对齐）", menu)
        align_local.setStatusTip("离线分析音频节奏，大致跟唱；可能整体差几秒")
        align_local.triggered.connect(self.align_local_requested.emit)
        menu.addAction(align_local)
        # v3.0.0 右键「AI 对齐歌词（逐字）」：本地 whisper 识别演唱，把每个字钉到真实时刻。
        # 与上面那条并列、但精度不同：近似对齐只到「行」（误差可达几秒），
        # AI 对齐到「字」（误差约 ±80ms）。文案必须把这个差别说出来，否则用户不知道选哪个。
        # v3.0.3：改成子菜单，让用户能按首指定识别语言（英文歌自动猜错时手动兜底）。
        align_ai_menu = QMenu("AI 对齐歌词（逐字）", menu)
        align_ai_menu.setEnabled(self._mode == "synced")
        ai_auto = QAction("自动识别语言", align_ai_menu)
        ai_auto.setStatusTip("按歌词汉字占比自动判断（推荐）")
        ai_auto.triggered.connect(lambda: self.align_ai_requested.emit("auto"))
        align_ai_menu.addAction(ai_auto)
        ai_zh = QAction("按中文识别", align_ai_menu)
        ai_zh.triggered.connect(lambda: self.align_ai_requested.emit("zh"))
        align_ai_menu.addAction(ai_zh)
        ai_en = QAction("按英文识别", align_ai_menu)
        ai_en.triggered.connect(lambda: self.align_ai_requested.emit("en"))
        align_ai_menu.addAction(ai_en)
        menu.addMenu(align_ai_menu)
        words_clear = QAction("清除本曲逐字数据", menu)
        words_clear.setStatusTip("退回按行匀速扫光（对齐结果不满意时用）")
        words_clear.triggered.connect(self.words_clear_requested.emit)
        words_clear.setEnabled(self._mode == "synced")
        menu.addAction(words_clear)
        # 右键「逐句打轴」：跟唱打拍子，每一句都卡在你按下的那一刻（v2.7.4）。
        # 这是唯一能让时间「完全准确」的路子——本地对齐只是近似（误差天花板 ~6s）。
        tap = QAction("逐句打轴（手动卡时间）", menu)
        tap.setStatusTip("播放中按空格逐句盖时间戳，Backspace 回退，Esc 结束")
        tap.triggered.connect(self.tap_requested.emit)
        tap.setEnabled(self._mode in ("plain", "synced"))
        menu.addAction(tap)
        # v2.9.0 逐句颜色：只对同步歌词的具体某一句生效
        color_one = QAction("这一句设置颜色…", menu)
        color_one.triggered.connect(lambda: self.line_color_requested.emit(row))
        menu.addAction(color_one)
        color_clear = QAction("清除这一句颜色", menu)
        color_clear.triggered.connect(lambda: self.line_color_clear_requested.emit(row))
        menu.addAction(color_clear)
        color_song = QAction("清除本曲歌词颜色", menu)
        color_song.triggered.connect(self.song_colors_clear_requested.emit)
        menu.addAction(color_song)
        for action in (color_one, color_clear):
            action.setEnabled(self._mode == "synced" and row >= 0)
        color_song.setEnabled(self._mode == "synced")
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
        sender = self.sender()
        row = -1
        if sender is self.list:
            item = self.list.itemAt(pos)
            if item is not None:
                row = self.list.row(item)
        menu = self._build_menu(row)
        anchor = sender.mapToGlobal(pos) if isinstance(sender, QWidget) else pos
        menu.exec(anchor)
