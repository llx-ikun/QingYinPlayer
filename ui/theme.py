# -*- coding: utf-8 -*-
"""双主题（默认深色 / 浅色浅蓝）：调色板 + QSS + 主题应用。

- Theme 为不可变数据类；THEMES 注册全部主题；build_stylesheet(theme) 生成 QSS。
- apply_theme(app, name)：切换主题 = 换 QSS + 重绘全部主题化图标 + 均衡器条换色。
- 模块级 __getattr__ 让 `from ui.theme import ACCENT` 始终读到**当前主题**的值，
  兼容 v1 代码的常量引用习惯。

v2.2 起支持「外观自定义」：
- **强调色**：用户只给一个色值，`derive_accent()` 派生 hover/dim/soft/on_accent
  四档（让用户手调四档既难用又会自相矛盾）。
- **字号缩放**：`build_stylesheet(theme, font_scale=)` 用正则把所有 `font-size: Npx`
  乘上系数。为什么在 QSS 文本层做而不是改控件字体：字号散落在 20 多处 QSS 规则里，
  改控件 font 会被 QSS 覆盖；在文本层缩放是唯一"一处生效、全局一致"的做法。
  代价：固定高度控件（行高 52、播放栏 84）不会跟着长，所以缩放范围要夹住。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace


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
    ACCENT: str           # 强调色（深=蓝紫，浅=浅蓝）
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

# 字号缩放安全区间：行高 52 / 播放栏 84 / 侧栏 248 都是固定值，
# 超出这个范围文字会被裁切（不是"变小"，而是"看不全"）。
FONT_SCALE_MIN = 0.85
FONT_SCALE_MAX = 1.30
FONT_SCALE_DEFAULT = 1.0
FONT_PX_FLOOR = 9          # 10px 徽标 × 0.85 ≈ 9，再小就不可读

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_FONT_SIZE_RE = re.compile(r"font-size:\s*(\d+)px")


def _rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _rgba(color: str, alpha: float) -> str:
    r, g, b = _rgb(color)
    return f"rgba({r}, {g}, {b}, {max(0.0, min(1.0, alpha)):.3f})"


def mix(color_a: str, color_b: str, ratio: float) -> str:
    """把 a 往 b 混 `ratio`（0=全 a，1=全 b）。"""
    ra, rb = _rgb(color_a), _rgb(color_b)
    return _hex(tuple(ra[i] + (rb[i] - ra[i]) * ratio for i in range(3)))


def luminance(color: str) -> float:
    """WCAG 相对亮度，用来决定 ON_ACCENT 该白还是该黑。"""
    def lin(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(color_a: str, color_b: str) -> float:
    hi, lo = sorted((luminance(color_a), luminance(color_b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def derive_accent(base: Theme, accent: str | None) -> Theme:
    """用一个自定义强调色派生整套主题。

    派生规则（以「底色亮暗」为准，而不是硬编码某个主题）：
    - ACCENT_HOVER：深色底上提亮 20%，浅色底上压暗 15%（悬浮要"更显眼"）；
    - ACCENT_DIM：压暗 30%（按下态，比 hover 更沉）；
    - ACCENT_SOFT：往 SURFACE 里混 13%，得到"选中行"那种一眼看出但不抢的淡底；
    - ON_ACCENT：先试白字，白字对比度不足 3:1 才换近黑 —— 亮橙/黄这种强调色上
      白字根本看不见（实测 #ff7a45 上白字只有 2.6:1）。
    """
    if not accent or not isinstance(accent, str) or not _HEX_RE.match(accent):
        return base
    accent = accent.lower()
    dark_ui = luminance(base.BG) < 0.5
    hover = mix(accent, "#ffffff", 0.20) if dark_ui else mix(accent, "#000000", 0.15)
    # hover 与主色必须肉眼可分：极浅的强调色提亮后几乎不动，改为压暗
    if max(abs(a - b) for a, b in zip(_rgb(hover), _rgb(accent), strict=True)) < 12:
        hover = mix(accent, "#000000", 0.18)
    dim = mix(accent, "#000000", 0.30)
    soft = mix(base.SURFACE, accent, 0.13)
    on_accent = "#ffffff" if contrast("#ffffff", accent) >= 3.0 else "#101014"
    return replace(base, ACCENT=accent, ACCENT_HOVER=hover, ACCENT_DIM=dim,
                   ACCENT_SOFT=soft, ON_ACCENT=on_accent)


def clamp_font_scale(value) -> float:
    """把任意输入夹进安全区间；非法值回落到 1.0。"""
    try:
        scale = float(value)
    except (TypeError, ValueError):
        return FONT_SCALE_DEFAULT
    if scale != scale:              # NaN
        return FONT_SCALE_DEFAULT
    return max(FONT_SCALE_MIN, min(FONT_SCALE_MAX, round(scale, 3)))


def _scale_font_sizes(css: str, scale: float) -> str:
    if scale == FONT_SCALE_DEFAULT:
        return css
    return _FONT_SIZE_RE.sub(
        lambda m: f"font-size: {max(FONT_PX_FLOOR, round(int(m.group(1)) * scale))}px",
        css,
    )


_current: Theme = DARK
_base_name: str = DEFAULT_THEME
_accent_override: str | None = None
_font_scale: float = FONT_SCALE_DEFAULT
_scrim: float | None = None

# 自定义背景开启时面板的不透明度：太高背景看不见，太低文字压不住
BG_SCRIM = 0.78

# 供 from ui.theme import ACCENT 使用的字段名
_FIELD_NAMES = tuple(DARK.__dataclass_fields__)


def current_theme() -> Theme:
    return _current


def current_font_scale() -> float:
    return _font_scale


def __getattr__(name: str):
    """`from ui.theme import ACCENT` 动态解析到当前主题（PEP 562）。"""
    if name in _FIELD_NAMES:
        return getattr(_current, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def set_theme(name: str) -> Theme:
    """切主题（保留当前的强调色/字号自定义）。"""
    global _current, _base_name
    _base_name = name if name in THEMES else DEFAULT_THEME
    _current = derive_accent(THEMES[_base_name], _accent_override)
    return _current


def set_appearance(app, theme_name: str | None = None, accent: str | None = None,
                   font_scale: float | None = None, scrim: float | None = None) -> Theme:
    """一次性设定主题 + 强调色 + 字号 + 背景透明度并应用（主窗口的唯一入口）。

    `accent=""` / `None` 表示"跟随主题默认色"；`scrim=None` 表示没有自定义背景。
    """
    global _accent_override, _font_scale, _scrim
    if accent is not None:
        _accent_override = accent.lower() if _HEX_RE.match(accent or "") else None
    if font_scale is not None:
        _font_scale = clamp_font_scale(font_scale)
    _scrim = scrim
    set_theme(theme_name or _base_name)
    return _refresh(app)


def apply_theme(app, name: str) -> Theme:
    """切换主题：换 QSS + 重绘主题化图标 + 均衡器条换色。app 为 QApplication/QWidget。

    保留旧签名（测试与外部脚本仍这么调）；要一起改强调色/字号/背景用 `set_appearance`。
    """
    set_theme(name)
    return _refresh(app)


def _refresh(app) -> Theme:
    app.setStyleSheet(build_stylesheet(_current, font_scale=_font_scale, scrim=_scrim))
    from ui import icons as ic
    ic.refresh_icons()
    from ui.widgets import refresh_equalizers
    refresh_equalizers(_current.ACCENT)
    return _current


def build_stylesheet(theme: Theme | None = None, font_scale: float = FONT_SCALE_DEFAULT,
                     scrim: float | None = None) -> str:
    """生成 QSS。

    `scrim`：自定义背景开启时传面板不透明度（如 0.78）。做法是**全局**把
    SURFACE/BG 换成 rgba，再给浮层补一段不透明覆盖 —— 比逐条规则替换可靠得多，
    也不会漏掉某个角落（漏掉的表现就是「背景只在某块区域露出来」）。
    """
    t = theme or _current
    css = f"""
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
/* 进度条两端时间：左端右对齐、右端左对齐，让时间紧贴滑块、两侧留白对称 */
QLabel#TimeLabel {{ color: {t.TEXT_DIM}; font-size: 12px; padding: 0px; }}
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
/* 设置里「随主题 / 当前自定义色」这类互斥选项：active 表示"当前生效的那一个" */
QPushButton#Ghost[active="true"] {{ border-color: {t.ACCENT}; color: {t.ACCENT}; }}

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
    border: none;
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
/* 浮动工具条：圆形主题开关 + 分段托盘。
   托盘是「浮起的一张卡片」（SURFACE + 细边），内部按钮透明、悬停时才凹下一层
   —— 三个入口读成一组并列工具，而不是三个各自独立的输入框。
   主题按钮与托盘同底色同高度，两者读成同一族；且不按 checked 变色（图标本身
   已表明会切到什么主题，再加一圈强调色边框只会抢走内容注意力）。
   注意：`border-radius` 不得超过控件短边的一半（QSS 里超了 Qt 会直接不圆，
   退化成直角方块 —— 旧版 #FloatTextBtn radius 16 配 28px 高就踩了这个坑）。 */
