# -*- coding: utf-8 -*-
"""构建脚本的辅助逻辑（不跑 PyInstaller，不启动任何 Qt 进程）。

重点是 `_read_logs` 的编码回退：windowed 产物（PyInstaller runw.exe）重定向到
文件时按系统代码页写，中文 Windows 上是 cp936，且**不认 PYTHONIOENCODING**
（v2.6.9 实测：设了 utf-8 还是写 GBK）。读日志若只用 utf-8，构建失败时的中文
报错会整片变成替换字符，等于把诊断信息丢掉。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build  # noqa: E402


class TestReadLogs(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="qy_build_log_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name: str, raw: bytes) -> str:
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(raw)
        return path

    def test_reads_utf8(self) -> None:
        path = self._write("a.log", "smoke ok 含音频解码\n".encode())
        self.assertEqual(build._read_logs(path), ("smoke ok 含音频解码\n",))

    def test_falls_back_to_gbk(self) -> None:
        """cp936 写出的中文必须能读回来——这是失败诊断的唯一来源。"""
        text = "smoke fail: 本地对齐解码器不可用\n"
        path = self._write("b.log", text.encode("gbk"))
        self.assertEqual(build._read_logs(path), (text,))

    def test_missing_file_yields_empty(self) -> None:
        missing = os.path.join(self.tmp, "nope.log")
        self.assertEqual(build._read_logs(missing), ("",))

    def test_multiple_paths_keep_order(self) -> None:
        a = self._write("a.log", b"out")
        b = self._write("b.log", b"err")
        self.assertEqual(build._read_logs(a, b), ("out", "err"))


if __name__ == "__main__":
    unittest.main()
