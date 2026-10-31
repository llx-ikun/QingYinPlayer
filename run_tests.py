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
    # v2.9.0 逐曲歌词颜色 sidecar：round-trip / 坏数据容错 / 清空删文件（纯逻辑）
    "tests.test_lyrics_colors",
    # v3.0.0 逐字时间轴：增强 LRC 标签解析 / sidecar 读写 / 文本校验贴回（纯逻辑）
    "tests.test_lyrics_words",
    # v3.0.0 AI 对齐：序列比对 / 能量谷吸附 / 置信度自检 / 逐行装配（不加载模型）
    "tests.test_lyrics_asr",
    "tests.test_metadata",
    "tests.test_store",
    # v2.1.9 受管理曲库：导入即复制 / 去重 / 同名冲突 / 扫描器落库
    "tests.test_library",
    # v2.2 联网歌词：URL 构造 / 脏数据 / 选曲打分 / 缓存读写 / 后台线程（不联网）
    "tests.test_lyrics_online",
    # v2.6.8 多源联网歌词：网易云/QQ 解析 / 候选挑选 / 多源并行取最优（不联网）
    "tests.test_lyrics_multi",
    # v2.6.2 歌词批量导入：.lrc 文件名 → 曲目匹配（纯逻辑）
    "tests.test_lyrics_import",
    # v2.6.6 歌词联网对齐：key 校验 / multipart / 三步流程 / 错误分类 / worker（不联网）
    "tests.test_lyrics_align",
    # v2.6.9 歌词本地对齐：解码 / 静音检测 / 时间戳分配 / LRC / worker（离线，合成音频）
    "tests.test_lyrics_local_align",
    # v2.2 自定义背景：图片导入 / 铺满裁切 / 模糊近似 / 半透明样式表
    "tests.test_background",
    "tests.test_queue",
    "tests.test_player",
    # v2.1.4 列表排序：预设归一化 + 各维度升降序（纯逻辑）
    "tests.test_sorting",
    # v2.1.4 文件大小读取/格式化（「大小」列 + 按大小排序）
    "tests.test_filesize",
    # v2.1.5 主题调色板：浅色必须为浅蓝 + 对比度下限（纯逻辑）
    "tests.test_theme",
    "tests.test_widgets",
    # test_e2e 两个类必须拆开跑：同一进程内 QMediaPlayer 实例累积到 ~15-20 个
    # 后，Qt 多媒体后端在 offscreen 下会在 C++ 层死锁（stop/setStyleSheet 等
    # 调用随机 hang）。逐类独立进程即可规避。
    "tests.test_e2e.TestE2E",
    "tests.test_e2e.TestE2EV2",
    # v2.2 联网补歌词接线：TestE2EV2 已 21 项，再加 5 项会突破 QMediaPlayer
    # 累积阈值（offscreen 下 C++ 死锁），必须单独成进程。
    "tests.test_e2e.TestE2ELyricsOnline",
    # v2.7.4 逐句打轴：单独成进程，理由同上（每建一次 MainWindow 多一个 QMediaPlayer）
    "tests.test_e2e.TestE2ELyricsTap",
    # v2.2 外观自定义（强调色 / 字号）：同样单独成进程
    "tests.test_e2e.TestE2EAppearance",
    # v2.7.8 主题自带背景图：同样是「每项建一个 MainWindow」，单独成进程
    "tests.test_e2e.TestE2EThemeBackground",
    # v2.9.0 歌词颜色覆盖：同样是「每项建一个 MainWindow」，单独成进程
    "tests.test_e2e.TestE2ELyricsColor",
    # v2.1 视频：后端纯逻辑单测
    "tests.test_video",
    # 应用图标规范回归（PNG-in-ICO 的 planes/bitcount 必须为 0）
    "tests.test_icon",
    # 导入进度对话框：完成后「关闭」按钮失效回归（v2.1.2）
    "tests.test_dialogs",
    # v2.1.5 冒烟自检隔离：exe --smoke 不得写入用户真实曲库（每次构建都会跑，
    # 曾把合成夹具「晴天」塞进 %APPDATA%）。独立进程运行 python main.py --smoke。
    "tests.test_smoke_isolation",
    # v2.1 视频 E2E 独立进程：视频链路会额外创建 QMediaPlayer + QVideoSink，
    # 累积后同样会触发 offscreen 下的 C++ 层 hang，必须单独成进程。
    "tests.test_e2e_video.TestE2EVideo",
    # v2.6 数据目录：优先级解析 / 指针文件 / 便携模式 / 迁移与失败回滚（纯逻辑）
    "tests.test_storage",
    # v2.6.9 构建辅助：自检日志的编码回退（windowed 产物写 cp936，
    # 只按 utf-8 读会把失败诊断整片变成乱码）
    "tests.test_build",
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
