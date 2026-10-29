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
from itertools import pairwise

_TIME_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_META_TAG = re.compile(r"^\[([A-Za-z]+):([^\]]*)\]$")


@dataclass
class LyricLine:
    time_ms: int
    text: str
    # 译文（双语歌词）。一句 = 原文 text + 可选译文 translation；渲染成同一条目里的
    # 两行，对齐/高亮/滚动/动效都按「句」为单位，所以译文不能自己占一行。
    translation: str = ""


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
        lines.extend(LyricLine(t + offset_ms, content) for t in times)
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


# 纯文本歌词里的元数据行标签（后跟冒号，如「作词 : 音融三喜」）。
# 浏览器下载的 .txt 歌词常在开头带一段 歌名 + 作词/作曲/编曲 的元数据，
# 识别时应剔除，否则会把「作词 : xxx」当歌词行显示。
_PLAIN_META_LABEL = re.compile(
    r"^\s*(?:作词|作曲|编曲|填词|词曲|作词者|作曲者|编曲者|演唱|演唱者|歌手|主唱|"
    r"混音|混音师|制作|制作人|监制|录音|和声|和音|吉他|贝斯|鼓|键盘|弦乐|钢琴|"
    r"出品|出品人|发行|发行方|企划|统筹|旁白)\s*[:：]"
)


def _next_is_meta(lines: list[str], start: int) -> bool:
    """从 start 起找第一个非空行，判断它是不是元数据行（「作词 : xxx」这种）。"""
    for j in range(start, len(lines)):
        line = lines[j].strip()
        if not line:
            continue
        return bool(_PLAIN_META_LABEL.match(line))
    return False


def strip_meta_lines(text: str) -> str:
    """剔除纯文本歌词开头的元数据块（歌名 + 作词/作曲/编曲等）。

    浏览器下载的 .txt 歌词常见：
        唯有追赶风的方向 (Only By Chasing the)
        作词 : 音融三喜
        作曲 : 音融三喜
        编曲 : 音融三喜
        歌词正文...
    首行「歌名」靠「后面紧跟元数据行」这条信号剔除，避免把正文第一句误删。
    """
    lines = (text or "").splitlines()
    out: list[str] = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if _PLAIN_META_LABEL.match(line):
            continue
        # 首行是歌名：其后的第一个非空行若是元数据行，首行也是元数据，剔除
        if i == 0 and _next_is_meta(lines, 1):
            continue
        out.append(raw)
    return "\n".join(out)


def lyrics_from_text(text: str) -> tuple[list[LyricLine], list[str]]:
    """歌词原文分流：含时间标签走同步解析，否则按纯文本。

    返回 (同步行列表, 纯文本行列表)，两者必有且只有一个非空。
    纯文本路径会先剔除「作词/作曲/编曲」这类元数据行。
    同步路径会把「同时间戳的相邻两行」合并成一句（原文 + 译文）。
    """
    synced = parse_lrc(text)
    if synced:
        return merge_translations(synced), []
    return [], parse_plain(strip_meta_lines(text))


# ---------- 双语歌词（原文 + 译文） ----------
#
# 两种常见形态：
# 1. 纯文本交替排版（浏览器下载的 .txt 最常见）：
#       Who can surely know      ← 原文
#       风将吹向何方              ← 译文
# 2. 同步 LRC 同时间戳两行（外部工具导出的双语 LRC）：
#       [00:02.36]Who can surely know
#       [00:02.36]风将吹向何方
#
# 两种都必须合并成「一句」，否则译文会自己占一个时间槽：行数翻倍会让整首歌的
# 时间轴被压缩一半，译文还永远比原文晚半句（v2.6.10 实测 74 行 / 实际 37 句）。

# 中日韩字符：汉字（含扩展 A/兼容区）、日文假名、韩文谚文
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]")

