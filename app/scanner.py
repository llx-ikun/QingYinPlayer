# -*- coding: utf-8 -*-
"""文件夹/文件扫描（QThread 后台执行，不卡 UI）。

v2.1：扫描范围从纯音频扩展为「音频 + 视频」媒体文件。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QThread, Signal

from app.metadata import read_track
from app.models import MEDIA_EXTENSIONS

# 扫描时跳过的目录名
_SKIP_DIRS = {".git", "node_modules", "$RECYCLE.BIN", "System Volume Information", "__pycache__"}


def collect_media_files(paths: list[str]) -> list[str]:
    """把传入的文件夹/文件展开为去重后的媒体文件列表（保持稳定排序）。

    音频与视频一视同仁：能否解码由播放引擎决定，导入阶段不做过滤。
    """
    found: set[str] = set()
    for p in paths:
        if not p:
            continue
        if os.path.isfile(p):
            if p.lower().endswith(MEDIA_EXTENSIONS):
                found.add(os.path.abspath(p))
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
            for name in files:
                if name.lower().endswith(MEDIA_EXTENSIONS):
                    found.add(os.path.abspath(os.path.join(root, name)))
    return sorted(found)


# 兼容旧名（v1.0 起的公开入口，测试与外部脚本仍在用）
collect_audio_files = collect_media_files


class ScannerWorker(QThread):
    """后台扫描 + 读取元数据，逐首发信号供 UI 增量更新。"""

    progress = Signal(int, int)        # 已完成数, 总数
    scanning = Signal(str)             # 当前文件路径
    track_ready = Signal(object)       # TrackMeta
    finished_ok = Signal(int)          # 处理总数
    cancelled = Signal()

    def __init__(self, paths: list[str], parent=None):
        super().__init__(parent)
        self._paths = list(paths)

    def run(self) -> None:
        files = collect_media_files(self._paths)
        total = len(files)
        for done, path in enumerate(files, 1):
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.scanning.emit(path)
            meta = read_track(path)
            if meta is not None:
                self.track_ready.emit(meta)
            self.progress.emit(done, total)
        self.finished_ok.emit(total)

    def cancel(self) -> None:
        self.requestInterruption()
