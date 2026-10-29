# -*- coding: utf-8 -*-
"""同名 .lrc 落地：把对齐产物写成「歌曲同目录同名 .lrc」。

播放器 `_resolve_lyrics` 第 2 级来源会自动识别同名 .lrc（晴天.mp3 → 晴天.lrc），
比写缓存更直观、可迁移、可手动管理。本地近似对齐（v2.6.9）复用它落盘。

说明：v2.7.0 移除了联网精确对齐（LyricTimestamps，上传音频做强制对齐、需自备 Key），
现在只有本地近似对齐，本模块只负责把结果原子写盘。
"""
from __future__ import annotations

import contextlib
import os


def sidecar_lrc_path(audio_path: str) -> str:
    """歌曲同目录同名 .lrc 的路径（去扩展名 + .lrc）。"""
    return os.path.splitext(audio_path)[0] + ".lrc"


def write_sidecar_lrc(audio_path: str, lrc: str) -> str | None:
    """把 LRC 原子写到歌曲同目录同名 .lrc，返回写入路径；失败（目录不可写等）返回 None。

    覆盖已有同名 .lrc 前由调用方确认；这里只负责原子写，不删不改其它文件。
    """
    if not audio_path or not lrc:
        return None
    path = sidecar_lrc_path(audio_path)
    tmp = path + ".part"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(lrc)
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        return None
    return path
