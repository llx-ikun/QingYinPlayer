# -*- coding: utf-8 -*-
"""异常与崩溃日志（v2.7.5）。

为什么需要这个模块：打包是 windowed 模式，双击启动时 `sys.stdout` /
`sys.stderr` 都是 None。PySide6 遇到槽函数里没被捕获的异常不会终止进程
（实测：打印 traceback 后继续跑），但那个 traceback 无处可去 —— 直接消失。
于是「点了某个按钮没反应」在用户这边不可解释，在开发者这边没有线索。

做法：把未捕获异常、未捕获的线程异常、以及 Qt 自己的警告统一落盘到
    <数据目录>/logs/app.log
并且滚动保留最近 KEEP 份，避免日志自己把磁盘吃满。

依赖约束：本模块**不得导入 Qt**。`app.store` 会调用 `log_message`，
而 store 是「无 Qt 依赖、可单测」的纯逻辑层，导入 Qt 会破坏这条边界。
Qt 消息处理器单独放在 `install_qt()` 里延迟导入。
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
from datetime import datetime

from app import paths

LOG_NAME = "app.log"
MAX_BYTES = 1024 * 1024      # 单个日志 1MB
KEEP = 3                     # 连同当前文件共保留 3 份


def logs_dir() -> str:
    """日志目录：跟随数据目录（便携模式 / 自定义位置都能一起搬走）。"""
    return os.path.join(paths.current_root(), "logs")


def log_path() -> str:
    return os.path.join(logs_dir(), LOG_NAME)


def _rotate(path: str) -> None:
    """app.log → app.log.1 → app.log.2，最老的一份丢弃。"""
    for index in range(KEEP - 1, 0, -1):
        src = f"{path}.{index}"
        if os.path.exists(src):
            os.replace(src, f"{path}.{index + 1}")
    if os.path.exists(path):
        os.replace(path, f"{path}.1")


def log_message(message: str) -> None:
    """写一行日志。**任何失败都静默**——日志不能成为新的故障源。

    这是全项目唯一刻意「吞掉异常且不记录」的函数：如果连日志都写不进去
    （磁盘满、目录不可写），再往下报错只会把调用方一起拖挂。
    """
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n"
    try:
        directory = logs_dir()
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, LOG_NAME)
        if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES:
            _rotate(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except (OSError, ValueError):
        pass


def _format_exception(exc_type, exc, tb) -> str:
    body = "".join(traceback.format_exception(exc_type, exc, tb)).rstrip()
    return f"未捕获异常\n{body}"


def _excepthook(exc_type, exc, tb) -> None:
    """顶层未捕获异常：落盘 + 尽量照旧打印，但**不终止进程**。"""
    text = _format_exception(exc_type, exc, tb)
    log_message(text)
    if getattr(sys, "stderr", None) is not None:
        sys.__stderr__.write(text + "\n")


def _thread_excepthook(args) -> None:
    """子线程里未捕获的异常：默认会被静默丢弃，这里统一记账。"""
    if args.exc_type is SystemExit:
        return
    text = _format_exception(args.exc_type, args.exc_value, args.exc_traceback)
    log_message(f"线程 {getattr(args.thread, 'name', '?')} {text}")


def install() -> None:
    """装纯 Python 侧的钩子。可在 QApplication 创建前后任意时刻调用。

    注意：这里**不写**任何日志。日志目录跟着数据目录走，而 `--smoke` 自检
    会中途改写 APPDATA / QY_DATA_DIR 做隔离 —— 此时写一行就等于污染用户
    真实目录。启动那条分隔线交给调用方在路径确定后自己写。
    """
    sys.excepthook = _excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_excepthook


def install_qt() -> None:
    """装 Qt 消息处理器。

    捕获的是 `QThread: Destroyed while thread is still running`、
    `QObject::startTimer: ...` 这类只在控制台可见的 Qt 警告 —— 关窗时线程
    没退干净就是这么暴露的，正是我们最需要留痕的地方。
    """
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    levels = {
        QtMsgType.QtDebugMsg: "DEBUG",
        QtMsgType.QtInfoMsg: "INFO",
        QtMsgType.QtWarningMsg: "WARN",
        QtMsgType.QtCriticalMsg: "CRITICAL",
        QtMsgType.QtFatalMsg: "FATAL",
    }

    def handler(mode, context, message) -> None:
        level = levels.get(mode, "?")
        where = ""
        if context is not None and context.file:
            where = f" ({context.file}:{context.line})"
        log_message(f"Qt {level}: {message}{where}")

    qInstallMessageHandler(handler)
