# -*- coding: utf-8 -*-
"""崩溃日志（v2.7.5 实现，v3.0.4 补测）：纯逻辑，不依赖 Qt。

为什么单独成模块：`crashlog` 是全项目**唯一刻意「吞异常且不记录」**的地方，
它写不进去时不能让程序再挂一次；而它写不进去时开发者就没有任何线索。
原来只有 `test_store` 间接碰到（加载坏数据时写日志），轮转 / 钩子安装 /
写失败静默这三件事都没钉住。这里逐条锁死。
"""
import os
import shutil
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import crashlog


class _Isolated(unittest.TestCase):
    """隔离数据根：logs_dir 跟随 QY_DATA_DIR，别污染真实目录（crashlog 不缓存路径）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_crash_")
        self._old_env = os.environ.get("QY_DATA_DIR")
        os.environ["QY_DATA_DIR"] = self.tmp
        self._old_hook = sys.excepthook
        self._old_thread_hook = getattr(threading, "excepthook", None)

    def tearDown(self):
        sys.excepthook = self._old_hook
        if self._old_thread_hook is not None:
            threading.excepthook = self._old_thread_hook
        if self._old_env is None:
            os.environ.pop("QY_DATA_DIR", None)
        else:
            os.environ["QY_DATA_DIR"] = self._old_env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _read_log(self) -> str:
        with open(crashlog.log_path(), encoding="utf-8") as f:
            return f.read()


class TestLogMessage(_Isolated):
    def test_writes_line_with_timestamp(self):
        crashlog.log_message("hello world")
        text = self._read_log()
        self.assertIn("hello world", text)
        self.assertRegex(text, r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]")

    def test_appends_not_overwrites(self):
        crashlog.log_message("first")
        crashlog.log_message("second")
        text = self._read_log()
        self.assertIn("first", text)
        self.assertIn("second", text)

    def test_silent_when_directory_unwritable(self):
        """日志不能成为新的故障源：写不进去也必须静默，绝不向上抛。"""
        with mock.patch.object(crashlog.os, "makedirs", side_effect=OSError("磁盘已满")):
            crashlog.log_message("boom")            # 不抛即通过

    def test_rotates_when_exceeding_max_bytes(self):
        with mock.patch.object(crashlog, "MAX_BYTES", 50):
            crashlog.log_message("x" * 60)          # 先写满超过阈值
            crashlog.log_message("newline")
        self.assertTrue(os.path.exists(crashlog.log_path() + ".1"), "超限应把旧日志轮转")
        self.assertIn("newline", self._read_log(), "当前日志只留最新一行")
        with open(crashlog.log_path() + ".1", encoding="utf-8") as f:
            self.assertIn("xxxxxxxxxx", f.read())

    def test_rotation_keeps_at_most_keep_files(self):
        """多次轮转后，连当前文件在内最多保留 KEEP 份，不能无限增长。"""
        with mock.patch.object(crashlog, "MAX_BYTES", 20):
            for i in range(10):
                crashlog.log_message(f"line-{i}-padding-padding")
        files = [n for n in os.listdir(crashlog.logs_dir()) if n.startswith(crashlog.LOG_NAME)]
        self.assertLessEqual(len(files), crashlog.KEEP,
                             f"轮转后不该超过 {crashlog.KEEP} 份：{sorted(files)}")


class TestHooks(_Isolated):
    def test_install_sets_both_hooks(self):
        crashlog.install()
        self.assertIs(sys.excepthook, crashlog._excepthook)
        self.assertIs(threading.excepthook, crashlog._thread_excepthook)

    def test_excepthook_logs_traceback(self):
        try:
            raise ValueError("bad-thing")
        except ValueError:
            info = sys.exc_info()
        with mock.patch.object(sys, "stderr", None):     # 静默控制台噪音
            crashlog._excepthook(*info)
        text = self._read_log()
        self.assertIn("未捕获异常", text)
        self.assertIn("bad-thing", text)

    def test_thread_excepthook_ignores_system_exit(self):
        args = types.SimpleNamespace(exc_type=SystemExit, exc_value=SystemExit(),
                                     exc_traceback=None, thread=None)
        crashlog._thread_excepthook(args)
        self.assertFalse(os.path.exists(crashlog.log_path()), "SystemExit 不该记账")

    def test_thread_excepthook_logs_other(self):
        try:
            raise RuntimeError("thread-boom")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()
        args = types.SimpleNamespace(exc_type=exc_type, exc_value=exc_value,
                                     exc_traceback=exc_tb,
                                     thread=types.SimpleNamespace(name="worker-1"))
        crashlog._thread_excepthook(args)
        text = self._read_log()
        self.assertIn("worker-1", text)
        self.assertIn("thread-boom", text)

    def test_install_qt_is_callable(self):
        """install_qt 延迟导入 Qt；有 PySide6 时装上再还原，不污染后续测试。"""
        try:
            from PySide6.QtCore import qInstallMessageHandler
        except Exception:  # noqa: BLE001
            self.skipTest("无 PySide6")
        try:
            crashlog.install_qt()
        finally:
            qInstallMessageHandler(None)


if __name__ == "__main__":
    unittest.main()