QPushButton#ThemeToggle {{
    background: {t.SURFACE}; border: 1px solid {t.BORDER}; border-radius: 17px;
    color: {t.TEXT_DIM};
}}
QPushButton#ThemeToggle:hover {{ background: {t.SURFACE_HOVER}; color: {t.ACCENT}; border-color: {t.ACCENT}; }}
QPushButton#ThemeToggle:pressed {{ background: {t.SURFACE_ACTIVE}; }}
QWidget#FloatTray {{
    background: {t.SURFACE};
    border: 1px solid {t.BORDER};
    border-radius: 12px;
}}
QPushButton#FloatTextBtn {{
    background: transparent; border: none; border-radius: 10px;
    padding: 0px 4px; color: {t.TEXT_DIM}; font-size: 11px;
}}
QPushButton#FloatTextBtn:hover {{ background: {t.SURFACE_ACTIVE}; color: {t.TEXT}; }}
QPushButton#FloatTextBtn:pressed {{ background: {t.ACCENT_SOFT}; color: {t.ACCENT}; }}

/* 右下角版本号：极低存在感的一行小字，贴着播放栏右下角 */
QLabel#VersionLabel {{
    color: {t.TEXT_DIM}; font-size: 10px; background: transparent; padding: 0px;
}}

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
/* 设置里的字号档位下拉（v2.2）：比排序框窄一些，圆角更收敛 */
QComboBox#FontScaleCombo {{
    background: {t.SURFACE};
    border: 1px solid {t.BORDER};
    border-radius: 12px;
    padding: 4px 8px 4px 12px;
    min-width: 96px;
    font-size: 12px;
    color: {t.TEXT};
}}
QComboBox#FontScaleCombo:hover {{ border-color: {t.ACCENT_DIM}; color: {t.ACCENT}; }}
QComboBox#FontScaleCombo::drop-down {{ border: none; width: 20px; }}
QComboBox#FontScaleCombo QAbstractItemView {{ padding: 5px; border-radius: 10px; }}

