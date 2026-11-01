# -*- coding: utf-8 -*-
"""逐曲「逐字时间轴」sidecar（v3.0.0，纯逻辑，无 Qt 依赖）。

每首歌一个 `<track_id>.json`：

    {"version": 1,
     "lines": {"12340": [[12340, 12560, "故"], [12560, 0, "事"]]}}

键是**行时间戳 time_ms**（与 `app/lyrics_colors.py` 同一口径，理由也一样：
行号会随歌词重导/增删句漂移，时间戳对同一份 LRC 稳定）。

值是该行每个字/词的 `[起点ms, 终点ms, 文本]` 三元组。`终点 == 0` 表示「终点未知」
（增强 LRC 的最后一段没有结尾戳，也无法从 ASR 推出），渲染时按下一个字或行尾兜底。

**为什么不一刀切用 sidecar 替代写回 .lrc**：.lrc 是通用格式，行内 `<mm:ss.xx>`
标签虽然合法（增强 LRC），但会把文件变成非标准形态、外部播放器可能显示乱码；
而重新联网取词/用户手换一份 .lrc 时，逐字数据不该跟着蒸发。

容错沿用 v2.7.5 约定：坏 JSON / 非法字段一律跳过，绝不让加载失败；空映射删文件。
"""
from __future__ import annotations

import contextlib
import json
import os

from app.lyrics import LyricLine, WordSpan
from app.paths import lyrics_words_dir

_VERSION = 1

# 防呆上限：坏文件（或恶意构造）不应该让界面卡住。
_MAX_WORDS_PER_LINE = 512
_MAX_LINES = 20000


def _safe_id(track_id) -> str:
    """track_id 正常是 md5 十六进制；兜底过滤非法字符，空值给 unknown。"""
    s = str(track_id or "").strip()
    s = "".join(c for c in s if c.isalnum() or c in "-_")
    return s or "unknown"


def _path(track_id, base_dir: str | None) -> str:
    base = base_dir or lyrics_words_dir()
    return os.path.join(base, f"{_safe_id(track_id)}.json")


def _clean_words(raw) -> tuple[WordSpan, ...]:
    """把一条 sidecar 记录净化成 `WordSpan` 元组；任何不合法就整条丢弃。

    逐字数据是「按字切分文本」的依据，错一个字的长度就会让整行对不上，所以这里
    宁可少留（返回空元组 = 该行退回线性插值），也不留半截。
    """
    if not isinstance(raw, (list, tuple)) or not raw:
        return ()
    if len(raw) > _MAX_WORDS_PER_LINE:
        return ()
    out: list[WordSpan] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            return ()
        try:
            start = int(item[0])
            end = int(item[1])
        except (TypeError, ValueError):
            return ()
        text = item[2]
        if not isinstance(text, str) or not text:
            return ()
        if start < 0:
            return ()
        # 终点缺省 / 小于起点 / 与起点相同 —— 统一记作 0（未知），别当零长度
        if end <= start:
            end = 0
        out.append(WordSpan(start, end, text))
    return tuple(out)


def load_line_words(track_id, base_dir: str | None = None) -> dict[int, tuple[WordSpan, ...]]:
    """读某首歌的逐字时间轴：`{time_ms: (WordSpan, ...)}`；缺失/损坏返回空字典。"""
    try:
        with open(_path(track_id, base_dir), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    raw = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: dict[int, tuple[WordSpan, ...]] = {}
    for key, value in list(raw.items())[:_MAX_LINES]:
        try:
            ms = int(key)
        except (TypeError, ValueError):
            continue
        words = _clean_words(value)
        if ms >= 0 and words:
            out[ms] = words
    return out


def save_line_words(track_id, mapping, base_dir: str | None = None) -> bool:
    """把整张映射写回 sidecar；空映射删除文件。写失败不抛，返回是否成功。"""
    base = base_dir or lyrics_words_dir()
    clean: dict[int, tuple[WordSpan, ...]] = {}
    for key, value in list((mapping or {}).items())[:_MAX_LINES]:
        try:
            ms = int(key)
        except (TypeError, ValueError):
            continue
        words = _clean_words([list(w) if not isinstance(w, WordSpan)
                              else [w.start_ms, w.end_ms, w.text] for w in (value or ())])
        if ms >= 0 and words:
            clean[ms] = words
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
                 "lines": {str(k): [[w.start_ms, w.end_ms, w.text] for w in clean[k]]
                           for k in sorted(clean)}},
                f, ensure_ascii=False,
            )
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def attach_words(lines: list[LyricLine],
                 mapping: dict[int, tuple[WordSpan, ...]]) -> list[LyricLine]:
    """把逐字映射按 `time_ms` 贴回歌词序列，返回**新列表**（不改入参）。

    文本校验是硬门槛：`words` 拼起来的字符串必须与该行 `text` 逐字符相等，否则
    整行丢弃、退回 v2.9.2 的线性插值。理由是一份 sidecar 可能配到被替换过的
    .lrc 上——时间戳碰巧撞上、文本却不同，硬贴会让高亮按错误的字数切片，
    表现为「扫光跑到句子中间」。

    校验失败只影响这一行，不影响其他行（沿用 v2.7.5 的逐条隔离思路）。
    """
    if not mapping:
        return list(lines or [])
    out: list[LyricLine] = []
    for line in lines or []:
        words = mapping.get(line.time_ms) if isinstance(line, LyricLine) else None
        if not words or "".join(w.text for w in words) != line.text:
            out.append(line)
            continue
        out.append(LyricLine(line.time_ms, line.text, line.translation, words))
    return out


