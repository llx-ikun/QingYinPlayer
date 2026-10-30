# -*- coding: utf-8 -*-
"""探针：损坏数据时主窗口是否真的给出提示（v2.7.5）。

验证三件事：
  1. store.load_skipped 能拿到被跳过的条目
  2. 窗口起来后会弹 Toast，文案包含「跳过」与条数
  3. 坏数据原件被备份成 .bak

跑法（必须隔离 APPDATA / QY_DATA_DIR，否则会写进真实曲库）：
    env -u PYTHONPATH QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe \
        tools/probe_damaged_data_ui.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="qy_probe_damaged_")
    os.environ["APPDATA"] = tmp
    data_root = os.path.join(tmp, "data")
    os.environ["QY_DATA_DIR"] = data_root
    os.makedirs(data_root, exist_ok=True)

    db = os.path.join(data_root, "data.json")
    payload = {
        "version": 1,
        "tracks": {
            "a": {"id": "a", "path": "C:/m/a.mp3", "title": "歌A"},
            "b": {"id": "b", "title": "缺 path 的坏数据"},
            "c": {"id": "c", "path": "C:/m/c.mp3", "title": "歌C"},
        },
        "playlists": [
            {"id": "pl1", "name": "跑步歌单", "track_ids": ["a", "c"], "created_at": 1},
        ],
        "settings": {"volume": 0.25, "theme": "columbina", "nickname": "阿坤"},
    }
    with open(db, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication

    from ui.main_window import MainWindow

    # 必须持有 QApplication 引用：被 GC 回收后窗口随即崩掉，不能删这个变量
    app = QApplication(sys.argv[:1])  # noqa: F841
    window = MainWindow()
    window.show()

    checks: list[tuple[str, bool, str]] = []
    skipped = window.store.load_skipped
    checks.append(("load_skipped 有记录", bool(skipped), str(skipped)))
    checks.append(("存活曲目 2 首", len(window.store.all_tracks()) == 2,
                   f"{len(window.store.all_tracks())} 首"))
    checks.append(("歌单保住", len(window.store.playlists) == 1,
                   f"{len(window.store.playlists)} 个"))
    checks.append(("设置保住", abs(window.store.settings.volume - 0.25) < 1e-6,
                   f"音量 {window.store.settings.volume}"))
    checks.append(("原始文件已备份", os.path.exists(db + ".bak"), db + ".bak"))

    # _warn_load_skipped 由 1200ms 的 singleShot 触发，这里手动推进事件循环
    deadline = time.time() + 2.0
    while time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)

    text = window._toast_label.text()
    checks.append(("Toast 有文案", bool(text), repr(text)))
    checks.append(("文案说明跳过", "跳过" in text, repr(text)))
    checks.append(("Toast 可见", window._toast_label.isVisible(), ""))

    window.close()

    failed = 0
    for name, ok, detail in checks:
        print(f"  {'OK  ' if ok else 'BAD '} {name}" + (f"  ({detail})" if detail else ""))
        if not ok:
            failed += 1
    print(f"\n{len(checks) - failed}/{len(checks)} 项通过")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
