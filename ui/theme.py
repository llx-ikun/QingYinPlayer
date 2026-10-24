# -*- coding: utf-8 -*-
"""深色主题：调色板 + QSS 样式表。"""
from __future__ import annotations

# ---------- 调色板 ----------
BG = "#0f0f14"            # 窗口底
SURFACE = "#16161f"       # 面板
SURFACE_HOVER = "#1e1e2a" # 悬浮
SURFACE_ACTIVE = "#262633"# 选中
BORDER = "#2a2a38"
TEXT = "#f0f0f4"
TEXT_DIM = "#8f8fa3"
ACCENT = "#6c8cff"        # 强调色（蓝紫）
ACCENT_HOVER = "#829fff"
ACCENT_DIM = "#3d4f8f"
DANGER = "#ff6b6b"

FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", sans-serif'


def build_stylesheet() -> str:
    return f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: 13px;
    color: {TEXT};
    outline: none;
}}

QMainWindow, QDialog {{ background: {BG}; }}
QWidget#Sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QWidget#Panel, QWidget#HeaderBar {{ background: {BG}; }}

/* ---------- 标签 ---------- */
QLabel {{ background: transparent; }}
QLabel#Dim {{ color: {TEXT_DIM}; }}
QLabel#Title {{ font-size: 15px; font-weight: bold; }}
QLabel#Logo {{ font-size: 17px; font-weight: bold; color: {TEXT}; }}
QLabel#TrackTitle {{ font-size: 13px; font-weight: bold; color: {TEXT}; }}
QLabel#TrackSub {{ color: {TEXT_DIM}; font-size: 12px; }}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px 10px;
    color: {TEXT};
}}
QPushButton:hover {{ background: {SURFACE_HOVER}; }}
QPushButton:pressed {{ background: {SURFACE_ACTIVE}; }}
QPushButton:disabled {{ color: #555566; }}
QPushButton#Primary {{
    background: {ACCENT};
    color: #ffffff;
    font-weight: bold;
    border-radius: 10px;
    padding: 8px 16px;
}}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Primary:pressed {{ background: {ACCENT_DIM}; }}
QPushButton#Ghost {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QPushButton#Ghost:hover {{ background: {SURFACE_HOVER}; }}

/* 侧边栏导航项 */
QPushButton#NavItem {{
    text-align: left;
    padding: 9px 12px;
    border-radius: 10px;
    color: {TEXT_DIM};
    font-size: 13px;
}}
QPushButton#NavItem:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}
QPushButton#NavItem[active="true"] {{
    background: {SURFACE_ACTIVE};
    color: {TEXT};
    font-weight: bold;
}}

/* 播放控制圆形按钮 */
QPushButton#PlayCircle {{
    background: {ACCENT};
    border-radius: 22px;
    min-width: 44px; max-width: 44px;
    min-height: 44px; max-height: 44px;
}}
QPushButton#PlayCircle:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#PlayCircle:pressed {{ background: {ACCENT_DIM}; }}
QPushButton#ControlBtn {{
    border-radius: 17px;
    min-width: 34px; max-width: 34px;
    min-height: 34px; max-height: 34px;
    color: {TEXT_DIM};
}}
QPushButton#ControlBtn:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}
QPushButton#ControlBtn[active="true"] {{ color: {ACCENT}; }}

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
QListWidget::item:hover {{ background: {SURFACE_HOVER}; }}
QListWidget::item:selected {{ background: {SURFACE_ACTIVE}; }}
QListWidget::item:selected:active {{ background: {SURFACE_ACTIVE}; }}

/* ---------- 输入框 ---------- */
QLineEdit, QTextEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QTextEdit:focus {{ border: 1px solid {ACCENT_DIM}; }}

/* ---------- 下拉框 ---------- */
QComboBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px 10px;
    min-width: 70px;
}}
QComboBox:hover {{ border: 1px solid {ACCENT_DIM}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    selection-background-color: {SURFACE_ACTIVE};
    padding: 4px;
}}

/* ---------- 滑块 ---------- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {BORDER};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::add-page:horizontal {{
    background: {BORDER};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: #ffffff;
    width: 12px;
    height: 12px;
    margin: -4px 0px;
    border-radius: 6px;
}}
QSlider::handle:horizontal:hover {{ background: {ACCENT_HOVER}; }}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #3a3a4c; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::up-arrow, QScrollBar::down-arrow {{
    background: none; border: none; height: 0;
}}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 30px; }}

/* ---------- 菜单 / 提示 / 状态栏 ---------- */
QMenu {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px 7px 14px;
    border-radius: 6px;
}}
QMenu::item:selected {{ background: {SURFACE_ACTIVE}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}
QToolTip {{
    background: {SURFACE_ACTIVE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
}}
QStatusBar {{ background: transparent; color: {TEXT_DIM}; min-height: 22px; }}
QStatusBar::item {{ border: none; }}
QMessageBox {{ background: {SURFACE}; }}

/* ---------- 对话框专用 ---------- */
QDialog {{ background: {SURFACE}; }}
"""
