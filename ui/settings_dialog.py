# -*- coding: utf-8 -*-
"""设置对话框：外观（纯色主题/强调色/字号）、背景（装饰主题/底图）、歌词与统计。

v2.2 的三条设计取舍：
1. **一个色值**（强调色）：hover/dim/soft/on_accent 由 theme 派生，不让用户手调四档
   —— 既难用，也很容易配出自相矛盾的组合。
2. **一档字号**（四档下拉）：范围夹在 0.85~1.30，因为行高 52、播放栏 84 是固定值，
   再大文字会被裁掉。
3. **背景按作用域存**：全部页面 / 列表页 / 正在播放页各存一份，本页没单独设过就
   跟随「全部页面」。切页时主窗口重新取一次配置即可，渲染层完全不用关心是哪个页面。
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import paths as app_paths
from app.library import import_background
from app.models import (DEFAULT_AI_LANGUAGE, DEFAULT_AI_MODEL, DEFAULT_AI_QUALITY,
                        LYRICS_AI_LANGUAGE_LABELS, LYRICS_AI_LANGUAGES,
                        LYRICS_AI_MODEL_LABELS, LYRICS_AI_MODELS,
                        LYRICS_AI_QUALITY_LABELS, LYRICS_AI_QUALITIES,
                        BackgroundConfig, LYRICS_EFFECTS, LyricsColorConfig)
from app.paths import bgs_dir
from app.version import APP_NAME, version_text
from ui import theme as ui_theme
from ui.dialogs import StorageMoveDialog
from ui.live_bg import LIVE_BY_KEY, LIVE_KEYS, LIVE_STYLES
from ui.widgets import ChevronComboBox

# 预设强调色：覆盖"冷暖各一支"，避免用户以为只能蓝
ACCENT_PRESETS = [
    ("蓝紫", "#6c8cff"),
    ("天蓝", "#3b82f6"),
    ("青", "#0ea5e9"),
    ("绿", "#22c55e"),
    ("橙", "#ff7a45"),
    ("玫红", "#e11d48"),
]

FONT_SCALE_OPTIONS = [
    ("较小", 0.90),
    ("标准", 1.00),
    ("较大", 1.15),
    ("特大", 1.28),
]

# 歌词播放动效（v2.6.4，单选）：与 app/models.py 的 LYRICS_EFFECTS 一一对应。
#
# v3.0.9 命名体系重排。旧命名有四个问题：
#   1. 「无特效」其实是「关闭」，与另外几个效果不在同一层级；
#   2. 「打字机」是比喻，不说明效果；
#   3. 两条逐字效果（typewriter / karaoke）的**唯一差别**是「未唱的字显示不显示」，
#      旧名里完全没写，用户只能靠试；
#   4. **重名**：「karaoke」旧名「颜色覆盖」，与下方 v2.9.0 的「歌词颜色覆盖」分区
#      重名 —— 前者是动效、后者是配色配置，用户以为是同一件事。
# 现在统一成「动什么 + 怎么动」，并把两条逐字效果的差别直接写进名字。
#
# v3.2.1 移除「放大当前行」：**当前行始终自动放大**，不再是一个选项。放大是歌词最
# 基本的可读性要求，让它躺在下拉里等人挑，等于把默认体验做成了次优。
LYRICS_EFFECT_OPTIONS = [
    ("无动效（仅高亮）", "none"),
    ("逐字显示（未唱不显示）", "typewriter"),
    ("逐字上色（未唱淡显）", "karaoke"),
]


def effect_label(value: str) -> str:
    """动效值 → 界面文案。

    v3.0.9：文案**只在这里定义一次**。此前下拉项在 `settings_dialog`、
    toast 提示在 `main_window` 各写一份，改名漏一处就会「设置页叫 A、提示说 B」。
    """
    for label, val in LYRICS_EFFECT_OPTIONS:
        if val == value:
            return label
    return value

# 歌词颜色覆盖（v2.9.0）
COLOR_TRIGGER_OPTIONS = [
    ("按歌词进度", "progress"),
    ("按播放时间", "time"),
]

COLOR_DIRECTION_OPTIONS = [
    ("横向", "horizontal"),
    ("纵向", "vertical"),
    ("斜向", "diagonal"),
]

BG_TYPE_OPTIONS = [
    ("无背景（跟随主题）", "none"),
    ("纯色", "color"),
    ("渐变", "gradient"),
    ("图片", "image"),
    ("动态背景", "live"),
]

BG_SCOPE_OPTIONS = [
    ("全部页面", "all"),
    ("列表页", "library"),
    ("正在播放页", "now_playing"),
]


class _Swatch(QWidget):
    """圆形色块：选中时画一圈外环。用自绘而不是 QSS —— 全局 QSS 里的
    QPushButton 内边距/圆角规则会和这里打架，自绘最省心。"""

    clicked = Signal(str)
    _SIZE = 22
    _RING = 4

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self.color = color
        self._color = QColor(color)
        self._selected = False
        edge = self._SIZE + self._RING * 2
        self.setFixedSize(edge, edge)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.color)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(self._RING, self._RING, -self._RING, -self._RING)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(rect)
        if self._selected:
            pen = QPen(QColor(self._color))
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(self.rect().adjusted(1, 1, -1, -1))


class SettingsDialog(QDialog):
    theme_changed = Signal(str)          # columbina / light
    nickname_changed = Signal(str)
    online_lyrics_changed = Signal(bool)
    accent_changed = Signal(str)         # "#rrggbb"，"" = 跟随主题默认
    font_scale_changed = Signal(float)
    lyrics_effect_changed = Signal(str)  # none / typewriter / karaoke
    lyrics_color_changed = Signal(object)  # v2.9.0：LyricsColorConfig
    ai_model_changed = Signal(str)       # v3.0.0：AI 逐字对齐的模型档位
    ai_language_changed = Signal(str)    # v3.0.3：AI 识别语言（auto/zh/en）
    ai_quality_changed = Signal(str)     # v3.0.3：AI 识别质量（fast/balanced/quality）
    ai_batch_requested = Signal()        # v3.0.0：打开全库批量对齐对话框
    words_clear_requested = Signal()     # v3.0.0：清空全部字级数据
    background_changed = Signal(str, object)   # (作用域, BackgroundConfig)
    storage_changed = Signal(str)        # 数据目录搬到的新位置（需重启生效）

    def __init__(self, theme_name: str, nickname: str, stats: dict, parent=None,
                 online_lyrics: bool = True, accent_color: str = "",
                 font_scale: float = 1.0, bg_configs: dict | None = None,
                 bg_scope: str = "all", lyrics_effect: str = "none",
                 lyrics_color: LyricsColorConfig | None = None,
                 ai_model: str = DEFAULT_AI_MODEL,
                 ai_language: str = DEFAULT_AI_LANGUAGE,
                 ai_quality: str = DEFAULT_AI_QUALITY):
        super().__init__(parent)
        self.setObjectName("SettingsDialog")
        self.setWindowTitle("设置")
        self.setMinimumWidth(430)
        self._theme_name = theme_name if theme_name in ui_theme.THEMES else ui_theme.DEFAULT_THEME
        self._accent = (accent_color or "").lower()
        self._font_scale = font_scale
        self._lyrics_effect = lyrics_effect if lyrics_effect in LYRICS_EFFECTS else "none"
        self._lyrics_color = LyricsColorConfig.from_dict(
            lyrics_color.to_dict() if isinstance(lyrics_color, LyricsColorConfig) else {})
        self._ai_model = ai_model if ai_model in LYRICS_AI_MODELS else DEFAULT_AI_MODEL
        self._ai_language = (ai_language if ai_language in LYRICS_AI_LANGUAGES
                             else DEFAULT_AI_LANGUAGE)
        self._ai_quality = (ai_quality if ai_quality in LYRICS_AI_QUALITIES
                            else DEFAULT_AI_QUALITY)
        self._loading = False
        self._bg_scope = bg_scope if bg_scope in ("all", "library", "now_playing") else "all"
        self._bg: dict[str, BackgroundConfig] = {}
        for scope in ("all", "library", "now_playing"):
            source = (bg_configs or {}).get(scope)
            self._bg[scope] = (BackgroundConfig.from_dict(source.to_dict())
                               if isinstance(source, BackgroundConfig) else BackgroundConfig())

        # v3.1.1：四套配色的单选**一次性建好**，再分别摆进「外观 / 背景」两页。
        # 为什么不各页自己建：
        # 1) QRadioButton 的互斥是按 parent 分组的 —— 分在两页会各亮一个（两套配色
        #    同时显示为选中），必须靠 QButtonGroup 跨页统一互斥；
        # 2) 「归哪页」只是摆放位置，状态只有一个，建好再分发不会出现两处不同步。
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_radios: dict[str, QRadioButton] = {}
        for _group_name, _ids in ui_theme.THEME_GROUPS:
            for _tid in _ids:
                radio = QRadioButton(ui_theme.theme_caption(_tid))
                _solid = _tid in ui_theme.THEME_SOLID
                radio.setToolTip(
                    f"{ui_theme.THEME_TONE[_tid]}配色"
                    + ("，不含装饰底纹" if _solid else "，带装饰底纹")
                    + "；可与任意背景图案自由搭配（图案在「背景」页选）")
                radio.setChecked(_tid == self._theme_name)
                radio.toggled.connect(
                    lambda checked, t=_tid: checked and self._on_theme(t))
                self.theme_group.addButton(radio)
                self.theme_radios[_tid] = radio
        self.light_radio = self.theme_radios["light"]   # 兼容旧引用

        root = QVBoxLayout(self)
        root.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("SettingsTabs")
        self.appearance_page = self._build_appearance_tab(nickname)
        self.tabs.addTab(self.appearance_page, "外观")
        self.background_page = self._build_background_tab()
        self.tabs.addTab(self.background_page, "背景")
        self.tabs.addTab(self._build_misc_tab(stats, online_lyrics), "歌词与统计")
        self.tabs.addTab(self._build_storage_tab(), "存储")
        root.addWidget(self.tabs, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("Primary")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

        self._load_background_scope(self._bg_scope)

    # ---------- 页 1：外观 ----------

    def _build_appearance_tab(self, nickname: str) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(8)
        self.nickname_edit = QLineEdit(nickname)
        self.nickname_edit.textChanged.connect(self.nickname_changed.emit)
        form.addRow("昵称", self.nickname_edit)
        root.addLayout(form)

        # v3.1.1：纯色主题（曜石 / 珍珠）放「外观」页 —— 它们只是把整套配色换成
        # 一条纯黑/纯白，不涉及任何底纹，和强调色、字号属于同一类"看起来怎样"的设置。
        # 带装饰底纹的星夜/月白仍在「背景」页，跟背景图案放一起调。
        # 注意：换个摆放位置**不等于**主题与背景合并，两者仍然正交（任何主题配任何背景）。
        root.addWidget(QLabel("纯色主题"))
        self._add_theme_rows(root, ui_theme.THEME_SOLID)
        root.addSpacing(4)

        accent_row = QHBoxLayout()
        accent_row.setSpacing(6)
        accent_row.addWidget(QLabel("强调色"))
        self.swatches: list[_Swatch] = []
        for name, color in ACCENT_PRESETS:
            swatch = _Swatch(color, self)
            swatch.setToolTip(name)
            swatch.clicked.connect(self._set_accent)
            self.swatches.append(swatch)
            accent_row.addWidget(swatch)
        accent_row.addSpacing(6)
        self.custom_btn = QPushButton("自定义…")
        self.custom_btn.setObjectName("Ghost")
        self.custom_btn.clicked.connect(self._pick_custom_accent)
        accent_row.addWidget(self.custom_btn)
        self.reset_accent_btn = QPushButton("随主题")
        self.reset_accent_btn.setObjectName("Ghost")
        self.reset_accent_btn.setToolTip("清除自定义强调色，回到当前主题的默认色")
        self.reset_accent_btn.clicked.connect(lambda: self._set_accent(""))
        accent_row.addWidget(self.reset_accent_btn)
        accent_row.addStretch(1)
        root.addLayout(accent_row)

        font_row = QHBoxLayout()
        font_row.setSpacing(10)
        font_row.addWidget(QLabel("字号"))
        self.font_combo = ChevronComboBox()
        self.font_combo.setObjectName("FontScaleCombo")
        for label, value in FONT_SCALE_OPTIONS:
            self.font_combo.addItem(label, value)
        self._select_font_scale(self._font_scale)
        self.font_combo.currentIndexChanged.connect(self._on_font_combo)
        font_row.addWidget(self.font_combo)
        font_row.addStretch(1)
        root.addLayout(font_row)

        hint = QLabel("外观改动立即生效，可以一边看一边调。"
                      "纯色主题不含底纹，想要星空 / 云海底纹请到「背景」页。")
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addStretch(1)

        self._sync_swatches()
        return page

    def _add_theme_rows(self, root: QVBoxLayout, bucket: tuple[str, ...]) -> None:
        """把属于某一页的主题单选摆出来，仍按「深色系 / 浅色系」标明明暗。

        bucket 取 `ui_theme.THEME_SOLID`（外观页）或 `THEME_PATTERNED`（背景页）。
        分组标签保留，因为它承载的是"这一套是深还是浅"的信息 —— 分页只是摆放位置，
        与明暗归类无关。
        """
        for group_name, ids in ui_theme.THEME_GROUPS:
            picked = [tid for tid in ids if tid in bucket]
            if not picked:
                continue
            group_row = QHBoxLayout()
            group_row.setSpacing(14)
            group_label = QLabel(group_name)
            group_label.setObjectName("Dim")
            group_label.setFixedWidth(46)   # 两组对齐，别让「深色系/浅色系」抖
            group_row.addWidget(group_label)
            for tid in picked:
                group_row.addWidget(self.theme_radios[tid])
            group_row.addStretch(1)
            root.addLayout(group_row)

    # ---------- 页 2：背景 ----------

    def _build_background_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setSpacing(10)

        # v3.1.1：这一页只剩带装饰底纹的两套（星夜 / 月白）；纯色的曜石 / 珍珠
        # 已移到「外观」页。两块**互不联动**：主题换的是配色，图案换的是底图，
        # 可以任意搭配。
        root.addWidget(QLabel("配色主题"))
        self._add_theme_rows(root, ui_theme.THEME_PATTERNED)

        root.addSpacing(8)

        # v2.8.3：内置背景图案（星空 / 云海）—— 主题与背景已拆开，这两张图不是
        # 「主题2」，而是这里可选的两张卡片，任何主题都能配（v3.1.0 改名「背景图案」，
        # 与上面的「配色主题」明确区分）。
        root.addWidget(QLabel("背景图案"))
        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        self.preset_buttons: dict[str, QPushButton] = {}
        for preset in ui_theme.BACKGROUND_PRESETS:
            btn = QPushButton(preset.label)
            btn.setObjectName("Ghost")
            btn.setToolTip(f"应用内置背景「{preset.label}」")
            thumb = QPixmap(ui_theme.preset_image_path(preset.id) or "")
            if not thumb.isNull():
                thumb = thumb.scaled(96, 54,
                                     Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
                btn.setIcon(QIcon(thumb))
                btn.setIconSize(thumb.size())
            btn.clicked.connect(lambda _=False, pid=preset.id: self._apply_preset(pid))
            preset_row.addWidget(btn)
            self.preset_buttons[preset.id] = btn
        preset_row.addStretch(1)
        root.addLayout(preset_row)

        # v3.3.0：动态背景（实时动画，亮度随歌曲能量起伏）。
        # 与上面的静态图案**互斥**：两者写的是同一份 BackgroundConfig 的
        # type/preset，选一个就顶掉另一个 —— 背景只能有一层，叠加会互相打架。
        root.addSpacing(8)
        root.addWidget(QLabel("动态背景（跟随音乐）"))
        live_row = QHBoxLayout()
        live_row.setSpacing(8)
        self.live_buttons: dict[str, QPushButton] = {}
        for style_key, style_label in LIVE_STYLES:
            live_btn = QPushButton(style_label)
            live_btn.setObjectName("Ghost")
            live_btn.setToolTip(f"实时动画背景「{style_label}」，亮度随歌曲音量起伏")
            live_btn.clicked.connect(
                lambda _=False, k=style_key: self._apply_live(k))
            live_row.addWidget(live_btn)
            self.live_buttons[style_key] = live_btn
        live_row.addStretch(1)
        root.addLayout(live_row)

        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(QLabel("类型"))
        self.bg_type_combo = ChevronComboBox()
        self.bg_type_combo.setObjectName("FontScaleCombo")
        for label, value in BG_TYPE_OPTIONS:
            self.bg_type_combo.addItem(label, value)
        self.bg_type_combo.currentIndexChanged.connect(self._on_bg_type_changed)
        top.addWidget(self.bg_type_combo)
        top.addSpacing(8)
        top.addWidget(QLabel("作用页面"))
        self.bg_scope_combo = ChevronComboBox()
        self.bg_scope_combo.setObjectName("FontScaleCombo")
        for label, value in BG_SCOPE_OPTIONS:
            self.bg_scope_combo.addItem(label, value)
        self.bg_scope_combo.currentIndexChanged.connect(self._on_bg_scope_changed)
        top.addWidget(self.bg_scope_combo)
        top.addStretch(1)
        root.addLayout(top)

        self.bg_inherit_box = QCheckBox("本页单独设置（不勾则跟随「全部页面」）")
        self.bg_inherit_box.toggled.connect(self._on_bg_inherit_toggled)
        root.addWidget(self.bg_inherit_box)

        # ---- 颜色 ----
        self.color_row = QWidget()
        color_lay = QHBoxLayout(self.color_row)
        color_lay.setContentsMargins(0, 0, 0, 0)
        color_lay.setSpacing(10)
        self.color_label = QLabel("颜色")
        color_lay.addWidget(self.color_label)
        self.color_btn = QPushButton()
        self.color_btn.setFixedWidth(96)
        self.color_btn.clicked.connect(lambda: self._pick_bg_color("color"))
        color_lay.addWidget(self.color_btn)
        self.color2_label = QLabel("渐至")
        color_lay.addWidget(self.color2_label)
        self.color2_btn = QPushButton()
        self.color2_btn.setFixedWidth(96)
        self.color2_btn.clicked.connect(lambda: self._pick_bg_color("color2"))
        color_lay.addWidget(self.color2_btn)
        color_lay.addStretch(1)
        root.addWidget(self.color_row)

        # ---- 图片 ----
        self.image_row = QWidget()
        image_lay = QHBoxLayout(self.image_row)
        image_lay.setContentsMargins(0, 0, 0, 0)
        image_lay.setSpacing(8)
        self.pick_image_btn = QPushButton("选择图片…")
        self.pick_image_btn.setObjectName("Ghost")
        self.pick_image_btn.clicked.connect(self._pick_bg_image)
        image_lay.addWidget(self.pick_image_btn)
        self.image_label = QLabel("未选择")
        self.image_label.setObjectName("Dim")
        image_lay.addWidget(self.image_label, 1)
        self.clear_image_btn = QPushButton("清除")
        self.clear_image_btn.setObjectName("Ghost")
        self.clear_image_btn.clicked.connect(self._clear_bg_image)
        image_lay.addWidget(self.clear_image_btn)
        root.addWidget(self.image_row)

        # ---- 三个调节 ----
        self.opacity_slider, self.opacity_value = self._add_slider_row(
            root, "不透明度", 20, 100, 100, "%")
        self.blur_slider, self.blur_value = self._add_slider_row(
            root, "模糊", 0, 40, 0, "")
        self.dim_slider, self.dim_value = self._add_slider_row(
            root, "暗化", 0, 70, 0, "%")
        for slider in (self.opacity_slider, self.blur_slider, self.dim_slider):
            slider.valueChanged.connect(self._on_bg_slider_changed)

        self.bg_hint = QLabel("背景越亮，越建议加一点「暗化」，否则文字会看不清。")
        self.bg_hint.setObjectName("Dim")
        self.bg_hint.setWordWrap(True)
        root.addWidget(self.bg_hint)
        root.addStretch(1)
        return page

    def _add_slider_row(self, layout, label, minimum, maximum, value, suffix):
        row = QHBoxLayout()
        row.setSpacing(10)
        name = QLabel(label)
        name.setFixedWidth(56)
        row.addWidget(name)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setObjectName("SettingSlider")
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.setFixedWidth(160)
        slider.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(slider)
        value_label = QLabel(f"{value}{suffix}")
        value_label.setObjectName("Dim")
        value_label.setFixedWidth(44)
        row.addWidget(value_label)
        row.addStretch(1)
        layout.addLayout(row)
        return slider, value_label

    # ---------- 页 3：歌词与统计 ----------

    def _build_misc_tab(self, stats: dict, online_lyrics: bool) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setSpacing(10)

        self.online_lyrics_box = QCheckBox("本地没有歌词时联网匹配（LRCLIB）")
        self.online_lyrics_box.setChecked(bool(online_lyrics))
        self.online_lyrics_box.toggled.connect(self.online_lyrics_changed.emit)
        root.addWidget(self.online_lyrics_box)
        hint = QLabel("匹配结果会缓存到本地，之后不联网也能看。")
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        root.addWidget(hint)

        effect_row = QHBoxLayout()
        effect_row.setSpacing(10)
        effect_row.addWidget(QLabel("歌词动效"))
        self.effect_combo = ChevronComboBox()
        self.effect_combo.setObjectName("FontScaleCombo")
        for label, value in LYRICS_EFFECT_OPTIONS:
            self.effect_combo.addItem(label, value)
        effect_index = self.effect_combo.findData(self._lyrics_effect)
        self.effect_combo.setCurrentIndex(max(0, effect_index))
        self.effect_combo.currentIndexChanged.connect(self._on_effect_combo)
        effect_row.addWidget(self.effect_combo)
        effect_row.addStretch(1)
        root.addLayout(effect_row)
        # 名字已经自带说明了效果，这里不再重复罗列；改为说清三件名字答不了的事：
        # 作用范围（只当前句）、**当前行始终放大**（v3.2.1 起不是选项），
        # 以及它和下方「歌词颜色覆盖」的关系（正交，可同时开）。
        effect_hint = QLabel(
            "只作用于正在播放页的当前这一句；当前播放的这句始终会自动放大，"
            "无需额外设置。与下方「歌词颜色覆盖」的配色互不影响，可以同时开启。")
        effect_hint.setObjectName("Dim")
        effect_hint.setWordWrap(True)
        root.addWidget(effect_hint)

        # ---- AI 逐字对齐（v3.0.0）----
        #
        # 放在这里而不是单独开一页：它和「歌词动效」「颜色覆盖」是同一件事的三个侧面
        # （字怎么动 / 字什么颜色 / 字在什么时候亮），分散到两页反而找不到。
        root.addSpacing(8)
        root.addWidget(QLabel("AI 逐字对齐"))
        ai_row = QHBoxLayout()
        ai_row.setSpacing(10)
        ai_row.addWidget(QLabel("模型档位"))
        self.ai_model_combo = ChevronComboBox()
        self.ai_model_combo.setObjectName("FontScaleCombo")
        for name in LYRICS_AI_MODELS:
            self.ai_model_combo.addItem(LYRICS_AI_MODEL_LABELS.get(name, name), name)
        self.ai_model_combo.setCurrentIndex(
            max(0, self.ai_model_combo.findData(self._ai_model)))
        self.ai_model_combo.currentIndexChanged.connect(self._on_ai_model_combo)
        ai_row.addWidget(self.ai_model_combo)
        ai_row.addStretch(1)
        root.addLayout(ai_row)

        # v3.0.3：识别语言（英文歌之前会被识别成中文乱码）与识别质量（beam 大小）。
        lang_row = QHBoxLayout()
        lang_row.setSpacing(10)
        lang_row.addWidget(QLabel("识别语言"))
        self.ai_language_combo = ChevronComboBox()
        self.ai_language_combo.setObjectName("FontScaleCombo")
        for name in LYRICS_AI_LANGUAGES:
            self.ai_language_combo.addItem(LYRICS_AI_LANGUAGE_LABELS.get(name, name), name)
        self.ai_language_combo.setCurrentIndex(
            max(0, self.ai_language_combo.findData(self._ai_language)))
        self.ai_language_combo.currentIndexChanged.connect(self._on_ai_language_combo)
        lang_row.addWidget(self.ai_language_combo)

        lang_row.addWidget(QLabel("识别质量"))
        self.ai_quality_combo = ChevronComboBox()
        self.ai_quality_combo.setObjectName("FontScaleCombo")
        for name in LYRICS_AI_QUALITIES:
            self.ai_quality_combo.addItem(LYRICS_AI_QUALITY_LABELS.get(name, name), name)
        self.ai_quality_combo.setCurrentIndex(
            max(0, self.ai_quality_combo.findData(self._ai_quality)))
        self.ai_quality_combo.currentIndexChanged.connect(self._on_ai_quality_combo)
        lang_row.addWidget(self.ai_quality_combo)
        lang_row.addStretch(1)
        root.addLayout(lang_row)

        ai_hint = QLabel("本地识别演唱、把每个字钉到真实时刻（误差约 ±80ms）。"
                         "首次使用需下载模型，之后完全离线；换档位需重新下载。"
                         "质量越高越准但越慢。")
        ai_hint.setObjectName("Dim")
        ai_hint.setWordWrap(True)
        root.addWidget(ai_hint)

        ai_buttons = QHBoxLayout()
        ai_buttons.setSpacing(8)
        batch_btn = QPushButton("全库批量对齐…")
        batch_btn.setToolTip("逐首跑 AI 对齐，可随时中断；失败的会列出来，不影响其他歌")
        batch_btn.clicked.connect(self.ai_batch_requested.emit)
        ai_buttons.addWidget(batch_btn)
        clear_btn = QPushButton("清空字级数据")
        clear_btn.setToolTip("删掉所有歌的逐字时间轴，退回按行匀速扫光")
        clear_btn.clicked.connect(self._on_clear_words)
        ai_buttons.addWidget(clear_btn)
        ai_buttons.addStretch(1)
        root.addLayout(ai_buttons)

        # ---- 歌词颜色覆盖（v2.9.0）：只作用于正在播放页的当前这一句 ----
        root.addSpacing(8)
        root.addWidget(QLabel("歌词颜色覆盖"))
        self.color_enabled_box = QCheckBox("启用（只作用于正在播放页当前这句）")
        self.color_enabled_box.setChecked(self._lyrics_color.enabled)
        self.color_enabled_box.toggled.connect(self._on_color_enabled)
        root.addWidget(self.color_enabled_box)

        color_top = QHBoxLayout()
        color_top.setSpacing(8)
        color_top.addWidget(QLabel("触发"))
        self.color_trigger_combo = ChevronComboBox()
        self.color_trigger_combo.setObjectName("FontScaleCombo")
        for label, value in COLOR_TRIGGER_OPTIONS:
            self.color_trigger_combo.addItem(label, value)
        self.color_trigger_combo.setCurrentIndex(
            max(0, self.color_trigger_combo.findData(self._lyrics_color.trigger)))
        self.color_trigger_combo.currentIndexChanged.connect(self._on_color_trigger)
        color_top.addWidget(self.color_trigger_combo)
        color_top.addSpacing(8)
        color_top.addWidget(QLabel("方向"))
        self.color_direction_combo = ChevronComboBox()
        self.color_direction_combo.setObjectName("FontScaleCombo")
        for label, value in COLOR_DIRECTION_OPTIONS:
            self.color_direction_combo.addItem(label, value)
        self.color_direction_combo.setCurrentIndex(
            max(0, self.color_direction_combo.findData(self._lyrics_color.direction)))
        self.color_direction_combo.currentIndexChanged.connect(self._on_color_direction)
        color_top.addWidget(self.color_direction_combo)
        color_top.addStretch(1)
        root.addLayout(color_top)

        color_pick = QHBoxLayout()
        color_pick.setSpacing(8)
        color_pick.addWidget(QLabel("起色"))
        self.color_a_btn = QPushButton()
        self.color_a_btn.setFixedWidth(96)
        self.color_a_btn.clicked.connect(lambda: self._pick_lyric_color("color_a"))
        color_pick.addWidget(self.color_a_btn)
        color_pick.addWidget(QLabel("止色"))
        self.color_b_btn = QPushButton()
        self.color_b_btn.setFixedWidth(96)
        self.color_b_btn.clicked.connect(lambda: self._pick_lyric_color("color_b"))
        color_pick.addWidget(self.color_b_btn)
        self.color_reset_btn = QPushButton("随主题")
        self.color_reset_btn.setObjectName("Ghost")
        self.color_reset_btn.setToolTip("清除起色/止色，跟随当前主题强调色")
        self.color_reset_btn.clicked.connect(self._reset_lyric_colors)
        color_pick.addWidget(self.color_reset_btn)
        color_pick.addStretch(1)
        root.addLayout(color_pick)

        self.color_speed_slider, self.color_speed_value = self._add_slider_row(
            root, "速度", 5, 200, round(self._lyrics_color.speed * 100), "%")
        self.color_speed_slider.valueChanged.connect(self._on_color_speed)
        self.color_transition_slider, self.color_transition_value = self._add_slider_row(
            root, "过渡", 0, 30, round(self._lyrics_color.transition * 100), "%")
        self.color_transition_slider.valueChanged.connect(self._on_color_transition)

        color_hint = QLabel("留空起色/止色即跟随主题；「按播放时间」时用速度控制流动快慢。")
        color_hint.setObjectName("Dim")
        color_hint.setWordWrap(True)
        root.addWidget(color_hint)
        self._sync_color_widgets()

        root.addSpacing(6)
        stats_text = (
            f"曲目 {stats.get('tracks', 0)} 首 · 歌单 {stats.get('playlists', 0)} 个 · "
            f"喜欢 {stats.get('favorites', 0)} 首\n"
            f"总时长 {stats.get('total_duration', '0 分钟')}"
        )
        stats_label = QLabel(stats_text)
        stats_label.setObjectName("Dim")
        stats_label.setWordWrap(True)
        root.addWidget(stats_label)

        # v2.7.6：原来写死 "轻音播放器 v2.2 · ..."，早就对不上了
        about = QLabel(f"{APP_NAME} {version_text()}，歌词可联网补全")
        about.setObjectName("Dim")
        root.addWidget(about)
        root.addStretch(1)
        return page

    # ---------- 页 4：存储 ----------

    def _build_storage_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setSpacing(10)

        root.addWidget(QLabel("数据存放位置"))

        self.storage_path_edit = QLineEdit(app_paths.current_root())
        self.storage_path_edit.setReadOnly(True)
        self.storage_path_edit.setCursorPosition(0)
        self.storage_path_edit.setToolTip("曲库、封面、歌词缓存、背景和设置都在这个目录里")
        root.addWidget(self.storage_path_edit)

        self.storage_mode_label = QLabel()
        self.storage_mode_label.setObjectName("Dim")
        self.storage_mode_label.setWordWrap(True)
        root.addWidget(self.storage_mode_label)
        self._refresh_storage_info()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.open_storage_btn = QPushButton("打开目录")
        self.open_storage_btn.setObjectName("Ghost")
        self.open_storage_btn.clicked.connect(self._open_storage_dir)
        btn_row.addWidget(self.open_storage_btn)

        self.change_storage_btn = QPushButton("更改位置…")
        self.change_storage_btn.clicked.connect(self._change_storage_location)
        btn_row.addWidget(self.change_storage_btn)

        self.portable_storage_btn = QPushButton("放到软件目录")
        self.portable_storage_btn.setObjectName("Ghost")
        self.portable_storage_btn.setToolTip(
            "把数据放到程序目录下的 data 文件夹，整个文件夹拷走就能带走曲库")
        self.portable_storage_btn.clicked.connect(self._use_portable_storage)
        # 便携模式只在打包版生效（开发态判断会踩到仓库里的 data/），这里直接禁用
        if not app_paths.is_packaged():
            self.portable_storage_btn.setEnabled(False)
            self.portable_storage_btn.setToolTip("仅打包后的程序支持便携模式")
        btn_row.addWidget(self.portable_storage_btn)

        self.reset_storage_btn = QPushButton("恢复默认")
        self.reset_storage_btn.setObjectName("Ghost")
        self.reset_storage_btn.clicked.connect(self._reset_storage_location)
        btn_row.addWidget(self.reset_storage_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        hint = QLabel(
            "移动时会把曲库、封面、歌词缓存、背景和设置一起搬过去：先复制并逐个核对文件，"
            "确认无误后才删除原数据；中途失败或取消都不会改动原数据。\n"
            "改完需要关闭并重新打开播放器才生效。"
        )
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addStretch(1)
        return page

    def _refresh_storage_info(self) -> None:
        mode_text = {
            "default": "默认位置（系统用户目录），重装系统前记得先备份。",
            "custom": "自定义位置，程序每次启动都会按这里找数据。",
            "portable": "便携模式：数据就在软件目录的 data 文件夹里，整个文件夹拷走即可。",
            "env": "临时目录（自检或测试指定，不会读写你的真实曲库）。",
        }.get(app_paths.mode(), "")
        self.storage_path_edit.setText(app_paths.current_root())
        self.storage_path_edit.setCursorPosition(0)
        self.storage_mode_label.setText(mode_text)

    def _open_storage_dir(self) -> None:
        folder = app_paths.app_data_dir()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
            QMessageBox.warning(self, "打不开", f"无法打开目录：\n{folder}")

    def _change_storage_location(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "选择数据存放位置", app_paths.current_root())
        if folder:
            self._apply_storage_location(folder)

    def _use_portable_storage(self) -> None:
        if not app_paths.is_packaged():
            QMessageBox.information(self, "仅打包版可用",
                                    "便携模式需要打包后的程序，源码运行时不生效。")
            return
        self._apply_storage_location(
            os.path.join(app_paths.exe_dir(), app_paths.PORTABLE_MARKER))

    def _reset_storage_location(self) -> None:
        if app_paths.mode() == "default":
            QMessageBox.information(self, "已经在默认位置", "当前数据就放在默认位置。")
            return
        self._apply_storage_location(app_paths.default_root())

    def _apply_storage_location(self, folder: str) -> None:
        target = os.path.abspath(folder)
        if os.path.normcase(target) == os.path.normcase(os.path.abspath(app_paths.current_root())):
            QMessageBox.information(self, "已在该位置", "这已经是当前的数据目录了。")
            return
        answer = QMessageBox.question(
            self, "移动数据",
            f"要把数据移动到：\n{target}\n\n"
            "曲库、封面、歌词缓存、背景和设置会一起搬过去。\n"
            "复制并核对成功后才删除原数据；中途失败或取消都不会丢数据。\n\n继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        dialog = StorageMoveDialog(target, remove_source=True, parent=self)
        dialog.exec()
        if dialog.error:
            QMessageBox.warning(self, "移动失败", dialog.error)
            self._refresh_storage_info()
            return
        if dialog.result_info is None:
            self._refresh_storage_info()
            return
        self._refresh_storage_info()
        self.storage_changed.emit(target)
        QMessageBox.information(
            self, "移动完成",
            "数据已经搬到新位置。\n\n请关闭播放器再重新打开，新位置才会生效。")

    # ---------- 主题 / 强调色 / 字号 ----------

    def _on_theme(self, name: str) -> None:
        if name != self._theme_name:
            self._theme_name = name
            self.theme_changed.emit(name)

    def _set_accent(self, color: str) -> None:
        color = (color or "").lower()
        if color == self._accent:
            return
        self._accent = color
        self._sync_swatches()
        self.accent_changed.emit(color)

    def _sync_swatches(self) -> None:
        for swatch in self.swatches:
            swatch.set_selected(swatch.color == self._accent)
        preset_colors = {c for _n, c in ACCENT_PRESETS}
        custom_active = bool(self._accent) and self._accent not in preset_colors
        # 自定义色不在预设里时，把「自定义…」按钮的文字换成色值，让用户知道当前值
        self.custom_btn.setText(self._accent.upper() if custom_active else "自定义…")
        # 「当前没有选中任何色块」时必须有个地方承接这个状态，否则用户看不出现在是什么
        for btn, active in ((self.reset_accent_btn, not self._accent),
                            (self.custom_btn, custom_active)):
            btn.setProperty("active", active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _pick_custom_accent(self) -> None:
        initial = QColor(self._accent) if self._accent else QColor("#6c8cff")
        color = QColorDialog.getColor(initial, self, "选择强调色")
        if color.isValid():
            self._set_accent(color.name())

    def _select_font_scale(self, font_scale: float) -> None:
        """把任意 scale 靠到最近的一档，避免下拉框出现空白。"""
        try:
            value = float(font_scale)
        except (TypeError, ValueError):
            value = 1.0
        best = min(FONT_SCALE_OPTIONS, key=lambda item: abs(item[1] - value))
        self.font_combo.setCurrentIndex(FONT_SCALE_OPTIONS.index(best))

    def _on_font_combo(self, index: int) -> None:
        value = self.font_combo.itemData(index)
        if value is not None and not self._loading:
            self.font_scale_changed.emit(float(value))

    def _on_effect_combo(self, index: int) -> None:
        value = self.effect_combo.itemData(index)
        if value is not None and not self._loading:
            self.lyrics_effect_changed.emit(value)

    # ---------- AI 逐字对齐（v3.0.0） ----------

    def _on_ai_model_combo(self, index: int) -> None:
        value = self.ai_model_combo.itemData(index)
        if value is not None and not self._loading:
            self.ai_model_changed.emit(value)

    def _on_ai_language_combo(self, index: int) -> None:
        value = self.ai_language_combo.itemData(index)
        if value is not None and not self._loading:
            self.ai_language_changed.emit(value)

    def _on_ai_quality_combo(self, index: int) -> None:
        value = self.ai_quality_combo.itemData(index)
        if value is not None and not self._loading:
            self.ai_quality_changed.emit(value)

    def _on_clear_words(self) -> None:
        """清空字级数据：删的是「对齐结果」，不是歌词本身，所以默认按钮仍是「否」。"""
        box = QMessageBox(self)
        box.setWindowTitle("清空字级数据")
        box.setText("将删除所有歌的逐字时间轴（不影响歌词文件与颜色设置）。\n"
                    "之后可以重新对齐，但要再跑一遍。继续吗？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.words_clear_requested.emit()

    # ---------- 歌词颜色覆盖（v2.9.0） ----------

    def _emit_lyrics_color(self) -> None:
        """发一份副本：调用方后续改自己那份时不会串到对话框状态。"""
        self.lyrics_color_changed.emit(
            LyricsColorConfig.from_dict(self._lyrics_color.to_dict()))

    def _on_color_enabled(self, checked: bool) -> None:
        if self._loading:
            return
        self._lyrics_color.enabled = bool(checked)
        self._sync_color_widgets()
        self._emit_lyrics_color()

    def _on_color_trigger(self, index: int) -> None:
        value = self.color_trigger_combo.itemData(index)
        if self._loading or value is None:
            return
        self._lyrics_color.trigger = value
        self._sync_color_widgets()
        self._emit_lyrics_color()

    def _on_color_direction(self, index: int) -> None:
        value = self.color_direction_combo.itemData(index)
        if self._loading or value is None:
            return
        self._lyrics_color.direction = value
        self._emit_lyrics_color()

    def _pick_lyric_color(self, field: str) -> None:
        current = getattr(self._lyrics_color, field) or ui_theme.current_theme().ACCENT
        color = QColorDialog.getColor(QColor(current), self, "选择歌词颜色")
        if not color.isValid():
            return
        setattr(self._lyrics_color, field, color.name())
        self._sync_color_widgets()
        self._emit_lyrics_color()

    def _reset_lyric_colors(self) -> None:
        self._lyrics_color.color_a = ""
        self._lyrics_color.color_b = ""
        self._sync_color_widgets()
        self._emit_lyrics_color()

    def _on_color_speed(self, value: int) -> None:
        if self._loading:
            return
        self._lyrics_color.speed = max(0.05, min(2.0, value / 100))
        self.color_speed_value.setText(f"{value}%")
        self._emit_lyrics_color()

    def _on_color_transition(self, value: int) -> None:
        if self._loading:
            return
        self._lyrics_color.transition = max(0.0, min(0.3, value / 100))
        self.color_transition_value.setText(f"{value}%")
        self._emit_lyrics_color()

    def _sync_color_widgets(self) -> None:
        """按当前配置刷新颜色按钮与「速度」可用状态（不发信号）。"""
        cfg = self._lyrics_color
        for btn, value in ((self.color_a_btn, cfg.color_a),
                           (self.color_b_btn, cfg.color_b)):
            if value:
                btn.setText(value.upper())
                btn.setStyleSheet(_color_button_style(value))
            else:
                btn.setText("随主题")
                btn.setStyleSheet("")
        is_time = cfg.trigger == "time"
        self.color_speed_slider.setEnabled(is_time)

    # ---------- 背景 ----------

    def _current_bg(self) -> BackgroundConfig:
        return self._bg[self._bg_scope]

    def _on_bg_scope_changed(self, index: int) -> None:
        if self._loading:
            return
        scope = self.bg_scope_combo.itemData(index)
        if scope not in self._bg:
            return
        self._bg_scope = scope
        self._load_background_scope(scope)

    def _on_bg_inherit_toggled(self, checked: bool) -> None:
        if self._loading or self._bg_scope == "all":
            return
        self._current_bg().inherit = not checked
        self._emit_background()

    def _on_bg_type_changed(self, index: int) -> None:
        if self._loading:
            return
        cfg = self._current_bg()
        cfg.type = self.bg_type_combo.itemData(index) or "none"
        if cfg.type == "live":
            # 动态背景的 preset 存的是风格 key，别被下面「离开图片就清空」的逻辑抹掉
            if cfg.preset not in LIVE_BY_KEY:
                cfg.preset = LIVE_KEYS[0]
        elif cfg.type != "image" or cfg.preset in LIVE_BY_KEY:
            # 离开图片类型就不再是内置预设；从「动态背景」切到图片时，preset 里
            # 残留的风格 id 对图片毫无意义（会让说明显示「内置背景：dust」）
            cfg.preset = ""
        if cfg.type == "image" and cfg.dim <= 0:
            cfg.dim = 0.35          # 默认压暗一点：直接铺亮图文字会看不清
        self._mark_page_custom()
        self._sync_bg_widgets()
        self._emit_background()

    def _on_bg_slider_changed(self, _value: int) -> None:
        if self._loading:
            return
        cfg = self._current_bg()
        cfg.opacity = self.opacity_slider.value() / 100
        cfg.blur = self.blur_slider.value()
        cfg.dim = self.dim_slider.value() / 100
        self._mark_page_custom()
        self._sync_bg_value_labels()
        self._emit_background()

    def _pick_bg_color(self, field: str) -> None:
        cfg = self._current_bg()
        current = getattr(cfg, field) or "#3b82f6"
        color = QColorDialog.getColor(QColor(current), self, "选择颜色")
        if not color.isValid():
            return
        setattr(cfg, field, color.name())
        self._mark_page_custom()
        self._sync_bg_widgets()
        self._emit_background()

    def _pick_bg_image(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "选择背景图片", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;所有文件 (*.*)")
        if not path:
            return
        try:
            stored = import_background(path, bgs_dir())
        except OSError:
            self.image_label.setText("图片无法读取")
            return
        cfg = self._current_bg()
        cfg.image = stored
        cfg.preset = ""             # 选了自定义图片就退出内置预设
        cfg.type = "image"
        if cfg.dim <= 0:
            cfg.dim = 0.35
        self._mark_page_custom()
        self._sync_bg_widgets()
        self._emit_background()

    def _clear_bg_image(self) -> None:
        cfg = self._current_bg()
        cfg.image = ""
        cfg.preset = ""
        if cfg.type == "image":
            cfg.type = "none"
        self._mark_page_custom()
        self._sync_bg_widgets()
        self._emit_background()

    def _load_background_scope(self, scope: str) -> None:
        """把某个作用域的配置搬到控件上（切作用域时用，期间不触发信号）。"""
        self._loading = True
        try:
            index = self.bg_scope_combo.findData(scope)
            if index >= 0:
                self.bg_scope_combo.setCurrentIndex(index)
            cfg = self._bg[scope]
            type_index = self.bg_type_combo.findData(cfg.type)
            self.bg_type_combo.setCurrentIndex(max(0, type_index))
            # 「全部页面」不存在跟随谁的问题 —— 直接藏起来，而不是灰成一个
            # 几乎看不见的控件（用户会以为界面缺了一块）
            self.bg_inherit_box.setVisible(scope != "all")
            self.bg_inherit_box.setChecked(scope != "all" and not cfg.inherit)
            self.opacity_slider.setValue(round(cfg.opacity * 100))
            self.blur_slider.setValue(int(cfg.blur))
            self.dim_slider.setValue(round(cfg.dim * 100))
            self._sync_bg_value_labels()
            self._sync_bg_widgets()
            self._sync_bg_presets()
        finally:
            self._loading = False

    def _sync_bg_value_labels(self) -> None:
        self.opacity_value.setText(f"{self.opacity_slider.value()}%")
        self.blur_value.setText(str(self.blur_slider.value()))
        self.dim_value.setText(f"{self.dim_slider.value()}%")

    def _sync_bg_widgets(self) -> None:
        """按类型显隐相关控件：选纯色时不该还摆着一行「选图片」。"""
        cfg = self._current_bg()
        needs_color = cfg.type in ("color", "gradient", "live")
        self.color_row.setVisible(needs_color)
        self.color2_label.setVisible(cfg.type == "gradient")
        self.color2_btn.setVisible(cfg.type == "gradient")
        self.image_row.setVisible(cfg.type == "image")

        self.color_btn.setText(cfg.color.upper())
        self.color_btn.setStyleSheet(_color_button_style(cfg.color))
        self.color2_btn.setText(cfg.color2.upper())
        self.color2_btn.setStyleSheet(_color_button_style(cfg.color2))
        if cfg.preset:
            preset = ui_theme.PRESET_BY_ID.get(cfg.preset)
            self.image_label.setText(f"内置背景：{preset.label if preset else cfg.preset}")
            self.image_label.setToolTip("随程序分发的内置背景图")
        elif cfg.image:
            self.image_label.setText(os.path.basename(cfg.image))
            self.image_label.setToolTip(cfg.image)
        else:
            self.image_label.setText("未选择")
            self.image_label.setToolTip("")

        for widget in (self.opacity_slider, self.blur_slider, self.dim_slider):
            widget.setEnabled(cfg.type != "none")
        # 动态背景没有位图可模糊（模糊滑块对它无意义），灰掉免得用户白调
        self.blur_slider.setEnabled(cfg.type == "image")
        self.bg_inherit_box.setVisible(self._bg_scope != "all")

    def _apply_preset(self, preset_id: str) -> None:
        """点内置背景卡片：把当前页背景设成这张图（带预设默认暗化/不透明度）。"""
        preset_cfg = ui_theme.background_preset_config(preset_id)
        if preset_cfg is None:
            return
        cfg = self._current_bg()
        cfg.type = "image"
        cfg.preset = preset_id
        cfg.image = ""              # 预设不占用用户图片路径
        cfg.opacity = preset_cfg.opacity
        cfg.blur = preset_cfg.blur
        cfg.dim = preset_cfg.dim
        # 让控件同步（类型选到「图片」、三个滑块贴到预设默认值），期间不发信号
        self._loading = True
        try:
            idx = self.bg_type_combo.findData("image")
            self.bg_type_combo.setCurrentIndex(max(0, idx))
            self.opacity_slider.setValue(round(cfg.opacity * 100))
            self.blur_slider.setValue(int(cfg.blur))
            self.dim_slider.setValue(round(cfg.dim * 100))
            self._sync_bg_value_labels()
        finally:
            self._loading = False
        self._sync_bg_widgets()
        self._sync_bg_presets()
        self._mark_page_custom()
        self._emit_background()

    def _apply_live(self, style_key: str) -> None:
        """点动态背景卡片：切到实时动画背景（v3.3.0）。

        默认强度给 0.8：满强度时图元 alpha 会叠到接近上限，左侧列表的图标
        反而因为底色变亮而对比下降 —— 「更亮」不等于「更好看」。
        """
        cfg = self._current_bg()
        cfg.type = "live"
        cfg.preset = style_key if style_key in LIVE_BY_KEY else LIVE_KEYS[0]
        cfg.image = ""
        if cfg.opacity >= 0.99:
            cfg.opacity = 0.8
        self._loading = True
        try:
            idx = self.bg_type_combo.findData("live")
            self.bg_type_combo.setCurrentIndex(max(0, idx))
            self.opacity_slider.setValue(round(cfg.opacity * 100))
            self.dim_slider.setValue(round(cfg.dim * 100))
            self._sync_bg_value_labels()
        finally:
            self._loading = False
        self._sync_bg_widgets()
        self._sync_bg_presets()
        self._mark_page_custom()
        self._emit_background()

    def _sync_bg_presets(self) -> None:
        """标出当前激活的内置预设卡片（用 active 属性 + repolish）。

        v3.3.0 起同一个方法管两组卡片：静态图案（preset_buttons）与动态背景
        （live_buttons）。两者的「激活」判据都是 `cfg.preset`，但必须带上 type ——
        否则选了动态背景后，同名的静态卡片会一起亮起来。
        """
        cfg = self._current_bg()
        for pid, btn in getattr(self, "preset_buttons", {}).items():
            active = cfg.type == "image" and cfg.preset == pid
            btn.setProperty("active", active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        for key, btn in getattr(self, "live_buttons", {}).items():
            active = cfg.type == "live" and cfg.preset == key
            btn.setProperty("active", active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _mark_page_custom(self) -> None:
        """在分页面作用域上主动改背景，就自动「本页单独设置」（inherit=False）。

        否则用户切到「列表页/正在播放页」设背景，inherit 仍是默认 True（跟随
        「全部页面」），Settings.bg_config() 会静默退回 bg_all —— 表现为「设了
        没反应」。勾选动作用 _loading 挡住 toggled 信号，避免重复处理。
        """
        if self._bg_scope == "all":
            return
        cfg = self._current_bg()
        if not cfg.inherit:
            return
        cfg.inherit = False
        self._loading = True
        try:
            self.bg_inherit_box.setChecked(True)
        finally:
            self._loading = False

    def _emit_background(self) -> None:
        cfg = self._current_bg()
        if self._bg_scope == "all":
            cfg.inherit = True     # 「全部页面」不存在跟随谁的问题
        self.background_changed.emit(self._bg_scope, cfg)


def _color_button_style(color: str) -> str:
    """颜色按钮：整块填充该色 + 色值文字。作用域限定到本控件，避免级联。"""
    text = "#101014" if _is_light(color) else "#ffffff"
    return (
        "QPushButton { border: 1px solid #8888; border-radius: 8px; padding: 4px 6px;"
        f" background: {color}; color: {text}; }}"
    )


def _is_light(color: str) -> bool:
    from ui.theme import luminance

    try:
        return luminance(color) > 0.55
    except (ValueError, IndexError):
        return False


def format_duration(total_ms: int) -> str:
    minutes = total_ms // 60000
    if minutes < 60:
        return f"{minutes} 分钟"
    return f"{minutes // 60} 小时 {minutes % 60} 分钟"


def stats_for(store) -> dict:
    tracks = store.all_tracks()
    return {
        "tracks": len(tracks),
        "playlists": len(store.user_playlists()),
        "favorites": store.favorite_count(),
        "total_duration": format_duration(sum(t.duration_ms for t in tracks)),
    }
