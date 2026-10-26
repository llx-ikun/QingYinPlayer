# -*- coding: utf-8 -*-
"""文件大小读取与人性化格式化（列表「大小」列 + 按大小排序共用）。

- file_size：取不到时返回 0（文件被删/权限不足/路径为空），调用方按「未知」处理；
- format_size：1024 进制，KB/MB/GB 一位小数，≥100 时取整，0 -> "--"。

不放进 app/models.py：Track 是纯数据类，读写文件系统属于独立职责，
且这里不做任何缓存——单次 os.stat 是微秒级，加缓存反而引入失效问题。
"""
from __future__ import annotations

import os

_UNITS = ("B", "KB", "MB", "GB", "TB")


def file_size(path: str) -> int:
    """返回文件字节数；路径为空或不可读时返回 0。"""
    if not path:
        return 0
    try:
        return os.path.getsize(path)
    except OSError:
        # 文件丢失/权限不足：不抛异常，交给 UI 显示「--」
        return 0


def format_size(size: int) -> str:
    """字节 -> 人类可读文本（`8.4 MB` / `820 KB` / `--`）。"""
    if size <= 0:
        return "--"
    value = float(size)
    for unit in _UNITS:
        if value < 1024 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{int(value)} B"
            # 三位数时小数位没意义，取整更整齐
            return f"{value:.1f} {unit}" if value < 100 else f"{value:.0f} {unit}"
        value /= 1024
    return "--"  # pragma: no cover - 循环必定 return
