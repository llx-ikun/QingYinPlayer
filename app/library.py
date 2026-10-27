# -*- coding: utf-8 -*-
"""受管理曲库：导入时把媒体文件复制进软件自己的目录（v2.1.9）。

设计要点（为什么这么做）：
- **复制而非引用**：原来只把原文件绝对路径写进 data.json，用户挪动/删除原文件后
  曲目就变成「失效」。复制进曲库后，曲目与原文件解耦，符合「导入=收进软件里」。
- **同内容去重**：用「size + 首尾 64KB」的快速指纹，而不是整文件哈希 —— 大视频
  整文件哈希太慢，而 size+两端足以区分正常媒体文件。同一内容重复导入不会多占空间。
- **同名不同内容**：追加 8 位指纹后缀，避免覆盖。
- **原子落盘**：先写 `.part` 再 `os.replace`，中途失败不会留下半个文件被当成有效曲目。
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import shutil

_CHUNK = 64 * 1024
_ILLEGAL = '<>:"/\\|?*'


def file_signature(path: str) -> str:
    """快速内容指纹：文件大小 + 首尾各 64KB 的 blake2b。"""
    size = os.path.getsize(path)
    h = hashlib.blake2b(digest_size=8)
    h.update(str(size).encode("ascii", "ignore"))
    with open(path, "rb") as f:
        h.update(f.read(_CHUNK))
        if size > _CHUNK * 2:
            f.seek(-_CHUNK, os.SEEK_END)
            h.update(f.read(_CHUNK))
    return h.hexdigest()


def safe_stem(name: str) -> str:
    """把文件名主干里的 Windows 非法字符替换掉，并去掉首尾空白/点。"""
    for ch in _ILLEGAL:
        name = name.replace(ch, "_")
    name = name.strip().strip(".")
    return name or "track"


def is_in_library(path: str, library_dir: str) -> bool:
    """path 是否位于曲库目录内（用 normcase 比较，兼容 Windows 大小写）。"""
    if not path or not library_dir:
        return False
    try:
        p = os.path.normcase(os.path.abspath(path))
        d = os.path.normcase(os.path.abspath(library_dir))
        return os.path.commonpath([p, d]) == d
    except ValueError:      # 不同盘符
        return False


def _find_sidecar_lrc(src: str) -> str | None:
    """找音频旁边的同名 .lrc（大小写不敏感：Windows 常见 .lrc / .LRC）。"""
    stem = os.path.splitext(src)[0]
    for ext in (".lrc", ".LRC", ".Lrc"):
        candidate = stem + ext
        if os.path.isfile(candidate):
            return candidate
    return None


def _copy_sidecar_lrc(src: str, dest: str) -> None:
    """把同名歌词一并带进曲库，否则副本旁边没有 .lrc，自动歌词就失效了。

    目标已存在则不覆盖（可能是用户手动换过的歌词）。
    """
    lrc = _find_sidecar_lrc(src)
    if lrc is None:
        return
    target = os.path.splitext(dest)[0] + ".lrc"
    if os.path.normcase(os.path.abspath(target)) == os.path.normcase(os.path.abspath(lrc)):
        return
    if os.path.exists(target):
        return
    tmp = target + ".part"
    try:
        shutil.copyfile(lrc, tmp)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            with contextlib.suppress(OSError):
                os.remove(tmp)


def import_into_library(src: str, library_dir: str) -> tuple[str, bool]:
    """把 `src` 复制进 `library_dir`，返回 `(目标路径, 是否真的复制了)`。

    - 目标已存在且内容一致 → 直接复用（去重，不复制）
    - 目标已存在但内容不同 → 文件名追加 8 位指纹后缀
    - 同名 .lrc 歌词一并复制（自动歌词依赖 `音频主干.lrc` 同目录）
    - 复制失败（磁盘满 / 权限）→ 抛 OSError，由调用方跳过该文件
    """
    os.makedirs(library_dir, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(src))
    stem = safe_stem(stem)
    sig = file_signature(src)
    src_abs = os.path.normcase(os.path.abspath(src))

    dest = os.path.join(library_dir, f"{stem}{ext}")
    if os.path.exists(dest):
        if os.path.normcase(os.path.abspath(dest)) == src_abs:
            return dest, False                          # 已经在曲库里
        if file_signature(dest) == sig:
            _copy_sidecar_lrc(src, dest)                # 同内容：补歌词（若有）
            return dest, False
        dest = os.path.join(library_dir, f"{stem}_{sig[:8]}{ext}")
        if os.path.exists(dest) and file_signature(dest) == sig:
            _copy_sidecar_lrc(src, dest)
            return dest, False

    tmp = dest + ".part"
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            with contextlib.suppress(OSError):
                os.remove(tmp)
    _copy_sidecar_lrc(src, dest)
    return dest, True
