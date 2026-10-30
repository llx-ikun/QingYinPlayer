# -*- coding: utf-8 -*-
"""构建脚本的辅助逻辑（不跑 PyInstaller，不启动任何 Qt 进程）。

重点是 `_read_logs` 的编码回退：windowed 产物（PyInstaller runw.exe）重定向到
文件时按系统代码页写，中文 Windows 上是 cp936，且**不认 PYTHONIOENCODING**
（v2.6.9 实测：设了 utf-8 还是写 GBK）。读日志若只用 utf-8，构建失败时的中文
报错会整片变成替换字符，等于把诊断信息丢掉。
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build  # noqa: E402
from app import version as app_version  # noqa: E402


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


class TestVersionSingleSource(unittest.TestCase):
    """v2.7.6：版本号只允许有一个来源。

    事故：界面右下角写死 "v2.6.12 · 本地音乐与视频"，「关于」写死 "v2.2"，
    两个都不跟随 APP_VERSION。用户明明跑的是 v2.7.5，界面显示 2.6.12，
    直接导致一轮排查方向完全跑偏。这组用例锁死三件事：
      1. 展示串由 app.version 生成
      2. 源码里不许再出现硬编码的版本字面量
      3. main.py 必须从 app.version 取，不自己定义
    """

    # 形如 "v2.6.12 ..." / "v2.2 ..." 的字符串字面量：以 v+数字开头，后接分隔符
    _LITERAL = re.compile(r"^v\d+\.\d+")

    def test_version_text_contains_current_version(self) -> None:
        text = app_version.version_text()
        self.assertIn(app_version.APP_VERSION, text)
        self.assertTrue(text.startswith("v"))

    def test_version_text_accepts_custom_tagline(self) -> None:
        self.assertEqual(app_version.version_text("自定义"), f"v{app_version.APP_VERSION} · 自定义")
        self.assertEqual(app_version.version_text(""), f"v{app_version.APP_VERSION}")

    def test_no_hardcoded_version_literal_in_source(self) -> None:
        """ui/ 与 app/ 里不许再写死版本串（version.py 自己除外）。"""
        import ast

        offenders: list[str] = []
        for sub in ("app", "ui"):
            for name in sorted(os.listdir(os.path.join(ROOT, sub))):
                if not name.endswith(".py") or name == "version.py":
                    continue
                path = os.path.join(ROOT, sub, name)
                with open(path, encoding="utf-8") as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                        continue
                    if self._LITERAL.match(node.value.strip()):
                        offenders.append(f"{sub}/{name}:{node.lineno} {node.value[:40]!r}")
        self.assertEqual(
            offenders, [],
            "发现硬编码版本号，应改用 app.version.version_text()：\n" + "\n".join(offenders),
        )

    def test_main_takes_version_from_app_version(self) -> None:
        """main.py 不许自己定义 APP_VERSION，必须转发 app.version 的。"""
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
            source = f.read()
        self.assertIn("from app.version import", source)
        self.assertNotRegex(source, r"(?m)^APP_VERSION\s*=")


if __name__ == "__main__":
    unittest.main()