/* ---------- 滑块 ---------- */
/* 3px 细轨 + 强调色圆钮 + SURFACE 色外环。
   三个必须同时满足，否则钮会退化成「圆角方块」或直接隐形：
   ① 钮芯必须是**有色实心**——白心白环在白底上完全看不见（旧版就是这样，
      用户截图里根本找不到进度手柄）；
   ② `border-radius` = (width + 2×border) / 2，取整到手柄总高的一半；
   ③ `margin` 决定手柄盒高 = 轨道高 + 2×|margin|，必须 ≥ 手柄总高，
      否则 Qt 会把圆压成方块（seek 总高 14 → margin -6；音量总高 12 → -5）。 */
QSlider::groove:horizontal {{
    height: 3px;
    background: {t.BORDER};
    border-radius: 1.5px;
}}
QSlider::sub-page:horizontal {{
    background: {t.ACCENT};
    border-radius: 1.5px;
}}
QSlider::add-page:horizontal {{
    background: {t.BORDER};
    border-radius: 1.5px;
}}
QSlider::handle:horizontal {{
    background: {t.ACCENT};
    width: 10px;
    height: 10px;
    margin: -6px 0px;
    border-radius: 7px;
    border: 2px solid {t.SURFACE};
}}
QSlider::handle:horizontal:hover {{
    background: {t.ACCENT_HOVER};
}}
/* 进度条手柄（主交互）与音量手柄（次要）尺寸分档 */
QSlider#SeekSlider::handle:horizontal {{
    width: 10px;
    height: 10px;
    margin: -6px 0px;
    border-radius: 7px;
}}
QSlider#VolumeSlider::handle:horizontal {{
    width: 8px;
    height: 8px;
    margin: -5px 0px;
    border-radius: 6px;
}}

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
/* ---------- 设置对话框分页（v2.2） ---------- */
/* pane 默认带一圈立体边框，跟本应用的扁平风格冲突，必须清掉；
   页签做成胶囊片：选中态用强调淡底 + 强调色文字，一眼看出在哪一页。 */
QTabWidget#SettingsTabs::pane {{ border: none; background: transparent; }}
QTabWidget#SettingsTabs > QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: {t.SURFACE_HOVER};
    color: {t.TEXT_DIM};
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 6px 16px;
    margin-right: 6px;
}}
QTabBar::tab:hover {{ color: {t.TEXT}; }}
QTabBar::tab:selected {{ background: {t.ACCENT_SOFT}; color: {t.ACCENT}; border-color: {t.ACCENT}; }}
"""
    if scrim:
        alpha = max(0.0, min(1.0, scrim))
        surf = _rgba(t.SURFACE, alpha)
        # 页面底色（页头/列头）比面板要透得多：BG 在深色主题里几乎是黑，
        # 用和面板同样的不透明度会变成一条突兀的黑带子压在图上面。
        veil = _rgba(t.BG, max(0.0, alpha * 0.42))
        css = css.replace(t.SURFACE, surf).replace(t.BG, veil)
        # 覆盖回不透明：①窗口根底色不能透（否则降了背景不透明度会看到桌面，
        # 而不是看到主题底色）；②对话框/菜单/输入框是独立顶层窗口，半透明会
        # 直接看到桌面内容。
        css += f"""
/* ---------- 自定义背景下的不透明兜底 ----------
   ① 窗口根底色不能透：否则把「背景不透明度」调低时，透出来的是桌面而不是
      主题底色，看着像窗口漏了；
   ② 对话框/菜单/输入框是独立顶层窗口或浮层，半透明会直接看到桌面内容。 */
QWidget#WindowRoot {{ background: {t.BG}; }}
QDialog#SettingsDialog, QDialog#QueuePanel, QMenu, QToolTip, QMessageBox,
QLineEdit, QTextEdit, QComboBox, QComboBox QAbstractItemView,
QLabel#Toast {{ background: {t.SURFACE}; }}
"""
    return _scale_font_sizes(css, font_scale)
