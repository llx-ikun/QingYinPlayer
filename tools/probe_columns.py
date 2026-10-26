# -*- coding: utf-8 -*-
"""开发工具：量化校验列头与数据行的逐列对齐（真实平台，非 offscreen）。

用法：env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_columns.py
输出每一列的「列头起点 X」与「行控件起点 X」，差值应为 0（对齐）。
"""
from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def main() -> int:
    appdata = tempfile.mkdtemp(prefix="qy_probe_")
    os.environ["APPDATA"] = appdata

    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])

    from app.metadata import read_track
    from app.paths import data_file
    from app.store import LibraryStore
    from tests.make_fixtures import ensure_fixtures

    store = LibraryStore(data_file())
    music_dir = ensure_fixtures()
    for name in ("晴天 - 周杰伦.mp3", "夜曲.flac", "晨间轻音乐.wav", "海浪的声音.ogg"):
        path = os.path.join(music_dir, name)
        if os.path.isfile(path):
            store.add_or_update(read_track(path), path)
    store.save()

    from ui.main_window import MainWindow
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    for _ in range(30):
        app.processEvents()

    tl = window.track_list
    row = tl.list.itemWidget(tl.list.item(0))
    head = tl._col_header_layout

    # 列头槽位顺序（与 TrackItemWidget 一致）：lead cover 歌曲 艺人 专辑 格式 大小 时长 ♥ ⋯
    head_widgets = []
    for i in range(head.count()):
        item = head.itemAt(i)
        w = item.widget() if item is not None else None
        head_widgets.append(w)
    row_widgets = [row.leading, row.cover, row.title, row.artist, row.album,
                   row.fmt, row.size, row.duration, row.fav_btn, row.more_btn]
    names = ["序号槽", "封面槽", "歌曲", "艺人", "专辑", "格式", "大小", "时长", "爱心", "更多"]

    print(f"{'列':<8}{'列头X':>8}{'行X':>8}{'Δ':>6}  备注")
    bad = 0
    for name, hw, rw in zip(names, head_widgets, row_widgets, strict=False):
        if hw is None or rw is None:
            print(f"{name:<8}  (缺控件)")
            bad += 1
            continue
        # 必须比全局坐标：列头在 TrackList 内，行控件在 item 内且 item 还有 margin，
        # 各自相对自身原点比较会把 item margin 漏算 8px。
        hx = hw.mapToGlobal(hw.rect().topLeft()).x()
        rx = rw.mapToGlobal(rw.rect().topLeft()).x()
        delta = hx - rx
        flag = "" if abs(delta) <= 1 else "  <== 错位"
        if abs(delta) > 1:
            bad += 1
        print(f"{name:<8}{hx:>8}{rx:>8}{delta:>6}{flag}")

    print(f"\n列头左内缩={head.contentsMargins().left()} 右内缩={head.contentsMargins().right()}"
          f" 行内缩={row.layout().contentsMargins().left()}/{row.layout().contentsMargins().right()}")
    print(f"控件宽度: TrackList={tl.width()} 列头={tl._column_header.width()}"
          f" 列表={tl.list.width()} 视口={tl.list.viewport().width()} 行={row.width()}")
    print(f"滚动条可见={tl.list.verticalScrollBar().isVisible()} 宽={tl.list.verticalScrollBar().width()}")
    print(f"弹性总宽: 列头={sum(h.width() for h in head_widgets[2:5])}"
          f" 行={sum(r.width() for r in row_widgets[2:5])}")
    print("对齐：", "全部通过" if bad == 0 else f"{bad} 列错位")
    window.close()
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
