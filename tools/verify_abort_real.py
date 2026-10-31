# -*- coding: utf-8 -*-
"""真实音频验收：批量对话框跑到一半点「关闭」，窗口最终必须真的关掉。

为什要这条验收：单元测试用的是假 worker（瞬时返回），拿不到真实场景里
「中止要等 60~90 秒、首段之前打不断」那个关键事实。v3.0.2 第一版就是因为
`wait(3000)` 超时后没有任何东西再触发关闭，窗口照样关不掉 —— 只有真跑才能发现。

跑：env -u PYTHONPATH .venv/Scripts/python.exe tools/verify_abort_real.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer                     # noqa: E402
from PySide6.QtWidgets import QApplication            # noqa: E402

from app.lyrics import lyrics_from_text                # noqa: E402
from ui.dialogs import AiBatchAlignDialog              # noqa: E402

DATA = os.path.join(os.environ["APPDATA"], "轻音播放器")
with open(os.path.join(DATA, "data.json"), encoding="utf-8") as handle:
    TRACKS = json.load(handle)["tracks"]

STARTED = time.time()


def mark(text):
    print(f"  +{time.time() - STARTED:6.1f}s  {text}", flush=True)


def resolve(track_id):
    cache = os.path.join(DATA, "lyrics_cache", track_id + ".lrc")
    if not os.path.isfile(cache):
        return []
    with open(cache, encoding="utf-8", errors="ignore") as handle:
        return lyrics_from_text(handle.read())[0]


class Spy(AiBatchAlignDialog):
    """把每个生命周期节点都打出来，否则「没关闭」只能靠猜。"""

    def _on_progress(self, tid, percent, stage):
        if getattr(self, "_last", None) != (stage, percent // 20):
            self._last = (stage, percent // 20)
            mark(f"进度 {stage} {percent}%")
        super()._on_progress(tid, percent, stage)

    def _on_failed(self, tid, message):
        mark(f"worker 失败：{message}")
        super()._on_failed(tid, message)

    def _on_done(self, tid, outcome):
        mark("worker 完成")
        super()._on_done(tid, outcome)

    def _finish(self):
        mark("_finish")
        super()._finish()

    def _retire(self):
        mark("_retire")
        super()._retire()

    def _on_worker_finished(self):
        mark("_on_worker_finished（线程真退出）")
        super()._on_worker_finished()

    def _maybe_close(self):
        self._n = getattr(self, "_n", 0) + 1
        if self._n <= 6:
            mark(f"_maybe_close #{self._n} 关窗标记={self._close_when_done} "
                 f"活线程={len(self._alive_workers())}")
        super()._maybe_close()


def main() -> int:
    app = QApplication([])
    items = [(tid, track["title"], track["path"]) for tid, track in TRACKS.items()
             if os.path.isfile(os.path.join(DATA, "lyrics_cache", tid + ".lrc"))]
    mark(f"队列 {len(items)} 首：" + "、".join(name for _t, name, _p in items))
    dialog = Spy(items, resolve, "small")

    state = {"closed": False}

    def _closed(_code):
        state["closed"] = True
        mark("QDialog 已关闭 ✅")
        app.quit()

    dialog.finished.connect(_closed)
    dialog.finished_summary.connect(lambda ok, bad: mark(f"汇总 成功{ok} 失败{bad}"))
    # 必须真显示：QDialog::closeEvent 在不可见时只 accept、不触发 finished，
    # 曾经因此误判成「关不掉」。真机上对话框是 exec() 出来的，天然可见。
    dialog.show()
    dialog.start()

    QTimer.singleShot(4000, lambda: (mark(">>> 点击「关闭」"), dialog._on_close_clicked()))
    QTimer.singleShot(6000, lambda: mark(
        f"关闭中：关闭钮可用={dialog.close_btn.isEnabled()} "
        f"文案={dialog.stage_label.text()[:20]}…"))
    QTimer.singleShot(400000, lambda: (mark("超时未关闭 ❌"), app.quit()))
    app.exec()

    alive = dialog._alive_workers()
    print(f"\n最终耗时 {time.time() - STARTED:.1f}s")
    print(f"QDialog.finished 触发 / 残留活线程: {state['closed']} / {len(alive)}")
    ok = state["closed"] and not alive
    print("判定:", "✅ 已自动关闭" if ok else "❌ 仍未关闭")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
