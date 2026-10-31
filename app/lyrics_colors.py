# -*- coding: utf-8 -*-
"""逐曲「歌词自定义颜色」sidecar（v2.9.0，纯逻辑，无 Qt 依赖）。

每首歌一个 `<track_id>.json`：

    {"version": 1, "lines": {"12340": "#ff6b9d", "45000": "#7f7bff"}}

为什么键用「行时间戳 time_ms」而不是行号：
- 行号在歌词被重新导入 / 增删句后会整体漂移，颜色全错位；
- 时间戳对同一份 LRC 稳定；换歌词文件时可能对不上，用「清除本曲颜色」兜底。

所有读写都做容错：坏 JSON / 非法色值一律跳过，绝不让加载流程失败（沿用 v2.7.5 的
容错约定）。空映射会删掉文件，避免数据目录里积一堆 `{}`。
"""
from __future__ import annotations

import contextlib
import json
import os

from app.models import normalize_color
from app.paths import lyrics_colors_dir

_VERSION = 1


def _safe_id(track_id) -> str:
    """track_id 正常是 md5 十六进制；兜底过滤非法字符，空值给 unknown。"""
    s = str(track_id or "").strip()
    s = "".join(c for c in s if c.isalnum() or c in "-_")
    return s or "unknown"


def _path(track_id, base_dir: str | None) -> str:
    base = base_dir or lyrics_colors_dir()
    return os.path.join(base, f"{_safe_id(track_id)}.json")


def load_line_colors(track_id, base_dir: str | None = None) -> dict[int, str]:
    """读某首歌的逐句颜色：`{time_ms: '#rrggbb'}`；文件缺失/损坏返回空字典。"""
    try:
        with open(_path(track_id, base_dir), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    raw = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: dict[int, str] = {}
    for key, value in raw.items():
        try:
            ms = int(key)
        except (TypeError, ValueError):
            continue
        color = normalize_color(value, "")
        if ms >= 0 and color:
            out[ms] = color
    return out


def save_line_colors(track_id, mapping, base_dir: str | None = None) -> bool:
    """把整张映射写回 sidecar；空映射删除文件。写失败不抛，返回是否成功。"""
    base = base_dir or lyrics_colors_dir()
    clean: dict[int, str] = {}
    for key, value in (mapping or {}).items():
        try:
            ms = int(key)
        except (TypeError, ValueError):
            continue
        color = normalize_color(value, "")
        if ms >= 0 and color:
            clean[ms] = color
    path = _path(track_id, base)
    if not clean:
        with contextlib.suppress(OSError):
            os.remove(path)
        return True
    try:
        os.makedirs(base, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {"version": _VERSION,
                 "lines": {str(k): v for k, v in sorted(clean.items())}},
                f, ensure_ascii=False,
            )
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def set_line_color(track_id, time_ms: int, color: str,
                   base_dir: str | None = None) -> dict[int, str]:
    """设置/清除某一句的颜色（color 为空即清除），返回更新后的整张映射。"""
    mapping = load_line_colors(track_id, base_dir)
    try:
        ms = int(time_ms)
    except (TypeError, ValueError):
        return mapping
    value = normalize_color(color, "")
    if value:
        mapping[ms] = value
    else:
        mapping.pop(ms, None)
    save_line_colors(track_id, mapping, base_dir)
    return mapping


def clear_line_color(track_id, time_ms: int,
                     base_dir: str | None = None) -> dict[int, str]:
    return set_line_color(track_id, time_ms, "", base_dir)


def clear_song_colors(track_id, base_dir: str | None = None) -> None:
    save_line_colors(track_id, {}, base_dir)
