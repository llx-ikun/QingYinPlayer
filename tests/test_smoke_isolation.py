# -*- coding: utf-8 -*-
"""冒烟自检必须与用户曲库隔离（回归）。

背景：`build.py` 每个产物都会跑 `exe --smoke <音频>` 验证解码。smoke 分支走的是
`MainWindow` → `LibraryStore.add_or_update()`，而 store 默认落在
`%APPDATA%\\轻音播放器\\data.json` —— 用户真实曲库。于是每次构建都往用户库里塞一条
合成夹具「晴天」，退出时还会覆盖 `last_view` / `last_track_id`；夹具被清理后这条
记录就变成失效条目（用户反复看到「晴天」又出现，就是这个原因）。

本模块用**独立进程**跑 `python main.py --smoke <夹具>`，把 APPDATA 指向临时目录并
预置一份哨兵 data.json，断言运行结束后哨兵文件**逐字节不变**。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.make_fixtures import ensure_fixtures  # noqa: E402

SENTINEL = (
    '{\n "version": 1,\n'
    ' "tracks": {},\n'
    ' "playlists": [],\n'
    ' "settings": {"volume": 0.5, "theme": "light", "nickname": "哨兵"}\n'
    '}\n'
)


class TestSmokeIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="qy_smoke_test_")
        self.appdata = os.path.join(self.tmp, "appdata")
        self.data_dir = os.path.join(self.appdata, "轻音播放器")
        os.makedirs(self.data_dir, exist_ok=True)
        self.data_file = os.path.join(self.data_dir, "data.json")
        with open(self.data_file, "w", encoding="utf-8") as f:
            f.write(SENTINEL)
        self.fixture = os.path.join(ensure_fixtures(), "晴天 - 周杰伦.mp3")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_smoke(self, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["APPDATA"] = self.appdata
        env["QT_QPA_PLATFORM"] = "offscreen"
        env.pop("PYTHONPATH", None)
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "main.py"), "--smoke", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def _assert_sentinel_intact(self) -> None:
        with open(self.data_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), SENTINEL, "smoke 不得改写用户曲库 data.json")
        extra = [n for n in os.listdir(self.data_dir) if n != "data.json"]
        self.assertEqual(extra, [], f"smoke 不得往用户数据目录写文件，多出: {extra}")

    def test_smoke_with_audio_does_not_touch_user_library(self):
        """核心回归：带音频的 smoke 会 add_or_update，必须落在隔离目录。"""
        proc = self._run_smoke(self.fixture)
        self.assertEqual(proc.returncode, 0, f"smoke 失败: {proc.stdout}\n{proc.stderr}")
        self.assertIn("smoke ok", proc.stdout)
        self._assert_sentinel_intact()

    def test_smoke_without_audio_does_not_touch_user_library(self):
        """不带音频的 smoke 也会加载并回写曲库，同样不能碰用户数据。"""
        proc = self._run_smoke()
        self.assertEqual(proc.returncode, 0, f"smoke 失败: {proc.stdout}\n{proc.stderr}")
        self.assertIn("smoke ok", proc.stdout)
        self._assert_sentinel_intact()


if __name__ == "__main__":
    unittest.main()