# 双语判定门槛：少于 4 行不判（无所谓），两种语种各自至少占 25%，
# 且相邻行「语种不同」的比例 ≥85%。
#
# 为什么要看整份文件而不是只看相邻两行：纯中文歌里夹一句英文副歌（"Yeah!"、"Oh~"）
# 时，只看相邻两行会把它和下一句中文错误配对，导致少一句、整首错位。整份文件
# 严格交替才算双语，能挡住这种误判。
BILINGUAL_MIN_LINES = 4
BILINGUAL_MIN_RATIO = 0.25
BILINGUAL_MIN_ALTERNATION = 0.85


def has_cjk(text: str) -> bool:
    """文本里是否含中日韩字符（用来区分「原文行」与「译文行」的语种）。"""
    return bool(_CJK.search(text or ""))


def is_bilingual_alternating(lines: list[str]) -> bool:
    """判断一批纯文本行是否为「原文 / 译文」交替排版。"""
    lines = [s for s in (lines or []) if s and s.strip()]
    if len(lines) < BILINGUAL_MIN_LINES:
        return False
    flags = [has_cjk(s) for s in lines]
    n_cjk = sum(flags)
    n_other = len(flags) - n_cjk
    quota = len(flags) * BILINGUAL_MIN_RATIO
    if n_cjk < quota or n_other < quota:
        return False
    flips = sum(1 for a, b in pairwise(flags) if a != b)
    return flips >= (len(flags) - 1) * BILINGUAL_MIN_ALTERNATION


def pair_bilingual(lines: list[str]) -> list[tuple[str, str]]:
    """把交替排版的原文/译文两两配对，返回 `[(原文, 译文)]`。

    不是双语排版时每行自成一句（译文为空串），调用方可以无脑按「句」处理。
    先出现的那行当原文——中英/英中哪种顺序在前都成立。
    """
    rows = [s.strip() for s in (lines or []) if s and s.strip()]
    if not is_bilingual_alternating(rows):
        return [(s, "") for s in rows]
    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(rows):
        cur = rows[i]
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if nxt is not None and has_cjk(cur) != has_cjk(nxt):
            pairs.append((cur, nxt))
            i += 2
        else:
            pairs.append((cur, ""))
            i += 1
    return pairs


def merge_translations(lines: list[LyricLine]) -> list[LyricLine]:
    """把「同时间戳的相邻两行」合并成一句：后一行当前一行的译文。

    双语 LRC 的标准写法就是同一时间戳写两行。行文本相同（副歌里同句重复）不合并，
    避免把两句一样的歌词吞掉一句。
    """
    out: list[LyricLine] = []
    for line in lines or []:
        prev = out[-1] if out else None
        if (prev is not None
                and prev.time_ms == line.time_ms
                and not prev.translation
                and prev.text != line.text):
            prev.translation = line.text
            continue
        out.append(LyricLine(line.time_ms, line.text, line.translation))
    return out


def format_lrc_stamp(ms: int) -> str:
    """毫秒 -> LRC 时间标签 `[mm:ss.xx]`（百分秒，与 `parse_lrc` 兼容）。"""
    if ms < 0:
        ms = 0
    total_s, cs = divmod(ms, 1000)
    m, s = divmod(total_s, 60)
    return f"[{m:02d}:{s:02d}.{cs // 10:02d}]"


def format_lrc(lines: list[LyricLine]) -> str:
    """把同步歌词序列化回 LRC；有译文的句子写成「同时间戳两行」。

    同时间戳两行是双语 LRC 的通用写法，外部播放器（含本应用 `parse_lrc`）都认，
    所以对齐产物落地成 .lrc 时也走这里。
    """
    out: list[str] = []
    for line in lines or []:
        stamp = format_lrc_stamp(line.time_ms)
        out.append(f"{stamp}{line.text}")
        if line.translation:
            out.append(f"{stamp}{line.translation}")
    if not out:
        return ""
    return "\n".join(out) + "\n"


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
