# -*- coding: utf-8 -*-
"""数据目录迁移（v2.6）。

用户可以在设置 → 存储里把整套数据（曲库 / 封面 / 歌词缓存 / 背景 / data.json）
换到别的盘，或者直接放进软件目录走便携模式。

**安全第一**，这套流程的每一步都可回退：

1. 目标目录必须是空目录或不存在 —— 不做任何覆盖，就不会出现"合并到一半两套数据
   搅在一起"的情况
2. 先**复制**到目标，逐个文件核对字节数
3. 全部核对通过后才删源（只在 `remove_source=True` 时）
4. 任何一步失败 / 用户取消 → 清掉目标里我们刚写过的东西，源目录一动不动

迁移是纯文件搬运，不解析 data.json：`tracks[].path` 里存的是**绝对路径**，所以
"换位置"必须把 library 一起搬过去、并保持目录结构，曲目才不会失效。
"""
from __future__ import annotations

import contextlib
import os
import shutil

from app.paths import DATA_FILE_NAME, POINTER_NAME

# 不搬运的东西：指针文件本身（它在默认目录里，指向别处）、复制残留
SKIP_NAMES = frozenset({POINTER_NAME})
SKIP_SUFFIXES = (".tmp", ".part", ".bak")


class MigrationError(Exception):
    """迁移前置校验失败或复制过程出错（消息可直接展示给用户）。"""


class Cancelled(Exception):
    """用户中途取消（目标已清理干净，源保持原样）。"""


def _skipped(name: str) -> bool:
    return name in SKIP_NAMES or name.endswith(SKIP_SUFFIXES)


def iter_entries(root: str) -> list[str]:
    """列出需要搬运的顶层条目（文件或目录），已排序保证结果稳定。"""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [n for n in names if not _skipped(n)]


def tree_bytes(path: str) -> int:
    """统计文件或目录占用的总字节数（不跟随符号链接）。"""
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            with contextlib.suppress(OSError):
                total += os.path.getsize(os.path.join(base, name))
    return total


def used_bytes(root: str) -> int:
    """整个数据目录的占用（用于设置页显示）。"""
    return sum(tree_bytes(os.path.join(root, name)) for name in iter_entries(root))


def has_data(root: str) -> bool:
    """该目录里是否已经有我们的数据（有 data.json 或有任何子目录）。"""
    return os.path.isfile(os.path.join(root, DATA_FILE_NAME)) or bool(iter_entries(root))


