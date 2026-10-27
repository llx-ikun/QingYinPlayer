# -*- coding: utf-8 -*-
"""设置对话框：外观（主题/强调色/字号）、自定义背景、歌词与统计。

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

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.library import import_background
from app.models import BackgroundConfig
from app.paths import bgs_dir
from ui import theme as ui_theme
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

BG_TYPE_OPTIONS = [
    ("无背景（跟随主题）", "none"),
    ("纯色", "color"),
    ("渐变", "gradient"),
    ("图片", "image"),
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
    theme_changed = Signal(str)          # columbina / dark / light
    nickname_changed = Signal(str)
    online_lyrics_changed = Signal(bool)
    accent_changed = Signal(str)         # "#rrggbb"，"" = 跟随主题默认
    font_scale_changed = Signal(float)
    background_changed = Signal(str, object)   # (作用域, BackgroundConfig)

    def __init__(self, theme_name: str, nickname: str, stats: dict, parent=None,
                 online_lyrics: bool = True, accent_color: str = "",
                 font_scale: float = 1.0, bg_configs: dict | None = None,
                 bg_scope: str = "all"):
        super().__init__(parent)
        self.setObjectName("SettingsDialog")
        self.setWindowTitle("设置")
        self.setMinimumWidth(430)
        self._theme_name = theme_name if theme_name in ui_theme.THEMES else ui_theme.DEFAULT_THEME
        self._accent = (accent_color or "").lower()
        self._font_scale = font_scale
        self._loading = False
        self._bg_scope = bg_scope if bg_scope in ("all", "library", "now_playing") else "all"
        self._bg: dict[str, BackgroundConfig] = {}
        for scope in ("all", "library", "now_playing"):
            source = (bg_configs or {}).get(scope)
            self._bg[scope] = (BackgroundConfig.from_dict(source.to_dict())
                               if isinstance(source, BackgroundConfig) else BackgroundConfig())

        root = QVBoxLayout(self)
        root.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("SettingsTabs")
        self.tabs.addTab(self._build_appearance_tab(nickname), "外观")
        self.tabs.addTab(self._build_background_tab(), "背景")
        self.tabs.addTab(self._build_misc_tab(stats, online_lyrics), "歌词与统计")
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

        theme_row = QHBoxLayout()
        theme_row.setSpacing(16)
        theme_row.addWidget(QLabel("主题"))
        self.theme_radios: dict[str, QRadioButton] = {}
        for tid in ui_theme.THEME_ORDER:
            radio = QRadioButton(ui_theme.THEME_LABEL[tid])
            radio.setChecked(tid == self._theme_name)
            radio.toggled.connect(lambda checked, t=tid: checked and self._on_theme(t))
            theme_row.addWidget(radio)
            self.theme_radios[tid] = radio
        # 兼容旧引用
        self.dark_radio = self.theme_radios["dark"]
        self.light_radio = self.theme_radios["light"]
        theme_row.addStretch(1)
        root.addLayout(theme_row)

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

        hint = QLabel("外观改动立即生效，可以一边看一边调。")
        hint.setObjectName("Dim")
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addStretch(1)

        self._sync_swatches()
        return page

    # ---------- 页 2：背景 ----------

    def _build_background_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setSpacing(10)

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

        about = QLabel("轻音播放器 v2.2 · 本地音乐与视频，歌词可联网补全")
        about.setObjectName("Dim")
        root.addWidget(about)
        root.addStretch(1)
        return page

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
        if cfg.type == "image" and cfg.dim <= 0:
            cfg.dim = 0.35          # 默认压暗一点：直接铺亮图文字会看不清
        self._sync_bg_widgets()
        self._emit_background()

    def _on_bg_slider_changed(self, _value: int) -> None:
        if self._loading:
            return
        cfg = self._current_bg()
        cfg.opacity = self.opacity_slider.value() / 100
        cfg.blur = self.blur_slider.value()
        cfg.dim = self.dim_slider.value() / 100
        self._sync_bg_value_labels()
        self._emit_background()

    def _pick_bg_color(self, field: str) -> None:
        cfg = self._current_bg()
        current = getattr(cfg, field) or "#3b82f6"
        color = QColorDialog.getColor(QColor(current), self, "选择颜色")
        if not color.isValid():
            return
        setattr(cfg, field, color.name())
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
        cfg.type = "image"
        if cfg.dim <= 0:
            cfg.dim = 0.35
        self._sync_bg_widgets()
        self._emit_background()

    def _clear_bg_image(self) -> None:
        cfg = self._current_bg()
        cfg.image = ""
        if cfg.type == "image":
            cfg.type = "none"
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
        finally:
            self._loading = False

    def _sync_bg_value_labels(self) -> None:
        self.opacity_value.setText(f"{self.opacity_slider.value()}%")
        self.blur_value.setText(str(self.blur_slider.value()))
        self.dim_value.setText(f"{self.dim_slider.value()}%")

    def _sync_bg_widgets(self) -> None:
        """按类型显隐相关控件：选纯色时不该还摆着一行「选图片」。"""
        cfg = self._current_bg()
        needs_color = cfg.type in ("color", "gradient")
        self.color_row.setVisible(needs_color)
        self.color2_label.setVisible(cfg.type == "gradient")
        self.color2_btn.setVisible(cfg.type == "gradient")
        self.image_row.setVisible(cfg.type == "image")

        self.color_btn.setText(cfg.color.upper())
        self.color_btn.setStyleSheet(_color_button_style(cfg.color))
        self.color2_btn.setText(cfg.color2.upper())
        self.color2_btn.setStyleSheet(_color_button_style(cfg.color2))
        if cfg.image:
            self.image_label.setText(os.path.basename(cfg.image))
            self.image_label.setToolTip(cfg.image)
        else:
            self.image_label.setText("未选择")
            self.image_label.setToolTip("")

        for widget in (self.opacity_slider, self.blur_slider, self.dim_slider):
            widget.setEnabled(cfg.type != "none")
        self.bg_inherit_box.setVisible(self._bg_scope != "all")

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
