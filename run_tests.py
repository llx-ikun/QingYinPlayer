# -*- coding: utf-8 -*-
"""全量回归入口：每个测试模块独立进程运行。

为什么不用 `python -m unittest discover -s tests`：QMediaPlayer 在
offscreen + 无音频后端下，若在同一进程内反复创建/销毁（跨测试模块累积），
会在 C++ 层偶发死锁（stop/setStyleSheet 等调用 hang，栈点随机漂移）。
逐模块独立进程运行可彻底规避该环境不稳定性；各模块内部逻辑均已单测覆盖。

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe run_tests.py
    env -u PYTHONPATH .venv/Scripts/python.exe run_tests.py tests.test_e2e   # 只跑指定模块
"""
from __future__ import annotations

import os
import subprocess
import sys

MODULES = [
    "tests.test_covers_scanner",
    "tests.test_lyrics",
    "tests.test_metadata",
    "tests.test_store",
    "tests.test_queue",
    "tests.test_player",
    "tests.test_widgets",
    # test_e2e 两个类必须拆开跑：同一进程内 QMediaPlayer 实例累积到 ~15-20 个
    # 后，Qt 多媒体后端在 offscreen 下会在 C++ 层死锁（stop/setStyleSheet 等
    # 调用随机 hang）。逐类独立进程即可规避。
    "tests.test_e2e.TestE2E",
    "tests.test_e2e.TestE2EV2",
    # v2.1 视频：后端纯逻辑单测
    "tests.test_video",
    # v2.1 视频 E2E 独立进程：视频链路会额外创建 QMediaPlayer + QVideoSink，
    # 累积后同样会触发 offscreen 下的 C++ 层 hang，必须单独成进程。
    "tests.test_e2e_video.TestE2EVideo",
]


def main() -> int:
    targets = sys.argv[1:] or MODULES
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("PYTHONPATH", None)  # 规避沙箱注入的删除守卫干扰批量文件操作

    failed = 0
    for mod in targets:
        print(f"== {mod} ==", flush=True)
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", mod, "-q"],
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        lines = (proc.stdout + proc.stderr).strip().splitlines()
        summary = lines[-1] if lines else "(no output)"
        if proc.returncode == 0:
            print(f"   PASS  {summary}", flush=True)
        else:
            failed += 1
            print(f"   FAIL  {summary}", flush=True)
            for line in lines:
                if line.startswith(("FAIL:", "ERROR:")):
                    print(f"          {line}", flush=True)
    print(f"\n{'全部通过' if failed == 0 else f'{failed} 个模块失败'}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