def retime_lines(lines: list[LyricLine], min_gap_ms: int = 120) -> list[LyricLine]:
    """用对齐出的首字时间重打**行**时间轴，返回新列表（v3.0.6 接入渲染链）。

    这是「行级误差 6.04s → <0.5s」的落点：本地近似对齐只能按有声段和字数估，
    前奏一长整条时间轴就整体偏早；whisper 给出的首字时刻是实测值，直接拿来当行起点。

    三条约束：
    1. 只有拿到逐字数据的行才重打，其余行保持原时间（宁可不改）；
    2. 时间必须严格递增（间隔至少 `min_gap_ms`），否则高亮会跳来跳去；
    3. 纯内存、不写任何文件——渲染层取到歌词后调 `apply_track_words` 即自动生效，
       .lrc 与 sidecar 都不动（不构成对用户歌词文件的破坏性写回）。
    """
    out: list[LyricLine] = []
    prev = -1
    for line in lines or []:
        time_ms = line.words[0].start_ms if line.words else line.time_ms
        time_ms = max(0, time_ms)
        if prev >= 0 and time_ms < prev + min_gap_ms:
            time_ms = prev + min_gap_ms
        prev = time_ms
        out.append(LyricLine(time_ms, line.text, line.translation, line.words))
    return out


def apply_track_words(lines: list[LyricLine], track_id,
                      base_dir: str | None = None) -> list[LyricLine]:
    """`load_line_words` + `attach_words` + `retime_lines` 的组合：播放器取到歌词后调这一句即可。

    贴完逐字数据后，用每行首字的实测时刻重打行时间轴（v3.0.6）。为什么必须做：
    AI 对齐（whisper）算出的字级时刻是对的，但很多 .lrc 的行时间本身整体偏早
    （本地近似对齐 / 前奏没算对），行高亮按旧时间提前亮、逐字扫光按实测时间才动，
    两者错位几秒，表现就是「歌词对不上人声」。行轴校正纯在内存里做，不写任何文件。
    """
    return retime_lines(attach_words(lines, load_line_words(track_id, base_dir)))


def save_from_lines(track_id, lines: list[LyricLine],
                    base_dir: str | None = None) -> bool:
    """从歌词序列里抽出所有带逐字数据的行落盘（AI 对齐产物的落地入口）。"""
    mapping: dict[int, tuple[WordSpan, ...]] = {}
    for line in lines or []:
        if isinstance(line, LyricLine) and line.words:
            mapping[line.time_ms] = line.words
    return save_line_words(track_id, mapping, base_dir)


def clear_song_words(track_id, base_dir: str | None = None) -> None:
    """删掉某首歌的逐字 sidecar（重新对齐 / 换歌词时用）。"""
    save_line_words(track_id, {}, base_dir)


def clear_all_words(base_dir: str | None = None) -> int:
    """删掉**全部**逐字 sidecar，返回删除个数（设置页「清空字级数据」用）。

    逐曲清空要靠用户一首首点，换模型档位重跑一遍时根本没有可行路径，
    所以必须有这个入口。删失败的文件只是跳过，不中断 —— 剩几个残留不影响使用。
    """
    base = base_dir or lyrics_words_dir()
    removed = 0
    try:
        names = os.listdir(base)
    except OSError:
        return 0
    for name in names:
        if not name.endswith(".json"):
            continue
        with contextlib.suppress(OSError):
            os.remove(os.path.join(base, name))
            removed += 1
    return removed
