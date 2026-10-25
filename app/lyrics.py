# -*- coding: utf-8 -*-
"""歌词引擎：LRC 解析 + 同步索引（纯逻辑，无 Qt 依赖，便于单测）。

支持：
- 标准 LRC：`[mm:ss.xx]` 时间标签（xx 为百分秒；也兼容三位毫秒）
- 一行多个时间标签（副歌重复）
- 元数据行 `[ti:]` `[ar:]` `[al:]` `[offset:]`（offset 可正可负，单位毫秒）
- 非同步歌词（如 ID3 USLT）按纯文本展示
"""
from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass

_TIME_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_META_TAG = re.compile(r"^\[([A-Za-z]+):([^\]]*)\]$")


@dataclass
class LyricLine:
    time_ms: int
    text: str


def _tag_to_ms(minute: str, second: str, frac: str | None) -> int:
    ms = int(minute) * 60000 + int(second) * 1000
    if frac:
        if len(frac) == 1:
            ms += int(frac) * 100
        elif len(frac) == 2:
            ms += int(frac) * 10
        else:
            ms += int(frac)
    return ms


def parse_lrc(text: str) -> list[LyricLine]:
    """解析 LRC 文本，返回按时间排序的同步歌词行（忽略无时间标签的行）。"""
    lines: list[LyricLine] = []
    offset_ms = 0
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        meta = _META_TAG.match(line)
        if meta and not _TIME_TAG.match(line):
            key = meta.group(1).lower()
            if key == "offset":
                with contextlib.suppress(ValueError):
                    offset_ms = int(float(meta.group(2)))
            continue
        times: list[int] = []
        rest = line
        while True:
            m = _TIME_TAG.match(rest)
            if not m:
                break
            times.append(_tag_to_ms(m.group(1), m.group(2), m.group(3)))
            rest = rest[m.end():]
        if not times:
            continue  # 无时间标签的行由 parse_plain 处理
        content = rest.strip()
        if not content:
            continue
        for t in times:
            lines.append(LyricLine(t + offset_ms, content))
    lines.sort(key=lambda line: line.time_ms)
    return lines


def parse_plain(text: str) -> list[str]:
    """非同步歌词（如 ID3 USLT / FLAC LYRICS）按纯文本逐行返回。"""
    out = []
    for raw in (text or "").splitlines():
        s = raw.strip()
        if s:
            out.append(s)
    return out


def lyrics_from_text(text: str) -> tuple[list[LyricLine], list[str]]:
    """歌词原文分流：含时间标签走同步解析，否则按纯文本。

    返回 (同步行列表, 纯文本行列表)，两者必有且只有一个非空。
    """
    synced = parse_lrc(text)
    if synced:
        return synced, []
    return [], parse_plain(text)


def lyric_index_at(lines: list[LyricLine], position_ms: int) -> int:
    """返回 position_ms 时应高亮的歌词行下标；在第一行之前返回 -1。"""
    lo, hi, ans = 0, len(lines) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if lines[mid].time_ms <= position_ms:
            ans = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return ans


def format_time(ms: int) -> str:
    """毫秒 -> m:ss（超过 1 小时用 h:mm:ss）。"""
    if ms < 0:
        ms = 0
    total_s = ms // 1000
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
