# -*- coding: utf-8 -*-
"""双主题（默认深色 / 浅色浅蓝）：调色板 + QSS + 主题应用。

- Theme 为不可变数据类；THEMES 注册全部主题；build_stylesheet(theme) 生成 QSS。
- apply_theme(app, name)：切换主题 = 换 QSS + 重绘全部主题化图标 + 均衡器条换色。
- 模块级 __getattr__ 让 `from ui.theme import ACCENT` 始终读到**当前主题**的值，
  兼容 v1 代码的常量引用习惯。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    BG: str               # 窗口底
    SURFACE: str          # 面板（侧边栏/标题栏/播放栏/菜单）
    SURFACE_HOVER: str    # 悬浮
    SURFACE_ACTIVE: str   # 选中
    BORDER: str
    TEXT: str
    TEXT_DIM: str
    ACCENT: str           # 强调色（深=蓝紫，浅=QQ 绿）
    ACCENT_HOVER: str
    ACCENT_DIM: str
    ACCENT_SOFT: str      # 强调淡底（选中行/图标导航激活/徽章）
    DANGER: str
    HEART: str            # 爱心红
    ON_ACCENT: str        # 强调色上的文字/图标


DARK = Theme(
    name="dark",
    BG="#0f0f14", SURFACE="#16161f", SURFACE_HOVER="#1e1e2a", SURFACE_ACTIVE="#262633",
    BORDER="#2a2a38", TEXT="#f0f0f4", TEXT_DIM="#8f8fa3",
    ACCENT="#6c8cff", ACCENT_HOVER="#829fff", ACCENT_DIM="#3d4f8f",
    ACCENT_SOFT="#232b47", DANGER="#ff6b6b", HEART="#ff5c7a", ON_ACCENT="#ffffff",
)

LIGHT = Theme(
    name="light",
    # 浅蓝风：中性灰底改为淡蓝灰，悬浮/选中/边框都带一点蓝，与深色主题的蓝紫强调色、
    # 应用图标（蓝紫渐变）保持一致。原先的 QQ 绿（#31c27c）与图标不同色系，已替换。
    BG="#f3f6fc", SURFACE="#ffffff", SURFACE_HOVER="#eef3fb", SURFACE_ACTIVE="#e3ecfb",
    BORDER="#dde5f3", TEXT="#1f2329", TEXT_DIM="#7f8b9e",
    ACCENT="#3b82f6", ACCENT_HOVER="#2f74ea", ACCENT_DIM="#2563eb",
    ACCENT_SOFT="#e7f0fe", DANGER="#e14a4a", HEART="#ec4141", ON_ACCENT="#ffffff",
)

THEMES = {"dark": DARK, "light": LIGHT}
DEFAULT_THEME = "dark"

FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif'

_current: Theme = DARK

# 供 from ui.theme import ACCENT 使用的字段名
_FIELD_NAMES = tuple(DARK.__dataclass_fields__)


def current_theme() -> Theme:
    return _current


def __getattr__(name: str):
    """`from ui.theme import ACCENT` 动态解析到当前主题（PEP 562）。"""
    if name in _FIELD_NAMES:
        return getattr(_current, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def set_theme(name: str) -> Theme:
    global _current
    _current = THEMES.get(name, DARK)
    return _current


def apply_theme(app, name: str) -> Theme:
    """切换主题：换 QSS + 重绘主题化图标 + 均衡器条换色。app 为 QApplication/QWidget。"""
    theme = set_theme(name)
    app.setStyleSheet(build_stylesheet(theme))
    from ui import icons as ic
    ic.refresh_icons()
    from ui.widgets import refresh_equalizers
    refresh_equalizers(theme.ACCENT)
    return theme


def build_stylesheet(theme: Theme | None = None) -> str:
    t = theme or _current
    return f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: 13px;
    color: {t.TEXT};
    outline: none;
}}

QMainWindow, QDialog {{ background: {t.BG}; }}

/* ---------- 无边框窗口根容器（圆角由 mask 硬裁剪） ---------- */
QWidget#WindowRoot {{ background: {t.BG}; border: 1px solid {t.BORDER}; border-radius: 10px; }}
QWidget#WindowRoot[is_maximized="true"] {{ border-radius: 0px; border: none; }}

/* ---------- 标题栏（通栏） ---------- */
QWidget#TitleBar {{ background: {t.SURFACE}; border-bottom: 1px solid {t.BORDER};
    border-top-left-radius: 10px; border-top-right-radius: 10px; }}
QWidget#WindowRoot[is_maximized="true"] QWidget#TitleBar {{ border-radius: 0px; }}
QPushButton#TitleBtn {{
    background: transparent; border: none; border-radius: 6px;
    min-width: 34px; max-width: 34px; min-height: 28px; max-height: 28px; color: {t.TEXT_DIM};
}}
QPushButton#TitleBtn:hover {{ background: {t.SURFACE_HOVER}; color: {t.TEXT}; }}
QPushButton#TitleBtn#CloseBtn:hover {{ background: #e81123; color: #ffffff; }}
QPushButton#TitleBtn:disabled {{ color: {t.BORDER}; }}

/* ---------- 搜索框（胶囊） ---------- */
QLineEdit#SearchBox {{
    background: {t.SURFACE_HOVER}; border: 1px solid transparent; border-radius: 16px;
    padding: 6px 12px; color: {t.TEXT}; selection-background-color: {t.ACCENT};
}}
QLineEdit#SearchBox:focus {{ border: 1px solid {t.ACCENT}; background: {t.SURFACE}; }}

/* ---------- 侧边栏 / 播放栏 ---------- */
QWidget#Sidebar {{ background: {t.SURFACE}; border-right: 1px solid {t.BORDER}; }}
QWidget#Panel, QWidget#PlayerBar {{ background: {t.SURFACE}; }}
QWidget#PlayerBar {{ border-top: 1px solid {t.BORDER};
    border-bottom-left-radius: 10px; border-bottom-right-radius: 10px; }}
QWidget#WindowRoot[is_maximized="true"] QWidget#PlayerBar {{ border-radius: 0px; }}
QWidget#HeaderBar {{ background: {t.BG}; }}

/* ---------- 视频页（v2.1） ---------- */
QWidget#VideoSinkHost {{ background: #000000; border-radius: 10px; }}
QWidget#VideoSurface {{ background: #000000; }}
QLabel#VideoTitle {{ font-size: 16px; font-weight: bold; color: {t.TEXT}; }}

/* ---------- 标签 ---------- */
QLabel {{ background: transparent; }}
QLabel#Dim {{ color: {t.TEXT_DIM}; }}
QLabel#Logo {{ font-size: 15px; font-weight: bold; color: {t.TEXT}; }}
QLabel#TrackTitle {{ font-size: 13px; font-weight: bold; color: {t.TEXT}; }}
QLabel#TrackSub {{ color: {t.TEXT_DIM}; font-size: 12px; }}
QLabel#Badge {{
    background: {t.SURFACE_HOVER}; color: {t.TEXT_DIM}; border-radius: 8px;
    padding: 1px 8px; font-size: 11px;
}}

/* ---------- 列表页页头（v2.1.4：大标题 + 统计 + 排序工具行） ---------- */
QWidget#PageHeader {{ background: transparent; }}
QLabel#PageTitle {{ font-size: 20px; font-weight: bold; color: {t.TEXT}; }}
/* 次级信息统一 12px 灰：统计、排序说明 */
QLabel#Stats {{ color: {t.TEXT_DIM}; font-size: 12px; }}
/* 列头：无额外内边距，位置完全由布局槽位决定（与行逐列对齐） */
QWidget#ColumnHeaderBar {{
    background: {t.BG}; border-bottom: 1px solid {t.BORDER};
}}
QLabel#ColumnHeader {{ color: {t.TEXT_DIM}; font-size: 12px; padding: 0px; }}
/* 空态：大号音符水印 + 说明文案 */
QLabel#EmptyGlyph {{ font-size: 44px; color: {t.BORDER}; }}
QLabel#EmptyText {{ color: {t.TEXT_DIM}; font-size: 13px; }}
QLabel#Avatar {{
    background: {t.ACCENT}; color: {t.ON_ACCENT}; font-size: 17px; font-weight: bold;
    border-radius: 21px; min-width: 42px; max-width: 42px; min-height: 42px; max-height: 42px;
}}
QLabel#FmtBadge {{
    border: 1px solid {t.BORDER}; border-radius: 6px; color: {t.TEXT_DIM};
    font-size: 10px; padding: 1px 5px;
}}
QLabel#FmtBadge[tier="lossless"] {{ color: {t.ACCENT}; border-color: {t.ACCENT}; }}
QLabel#FmtBadge[tier="video"] {{ color: {t.HEART}; border-color: {t.HEART}; }}
QLabel#Toast {{
    background: {t.SURFACE}; color: {t.TEXT}; border: 1px solid {t.BORDER};
    border-radius: 8px; padding: 7px 14px;
}}

/* ---------- 用户卡片 / 图标导航 ---------- */
QWidget#UserCard {{ border-radius: 10px; }}
QWidget#UserCard:hover {{ background: {t.SURFACE_HOVER}; }}
QPushButton#IconNav {{
    background: {t.SURFACE_HOVER}; border: none; border-radius: 12px;
    min-width: 46px; max-width: 46px; min-height: 46px; max-height: 46px;
}}
QPushButton#IconNav:hover {{ background: {t.SURFACE_ACTIVE}; }}
QPushButton#IconNav[active="true"] {{ background: {t.ACCENT_SOFT}; }}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px 10px;
    color: {t.TEXT};
}}
QPushButton:hover {{ background: {t.SURFACE_HOVER}; }}
QPushButton:pressed {{ background: {t.SURFACE_ACTIVE}; }}
QPushButton:disabled {{ color: {t.BORDER}; }}
/* 固定尺寸的图标按钮必须显式 padding: 0：
   基础 QPushButton 规则带 6px 10px 内边距，会叠加在 min/max-width 之上，
   使声明尺寸普遍虚胖 20px（34→54、40→60、46→66、36→58）。
   后果：播放键 border-radius 不再是圆、行内按钮撑歪列对齐、浮动条超宽被裁。 */
QPushButton#TitleBtn, QPushButton#ControlBtn, QPushButton#PlayCircle,
QPushButton#IconNav, QPushButton#ThemeToggle {{ padding: 0px; }}
QPushButton#Primary {{
    background: {t.ACCENT};
    color: {t.ON_ACCENT};
    font-weight: bold;
    border-radius: 10px;
    padding: 8px 16px;
}}
QPushButton#Primary:hover {{ background: {t.ACCENT_HOVER}; }}
QPushButton#Primary:pressed {{ background: {t.ACCENT_DIM}; }}
QPushButton#Ghost {{
    background: {t.SURFACE};
    border: 1px solid {t.BORDER};
    border-radius: 8px;
}}
QPushButton#Ghost:hover {{ background: {t.SURFACE_HOVER}; }}

/* 侧边栏导航项（文本） */
QPushButton#NavItem {{
    text-align: left;
    padding: 9px 12px;
    border-radius: 10px;
    color: {t.TEXT_DIM};
    font-size: 13px;
}}
QPushButton#NavItem:hover {{ background: {t.SURFACE_HOVER}; color: {t.TEXT}; }}
QPushButton#NavItem[active="true"] {{
    background: {t.ACCENT_SOFT};
    color: {t.ACCENT};
    font-weight: bold;
}}

/* 播放控制按钮 */
QPushButton#PlayCircle {{
    background: {t.ACCENT};
    border-radius: 20px;
    min-width: 40px; max-width: 40px;
    min-height: 40px; max-height: 40px;
}}
QPushButton#PlayCircle:hover {{ background: {t.ACCENT_HOVER}; }}
QPushButton#PlayCircle:pressed {{ background: {t.ACCENT_DIM}; }}
QPushButton#ControlBtn {{
    border-radius: 17px;
    min-width: 34px; max-width: 34px;
    min-height: 34px; max-height: 34px;
    color: {t.TEXT_DIM};
}}
QPushButton#ControlBtn:hover {{ background: {t.SURFACE_HOVER}; color: {t.TEXT}; }}
QPushButton#ControlBtn[active="true"] {{ color: {t.ACCENT}; }}
/* 行内心形/更多按钮（小号）——padding 必须显式归零：
   基础 QPushButton 规则带 6px 10px 内边距，会叠加在 min/max-width 之上，
   实际宽度变成 28+20=48；列头占位槽是 28，于是整表逐列漂移 40px。 */
QPushButton#RowBtn {{
    border-radius: 14px;
    padding: 0px;
    min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
    color: {t.TEXT_DIM};
}}
QPushButton#RowBtn:hover {{ background: {t.SURFACE_HOVER}; color: {t.TEXT}; }}
QPushButton#RowBtn[active="true"] {{ color: {t.HEART}; }}
/* 浮动工具条：主题切换按钮（开关式，checkable） */
QPushButton#ThemeToggle {{
    background: {t.SURFACE}; border: 1px solid {t.BORDER}; border-radius: 18px;
    min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; color: {t.TEXT_DIM};
}}
QPushButton#ThemeToggle:hover {{ background: {t.SURFACE_HOVER}; color: {t.ACCENT}; }}
QPushButton#ThemeToggle:checked {{ background: {t.ACCENT_SOFT}; color: {t.ACCENT}; border-color: {t.ACCENT}; }}
/* 浮动工具条：图标 + 文字按钮 */
QPushButton#FloatTextBtn {{
    background: {t.SURFACE}; border: 1px solid {t.BORDER}; border-radius: 16px;
    padding: 5px 12px 5px 6px; color: {t.TEXT_DIM}; font-size: 12px;
}}
QPushButton#FloatTextBtn:hover {{ background: {t.SURFACE_HOVER}; color: {t.TEXT}; }}

/* ---------- 列表 ---------- */
QListWidget {{
    background: transparent;
    border: none;
}}
QListWidget::item {{
    border-radius: 10px;
    padding: 0px;
    margin: 2px 8px;
}}
QListWidget::item:hover {{ background: {t.SURFACE_HOVER}; }}
QListWidget::item:selected {{ background: {t.ACCENT_SOFT}; }}
QListWidget::item:selected:active {{ background: {t.ACCENT_SOFT}; }}

/* ---------- 输入框 ---------- */
QLineEdit, QTextEdit {{
    background: {t.SURFACE};
    border: 1px solid {t.BORDER};
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {t.ACCENT};
}}
QLineEdit:focus, QTextEdit:focus {{ border: 1px solid {t.ACCENT}; }}

/* ---------- 下拉框 ---------- */
QComboBox {{
    background: {t.SURFACE};
    border: 1px solid {t.BORDER};
    border-radius: 8px;
    padding: 5px 10px;
    min-width: 70px;
}}
QComboBox:hover {{ border: 1px solid {t.ACCENT_DIM}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {t.SURFACE};
    border: 1px solid {t.BORDER};
    border-radius: 8px;
    selection-background-color: {t.ACCENT_SOFT};
    padding: 4px;
}}
/* 列表排序下拉（v2.1.4）：胶囊形，条目文案即当前排序方式 */
QComboBox#SortCombo {{
    background: {t.SURFACE};
    border: 1px solid {t.BORDER};
    border-radius: 14px;
    padding: 4px 8px 4px 12px;
    min-width: 132px;
    font-size: 12px;
    color: {t.TEXT};
}}
QComboBox#SortCombo:hover {{ border-color: {t.ACCENT_DIM}; color: {t.ACCENT}; }}
QComboBox#SortCombo::drop-down {{ border: none; width: 20px; }}
QComboBox#SortCombo QAbstractItemView {{
    padding: 5px;
    border-radius: 10px;
    selection-background-color: {t.ACCENT_SOFT};
    selection-color: {t.ACCENT};
}}
QComboBox#SortCombo QAbstractItemView::item {{ padding: 5px 8px; border-radius: 6px; }}

/* ---------- 滑块 ---------- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {t.BORDER};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {t.ACCENT};
    border-radius: 2px;
}}
QSlider::add-page:horizontal {{
    background: {t.BORDER};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: #ffffff;
    width: 12px;
    height: 12px;
    margin: -4px 0px;
    border-radius: 6px;
    border: 1px solid {t.BORDER};
}}
QSlider::handle:horizontal:hover {{ background: {t.ACCENT_HOVER}; }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {t.BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {t.TEXT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::up-arrow, QScrollBar::down-arrow {{
    background: none; border: none; height: 0;
}}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {t.BORDER}; border-radius: 5px; min-width: 30px; }}

/* ---------- 菜单 / 提示 / 状态栏 ---------- */
QMenu {{
    background: {t.SURFACE};
    border: 1px solid {t.BORDER};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: 6px;
}}
QMenu::item:selected {{ background: {t.SURFACE_HOVER}; }}
QMenu::separator {{ height: 1px; background: {t.BORDER}; margin: 5px 8px; }}
QToolTip {{
    background: {t.SURFACE_ACTIVE};
    color: {t.TEXT};
    border: 1px solid {t.BORDER};
    border-radius: 6px;
    padding: 5px 8px;
}}
QStatusBar {{ background: transparent; color: {t.TEXT_DIM}; min-height: 22px; }}
QStatusBar::item {{ border: none; }}
QMessageBox {{ background: {t.SURFACE}; }}

/* ---------- 对话框专用 ---------- */
QDialog {{ background: {t.SURFACE}; }}
QDialog#QueuePanel {{
    background: {t.SURFACE}; border: 1px solid {t.BORDER}; border-radius: 10px;
}}
QDialog#SettingsDialog QLabel {{ background: transparent; }}
"""
