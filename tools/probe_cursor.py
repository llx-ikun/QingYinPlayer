"""探针：验证应用级事件过滤器是否会抹掉控件自己设的光标形状。

背景：main_window.eventFilter 在**每次** MouseMove 上，对指针下的控件调用
setCursor(边缘缩放箭头) 或 unsetCursor()。后者会清掉控件在 __init__ 里设的
PointingHandCursor（小手），导致全应用的小手光标全部失效。

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_cursor.py
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_tmp = tempfile.mkdtemp(prefix="qy_probe_cursor_")
os.environ["APPDATA"] = _tmp
os.environ["QY_DATA_DIR"] = os.path.join(_tmp, "data")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _move(widget, pos: QPoint) -> None:
    """给 widget 投递一个 MouseMove 事件（会经过应用级过滤器）。"""
    ev = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(pos),
        QPointF(widget.mapToGlobal(pos)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, ev)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    from ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1185, 760)
    win.show()
    app.processEvents()

    targets = {
        "播放/暂停按钮": win.player_bar.play_btn,
        "上一首按钮": win.player_bar.prev_btn,
        "歌单按钮": win.player_bar.queue_btn,
        "侧栏导航按钮": win.sidebar.recent_btn,
        "窗口根容器": win._root,
    }

    print("=" * 62)
    print("光标形状检查：期望 values = 2 (PointingHandCursor)")
    print("=" * 62)
    ok = True
    for name, w in targets.items():
        expected = w.cursor().shape()
        has_own = w.testAttribute(Qt.WidgetAttribute.WA_SetCursor)
        # 在控件内部（远离窗口边缘）移动一下
        center = QPoint(w.width() // 2, w.height() // 2)
        _move(w, center)
        after = w.cursor().shape()
        after_own = w.testAttribute(Qt.WidgetAttribute.WA_SetCursor)
        mark = "OK " if after == expected else "BAD"
        if after != expected:
            ok = False
        print(
            f"[{mark}] {name:<12} 移动前={_name(expected)}(own={has_own}) "
            f"移动后={_name(after)}(own={after_own})"
        )

    # 第二条：边缘强制光标是否会残留在别的控件上
    print("-" * 62)
    edge_ok = True
    btn = win.player_bar.play_btn
    edge_local = QPoint(1, win._root.height() // 2)
    ev = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(btn.rect().center()),
        QPointF(win._root.mapToGlobal(edge_local)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(btn, ev)
    forced = win._cursor_widget
    shape = forced.cursor().shape() if forced is not None else None
    print(f"[..] 贴左边缘后强制光标落在 {type(forced).__name__ if forced else None} -> {_name(shape)}")
    # 再移到窗口中间，看是否恢复
    _move(btn, QPoint(btn.width() // 2, btn.height() // 2))
    restored = btn.cursor().shape()
    leaked = win._cursor_widget
    got = restored == Qt.CursorShape.PointingHandCursor and leaked is None
    line = f"[{'OK ' if got else 'BAD'}] 移回中间 -> {_name(restored)}（期望 PointingHandCursor）"
    print(line)
    print(f"     残留强制光标：{type(leaked).__name__ if leaked is not None else 'None（已还原）'}")
    if not got:
        edge_ok = False

    win.player.stop() if hasattr(win, "player") else None
    win.close()
    print("=" * 62)
    print("结论：控件自身光标被抹掉" if not ok else "结论：控件自身光标正常")
    print("结论：边缘光标能正确恢复" if edge_ok else "结论：边缘光标会残留/丢失")
    return 0 if (ok and edge_ok) else 1


def _name(shape) -> str:
    try:
        return f"{shape.name}@{int(shape)}"
    except Exception:  # pragma: no cover
        return str(shape)


if __name__ == "__main__":
    raise SystemExit(main())
