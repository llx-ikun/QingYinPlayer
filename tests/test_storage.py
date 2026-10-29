# -*- coding: utf-8 -*-
"""数据目录解析与迁移（v2.6）。

覆盖两件容易出事的东西：
1. **优先级**：QY_DATA_DIR > 便携模式 > 指针文件 > 默认 APPDATA。
   顺序错了会把自检数据写进用户曲库，或者让"改了位置却不生效"。
2. **迁移安全**：先复制再核对，失败/取消一律清理目标、源保持原样。
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest import mock

from app import paths, storage


class _TempAppData(unittest.TestCase):
    """每个测试一套独立 APPDATA，绝不碰到真实用户目录。"""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="qy_storage_test_")
        self._saved_appdata = os.environ.get("APPDATA")
        self._saved_env = os.environ.pop(paths.ENV_DATA_ROOT, None)
        os.environ["APPDATA"] = os.path.join(self.tmp, "roaming")
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        if self._saved_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._saved_appdata
        if self._saved_env is None:
            os.environ.pop(paths.ENV_DATA_ROOT, None)
        else:
            os.environ[paths.ENV_DATA_ROOT] = self._saved_env
        shutil.rmtree(self.tmp, ignore_errors=True)

    # 便捷方法
    def write(self, path: str, payload: bytes = b"x") -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(payload)
        return path


class TestResolveRoot(_TempAppData):
    def test_default_is_appdata(self):
        self.assertFalse(os.environ.get(paths.ENV_DATA_ROOT))
        self.assertEqual(paths.current_root(), paths.default_root())
        self.assertEqual(paths.mode(), "default")

    def test_env_wins_over_everything(self):
        # 指针指向 A、env 指向 B → 必须用 B（自检隔离就靠这条）
        pointed = os.path.join(self.tmp, "pointed")
        os.makedirs(pointed, exist_ok=True)
        paths.write_pointer(pointed)
        env_root = os.path.join(self.tmp, "envroot")
        os.environ[paths.ENV_DATA_ROOT] = env_root
        self.assertEqual(os.path.normcase(paths.current_root()),
                         os.path.normcase(env_root))
        self.assertEqual(paths.mode(), "env")

    def test_pointer_overrides_default(self):
        custom = os.path.join(self.tmp, "custom")
        os.makedirs(custom, exist_ok=True)
        paths.write_pointer(custom)
        self.assertEqual(os.path.normcase(paths.current_root()),
                         os.path.normcase(custom))
        self.assertEqual(paths.mode(), "custom")

    def test_broken_pointer_falls_back_to_default(self):
        # 指向一个不存在的目录（U 盘拔了 / 用户删了）→ 回默认，不是空目录
        paths.write_pointer(os.path.join(self.tmp, "gone"))
        self.assertEqual(paths.current_root(), paths.default_root())
        self.assertEqual(paths.mode(), "default")

    def test_empty_pointer_is_ignored(self):
        os.makedirs(paths.default_root(), exist_ok=True)
        with open(paths.pointer_file(), "w", encoding="utf-8") as f:
            f.write("   \n")
        self.assertEqual(paths.current_root(), paths.default_root())

    def test_clear_pointer_restores_default(self):
        custom = os.path.join(self.tmp, "custom")
        os.makedirs(custom, exist_ok=True)
        paths.write_pointer(custom)
        paths.clear_pointer()
        self.assertEqual(paths.current_root(), paths.default_root())
        self.assertFalse(os.path.exists(paths.pointer_file()))

    def test_clear_pointer_is_idempotent(self):
        paths.clear_pointer()          # 不存在时也不能抛
        paths.clear_pointer()


class TestPortableMode(_TempAppData):
    """便携模式只在打包后生效 —— 源码运行时必须忽略，否则测试隔离会失效。"""

    def test_source_run_ignores_portable_dir(self):
        fake_exe = os.path.join(self.tmp, "app")
        os.makedirs(os.path.join(fake_exe, paths.PORTABLE_MARKER), exist_ok=True)
        with mock.patch.object(paths, "exe_dir", return_value=fake_exe):
            # 没打补丁到 _frozen：源码态就是 False
            self.assertIsNone(paths.portable_root())
            self.assertEqual(paths.current_root(), paths.default_root())

    def test_packaged_uses_software_dir(self):
        fake_exe = os.path.join(self.tmp, "app")
        portable = os.path.join(fake_exe, paths.PORTABLE_MARKER)
        os.makedirs(portable, exist_ok=True)
        with mock.patch.object(paths, "_frozen", return_value=True), \
                mock.patch.object(paths, "exe_dir", return_value=fake_exe):
            self.assertEqual(os.path.normcase(paths.portable_root()),
                             os.path.normcase(portable))
            self.assertEqual(os.path.normcase(paths.current_root()),
                             os.path.normcase(portable))
            self.assertEqual(paths.mode(), "portable")
            self.assertTrue(paths.is_portable())

    def test_packaged_without_marker_uses_appdata(self):
        fake_exe = os.path.join(self.tmp, "app")
        os.makedirs(fake_exe, exist_ok=True)
        with mock.patch.object(paths, "_frozen", return_value=True), \
                mock.patch.object(paths, "exe_dir", return_value=fake_exe):
            self.assertIsNone(paths.portable_root())
            self.assertEqual(paths.current_root(), paths.default_root())

    def test_portable_beats_pointer(self):
        fake_exe = os.path.join(self.tmp, "app")
        portable = os.path.join(fake_exe, paths.PORTABLE_MARKER)
        os.makedirs(portable, exist_ok=True)
        pointed = os.path.join(self.tmp, "pointed")
        os.makedirs(pointed, exist_ok=True)
        paths.write_pointer(pointed)
        with mock.patch.object(paths, "_frozen", return_value=True), \
                mock.patch.object(paths, "exe_dir", return_value=fake_exe):
            self.assertEqual(os.path.normcase(paths.current_root()),
                             os.path.normcase(portable))

    def test_env_beats_portable(self):
        """自检隔离的底线：软件目录里有 data/ 也不能把 --smoke 写进去。"""
        fake_exe = os.path.join(self.tmp, "app")
        os.makedirs(os.path.join(fake_exe, paths.PORTABLE_MARKER), exist_ok=True)
        env_root = os.path.join(self.tmp, "temp_isolated")
        os.environ[paths.ENV_DATA_ROOT] = env_root
        with mock.patch.object(paths, "_frozen", return_value=True), \
                mock.patch.object(paths, "exe_dir", return_value=fake_exe):
            self.assertEqual(os.path.normcase(paths.current_root()),
                             os.path.normcase(env_root))
            self.assertEqual(paths.mode(), "env")


class TestSubdirs(_TempAppData):
    def test_all_subdirs_live_under_root(self):
        custom = os.path.join(self.tmp, "custom")
        os.makedirs(custom, exist_ok=True)
        paths.write_pointer(custom)
        for getter in (paths.covers_dir, paths.library_dir,
                       paths.lyrics_cache_dir, paths.bgs_dir):
            self.assertEqual(os.path.dirname(os.path.normcase(getter())),
                             os.path.normcase(custom))
            self.assertTrue(os.path.isdir(getter()))
        self.assertEqual(os.path.dirname(os.path.normcase(paths.data_file())),
                         os.path.normcase(custom))


class TestMigration(_TempAppData):
    def _seed(self, root: str) -> None:
        self.write(os.path.join(root, "data.json"), b"{}")
        self.write(os.path.join(root, "library", "a.mp3"), b"a" * 100)
        self.write(os.path.join(root, "library", "sub", "b.mp3"), b"b" * 50)
        self.write(os.path.join(root, "covers", "c.png"), b"c" * 10)
        self.write(os.path.join(root, "library", "stale.part"), b"p" * 999)

    def test_plan_skips_temp_files(self):
        root = os.path.join(self.tmp, "src")
        self._seed(root)
        items = storage.plan(root)
        names = {rel for _s, rel, _n in items}
        self.assertIn(os.path.join("library", "a.mp3"), names)
        self.assertIn(os.path.join("library", "sub", "b.mp3"), names)
        self.assertIn("data.json", names)
        self.assertNotIn(os.path.join("library", "stale.part"), names)

    def test_migrate_copies_everything_and_removes_source(self):
        src = os.path.join(self.tmp, "src")
        dst = os.path.join(self.tmp, "dst")
        self._seed(src)
        result = storage.migrate(src, dst)

        self.assertEqual(result["files"], 4)
        self.assertTrue(result["removed"])
        self.assertTrue(os.path.isfile(os.path.join(dst, "data.json")))
        self.assertTrue(os.path.isfile(os.path.join(dst, "library", "a.mp3")))
        self.assertTrue(os.path.isfile(os.path.join(dst, "library", "sub", "b.mp3")))
        self.assertTrue(os.path.isfile(os.path.join(dst, "covers", "c.png")))
        # 源侧业务数据已清空（.part 是残留，不在搬运范围里）
        self.assertFalse(os.path.exists(os.path.join(src, "data.json")))
        self.assertFalse(os.path.exists(os.path.join(src, "library", "a.mp3")))

    def test_migrate_keeps_source_when_not_removing(self):
        src = os.path.join(self.tmp, "src")
        dst = os.path.join(self.tmp, "dst")
        self._seed(src)
        result = storage.migrate(src, dst, remove_source=False)
        self.assertFalse(result["removed"])
        self.assertTrue(os.path.isfile(os.path.join(src, "data.json")))
        self.assertTrue(os.path.isfile(os.path.join(dst, "data.json")))

    def test_progress_reaches_total(self):
        src = os.path.join(self.tmp, "src")
        dst = os.path.join(self.tmp, "dst")
        self._seed(src)
        seen: list[tuple[int, int]] = []
        storage.migrate(src, dst, progress=lambda d, t, _n: seen.append((d, t)))
        self.assertTrue(seen)
        done, total = seen[-1]
        self.assertEqual(done, total)

    def test_cancel_cleans_target_and_keeps_source(self):
        src = os.path.join(self.tmp, "src")
        dst = os.path.join(self.tmp, "dst")
        self._seed(src)
        calls = {"n": 0}

        def should_stop() -> bool:
            calls["n"] += 1
            return calls["n"] > 1        # 复制完第一个文件就喊停

        with self.assertRaises(storage.Cancelled):
            storage.migrate(src, dst, should_stop=should_stop)

        # 源完好无损
        self.assertTrue(os.path.isfile(os.path.join(src, "data.json")))
        self.assertTrue(os.path.isfile(os.path.join(src, "library", "a.mp3")))
        # 目标里我们写过的顶层条目都被清掉
        self.assertFalse(os.path.exists(os.path.join(dst, "library")))
        self.assertFalse(os.path.exists(os.path.join(dst, "data.json")))

    def test_rejects_same_directory(self):
        src = os.path.join(self.tmp, "src")
        self._seed(src)
        with self.assertRaises(storage.MigrationError):
            storage.migrate(src, src)

    def test_rejects_nested_target(self):
        src = os.path.join(self.tmp, "src")
        self._seed(src)
        with self.assertRaises(storage.MigrationError):
            storage.migrate(src, os.path.join(src, "inner"))

    def test_rejects_non_empty_target(self):
        src = os.path.join(self.tmp, "src")
        dst = os.path.join(self.tmp, "dst")
        self._seed(src)
        self.write(os.path.join(dst, "data.json"), b"{}")
        with self.assertRaises(storage.MigrationError):
            storage.migrate(src, dst)
        # 拒绝之后源必须还在
        self.assertTrue(os.path.isfile(os.path.join(src, "data.json")))

    def test_has_data(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty, exist_ok=True)
        self.assertFalse(storage.has_data(empty))
        full = os.path.join(self.tmp, "full")
        self.write(os.path.join(full, "library", "a.mp3"))
        self.assertTrue(storage.has_data(full))

    def test_used_bytes(self):
        root = os.path.join(self.tmp, "root")
        self._seed(root)
        self.assertEqual(storage.used_bytes(root), 100 + 50 + 10 + 2 + 999)

    def test_is_writable(self):
        self.assertTrue(storage.is_writable(os.path.join(self.tmp, "ok")))


class TestSwitchRoot(_TempAppData):
    def test_switch_moves_data_and_writes_pointer(self):
        src = paths.app_data_dir()
        self.write(os.path.join(src, "data.json"), b"{}")
        self.write(os.path.join(src, "library", "a.mp3"), b"a" * 20)

        dst = os.path.join(self.tmp, "newhome")
        result = storage.switch_root(dst)

        self.assertEqual(result["files"], 2)
        self.assertEqual(paths.mode(), "custom")
        self.assertEqual(os.path.normcase(paths.current_root()), os.path.normcase(dst))
        self.assertTrue(os.path.isfile(os.path.join(dst, "library", "a.mp3")))
        with open(paths.pointer_file(), "r", encoding="utf-8") as f:
            self.assertEqual(os.path.normcase(f.read().strip()), os.path.normcase(dst))

    def test_switch_back_to_default_clears_pointer(self):
        src = paths.app_data_dir()
        self.write(os.path.join(src, "data.json"), b"{}")
        dst = os.path.join(self.tmp, "newhome")
        storage.switch_root(dst)
        self.assertEqual(paths.mode(), "custom")

        storage.switch_root(paths.default_root())
        self.assertEqual(paths.mode(), "default")
        self.assertFalse(os.path.exists(paths.pointer_file()))
        self.assertTrue(os.path.isfile(os.path.join(paths.default_root(), "data.json")))

    def test_first_run_switch_only_records_location(self):
        # 还没有任何数据时换位置：不报错、不迁移，只记住位置
        dst = os.path.join(self.tmp, "fresh")
        result = storage.switch_root(dst)
        self.assertEqual(result["files"], 0)
        self.assertTrue(os.path.isdir(dst))
        self.assertEqual(os.path.normcase(paths.current_root()), os.path.normcase(dst))
        self.assertEqual(paths.mode(), "custom")
