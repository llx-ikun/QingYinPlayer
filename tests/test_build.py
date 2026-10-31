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


class TestBundledAssets(unittest.TestCase):
    """v2.8.3：内置背景预设图（星空/云海）必须真的打进包里。

    漏了 `--add-data` 的表现极具欺骗性：开发态（仓库根能读到文件）一切正常，
    打包后才是一块空底，而且不报错 —— 只有跑 exe 的人会发现「选预设没图」。
    """

    def test_theme_images_are_bundled(self) -> None:
        args = build.data_args()
        joined = " ".join(args)
        for rel in ("theme_dark.jpg", "theme_light.jpg"):
            self.assertIn(rel, joined, f"构建参数里缺 {rel}，打包后内置背景会是一块空底")
        # 每个 --add-data 都得配一个值，且目标目录是包内 assets/
        self.assertEqual(args.count("--add-data") * 2, len(args))
        self.assertTrue(all(args[i + 1].endswith(f"{os.pathsep}assets")
                            for i, a in enumerate(args) if a == "--add-data"))

    def test_bundled_paths_match_preset_definition(self) -> None:
        """build.py 的资源清单与 ui.theme 里的内置背景预设相对路径逐字对应。"""
        from ui.theme import BACKGROUND_PRESETS

        declared = {p.image for p in BACKGROUND_PRESETS}
        self.assertEqual(declared, set(build.BUNDLED_ASSETS))

    def test_icon_is_bundled(self) -> None:
        self.assertIn(build.ICON_PATH, " ".join(build.data_args()))


class TestResourcePath(unittest.TestCase):
    """`app.paths.resource_path`：打包后必须指向 `_MEIPASS`，开发态指向仓库根。

    这是「主题2 打包后是一块空底」的根因所在 —— 用 `exe_dir()` 取资源在 onefile
    下拿到的是 `dist/`（真 exe 旁边），而资源被解压到临时目录，只有 `_MEIPASS`
    指向那里。所以这两条不能省。
    """

    def test_prefers_meipass_when_frozen(self) -> None:
        from unittest import mock

        from app import paths
        with mock.patch.object(paths.sys, "_MEIPASS", r"C:\bundle", create=True):
            self.assertEqual(paths.resource_path("assets", "theme_dark.jpg"),
                             os.path.join(r"C:\bundle", "assets", "theme_dark.jpg"))

    def test_falls_back_to_repo_root(self) -> None:
        from app import paths
        expected = os.path.join(ROOT, "assets", "theme_dark.jpg")
        self.assertEqual(paths.resource_path("assets", "theme_dark.jpg"), expected)
        self.assertTrue(os.path.isfile(expected))


class TestAiCheckCommand(unittest.TestCase):
    """`main.py --check-ai`（v3.0.0）：打包后验证「模型能不能加载」的唯一手段。

    这条命令的价值在于 windowed 产物没有 stdout，只能靠它把结论写进文件；
    所以它自己**不能崩** —— 参数给错、模型缺失都得返回正常的结果码。
    """

    def test_runs_without_model(self) -> None:
        import main as main_mod
        from unittest import mock

        with mock.patch.object(main_mod, "AI_CHECK_REPORT", os.devnull):
            code = main_mod._check_ai(["main.py", "--check-ai"])
        self.assertEqual(code, 0, "没有给模型目录时应只是跳过推理，不算失败")

    def test_missing_audio_reports_code_2(self) -> None:
        import main as main_mod
        from unittest import mock

        with mock.patch.object(main_mod, "AI_CHECK_REPORT", os.devnull):
            code = main_mod._check_ai(["main.py", "--check-ai", "", "no_such_file.mp3"])
        self.assertEqual(code, 2)

    def test_report_file_written(self) -> None:
        import tempfile

        import main as main_mod
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "r.txt")
            with mock.patch.object(main_mod, "AI_CHECK_REPORT", out):
                main_mod._check_ai(["main.py", "--check-ai"])
            self.assertTrue(os.path.isfile(out))
            with open(out, encoding="utf-8") as f:
                self.assertIn("AI 自检", f.read())


if __name__ == "__main__":
    unittest.main()