def is_writable(path: str) -> bool:
    """真写一次再删掉，比 os.access 可靠（只读网络盘/UAC 目录都会露馅）。"""
    probe = os.path.join(path, ".qy_write_probe")
    try:
        os.makedirs(path, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as f:
            f.write("1")
        os.remove(probe)
        return True
    except OSError:
        return False


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _is_nested(a: str, b: str) -> bool:
    """b 是否在 a 里面（含相等）。"""
    a = os.path.normcase(os.path.abspath(a)) + os.sep
    b = os.path.normcase(os.path.abspath(b)) + os.sep
    return b.startswith(a)


def check_target(src: str, dst: str) -> None:
    """迁移前置校验；不通过抛 MigrationError（消息面向用户）。"""
    if _same_path(src, dst):
        raise MigrationError("目标目录和当前数据目录是同一个。")
    if _is_nested(src, dst) or _is_nested(dst, src):
        raise MigrationError("目标目录不能位于当前数据目录内部（也不能反过来包含它）。")
    if not os.path.isdir(src):
        raise MigrationError(f"当前数据目录不存在：{src}")
    if os.path.exists(dst) and has_data(dst):
        raise MigrationError("目标目录里已经有数据了，请换一个空目录（或先清空它）。")
    if not is_writable(dst):
        raise MigrationError("目标目录不可写，请换一个位置（Program Files 下通常需要管理员权限）。")


def _copy_file(src_file: str, dst_file: str) -> None:
    os.makedirs(os.path.dirname(dst_file), exist_ok=True)
    tmp = dst_file + ".part"
    shutil.copy2(src_file, tmp)
    os.replace(tmp, dst_file)


def plan(src: str) -> list[tuple[str, str, int]]:
    """复制计划：`(源文件, 相对目标路径, 字节数)`。

    统计体积和实际复制必须用**同一份清单**，否则 `tree_bytes` 会把跳过的
    `.part`/`.bak` 也算进总量，导致迁移后的核对永远对不上。
    """
    items: list[tuple[str, str, int]] = []
    for name in iter_entries(src):
        path = os.path.join(src, name)
        if os.path.isdir(path):
            for base, _dirs, files in os.walk(path):
                inner = os.path.relpath(base, path)
                for fname in sorted(files):
                    if fname.endswith(SKIP_SUFFIXES):
                        continue
                    s_file = os.path.join(base, fname)
                    rel = (os.path.join(name, fname) if inner == "."
                           else os.path.join(name, inner, fname))
                    items.append((s_file, rel, os.path.getsize(s_file)))
        elif not name.endswith(SKIP_SUFFIXES):
            items.append((path, name, os.path.getsize(path)))
    return items


def migrate(src: str, dst: str, progress=None, should_stop=None,
            remove_source: bool = True) -> dict:
    """把 src 里的数据搬到 dst。

    progress(done, total, current) —— 每复制一个文件回调一次（字节为单位）
    should_stop() -> bool          —— 返回 True 则中止，抛 Cancelled

    返回 {"files": 文件数, "bytes": 总字节, "removed": 是否删了源}
    """
    check_target(src, dst)
    os.makedirs(dst, exist_ok=True)

    items = plan(src)
    total = sum(size for _s, _r, size in items)
    entries = iter_entries(src)

    copied_files = 0
    copied_bytes = 0
    created: list[str] = []      # 目标侧由我们创建的顶层条目，失败时清掉

    try:
        for s_file, rel, size in items:
            dst_path = os.path.join(dst, rel)
            top = os.path.join(dst, rel.split(os.sep)[0])
            if top not in created:
                created.append(top)
            if should_stop is not None and should_stop():
                raise Cancelled
            _copy_file(s_file, dst_path)
            copied_files += 1
            copied_bytes += size
            if progress is not None:
                progress(copied_bytes, total, os.path.basename(s_file))

        # 核对：目标总字节必须与计划一致，不一致就不敢删源
        got = tree_bytes_entries(dst, entries)
        if got != total:
            raise MigrationError("复制结果与源不一致（可能磁盘空间不足），已放弃且未删除原数据。")
    except Cancelled:
        _cleanup(created)
        raise
    except OSError as e:
        _cleanup(created)
        raise MigrationError(f"复制失败：{e}") from e
    except Exception:
        _cleanup(created)
        raise

    removed = False
    if remove_source:
        for name in entries:
            target = os.path.join(src, name)
            try:
                if os.path.isdir(target):
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    os.remove(target)
            except OSError:
                pass       # 删不掉不算失败：数据已经在目标里了
        removed = True

    return {"files": copied_files, "bytes": copied_bytes, "removed": removed}


def tree_bytes_entries(root: str, entries: list[str]) -> int:
    """目标侧同名条目的总字节（用于迁移后核对）。"""
    return sum(tree_bytes(os.path.join(root, n)) for n in entries)


def _cleanup(paths: list[str]) -> None:
    for path in paths:
        with contextlib.suppress(OSError):
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                os.remove(path)


def _remember_location(dst_abs: str) -> None:
    """记住新位置：目标是默认目录或便携目录时改为清指针（那两处由规则自动选中）。"""
    from app import paths

    portable_dir = os.path.join(paths.exe_dir(), paths.PORTABLE_MARKER)
    if _same_path(dst_abs, paths.default_root()) or _same_path(dst_abs, portable_dir):
        paths.clear_pointer()
    else:
        paths.write_pointer(dst_abs)


def switch_root(dst: str, remove_source: bool = True, progress=None,
                should_stop=None) -> dict:
    """把数据搬到 dst 并让它成为新的数据目录。

    写指针而不是记在 data.json 里：data.json 本身就要被搬走，用一个「只在默认
    目录里的小文件」记位置，才能在数据目录换掉之后仍然找得到它。

    还没有任何数据时（首次使用就换位置）不迁移，只记位置。
    """
    from app import paths

    src = paths.current_root()
    dst_abs = os.path.abspath(dst)
    if not os.path.isdir(src) or not iter_entries(src):
        os.makedirs(dst_abs, exist_ok=True)
        if not is_writable(dst_abs):
            raise MigrationError("目标目录不可写，请换一个位置（Program Files 下通常需要管理员权限）。")
        _remember_location(dst_abs)
        return {"files": 0, "bytes": 0, "removed": False}

    result = migrate(src, dst_abs, progress=progress, should_stop=should_stop,
                     remove_source=remove_source)
    _remember_location(dst_abs)
    return result
