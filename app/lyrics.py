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

# 元数据块只在「文件开头的这一段」里认，且要求连续 ≥2 行 —— 见 strip_meta_lines。
_META_SCAN_LINES = 8
_META_MIN_RUN = 2


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

    两条约束缺一不可（v2.7.3 收紧，此前会误删正文）：
    1. 只看**前 8 行**（`_META_SCAN_LINES`）—— 正文深处出现「制作 : xxx」不是元数据；
    2. 元数据必须**连续 ≥2 行**（`_META_MIN_RUN`）—— 孤立一行「制作 : xxx」更可能是
       歌词本身（探针实测：正文第 2 行是这种样式时，旧实现会把首句歌词当歌名删掉，
       3 行变 1 行）。

    首行歌名靠「后面紧跟 ≥2 行元数据」这条信号剔除，避免把正文第一句误删。
    """
    lines = (text or "").splitlines()
    # 前 8 个非空行的下标
    idxs = [i for i, raw in enumerate(lines) if raw.strip()][:_META_SCAN_LINES]

    meta_idx: set[int] = set()
    run: list[int] = []
    for i in [*idxs, None]:
        if i is not None and _PLAIN_META_LABEL.match(lines[i].strip()):
            run.append(i)
            continue
        if len(run) >= _META_MIN_RUN:
            meta_idx.update(run)
        run = []

    drop: set[int] = set(meta_idx)
    if idxs:
        first = idxs[0]
        if first not in meta_idx and _PLAIN_META_LABEL.match(lines[first].strip()):
            # 文件**第一行**就是元数据：单行也删（后面紧跟正文，不可能把它当歌词唱）
            drop.add(first)
        elif len(idxs) > 1 and idxs[1] in drop:
            # 首行是歌名：紧随其后的就是被剔除的元数据块
            drop.add(first)

    return "\n".join(raw for i, raw in enumerate(lines) if i not in drop)


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


# ---------- 双语判定 / 结构标记行（v2.7.3） ----------
#
# 浏览器/工具导出的 .txt 常带 [Verse 1]、(间奏)、【副歌】 这类段落标记。它们不是
# 歌词，却会被当成「一行歌词」参与双语判定：`[Verse 1]` 含 ASCII 字母但没有汉字，
# 于是冒充"英文原文行"，把紧跟其后的真中文歌词降级成小字译文（探针实测 4 行被配成
# 2 句，中文整段变译文）。
#
# 这里给它们一个独立身份：**保留在序列里原样显示，但不参与双语配对**。

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

# 整体被括号/星号包裹的行：捕获括号内的内容
_WRAPPED = re.compile(
    r"^\s*(?:[\[【〔]([^\[\]【】〔〕]*)[\]】〕]"
    r"|[\(（]([^\(\)（）]*)[\)）]"
    r"|\*([^*]+)\*)\s*$"
)

# 常见段落标记词：带不带括号都认（「间奏」「[Chorus 2]」「*intro*」）
_MARKER_WORDS = re.compile(
    r"^\s*[\[【〔(（*]?\s*"
    r"(?:间奏|前奏|尾奏|间奏曲|副歌|主歌|桥段|过渡段|过渡|合唱|吟唱|纯音乐|伴奏|音乐"
    r"|intro|outro|verse|chorus|pre-?chorus|bridge|hook|interlude|instrumental"
    r"|solo|refrain|breakdown|drop|skit)"
    r"(?:\s*\d+)?\s*[:：]?\s*[\]】〕)）*]?\s*$",
    re.IGNORECASE,
)

# 括号内最多这么长才可能是标记（再长就当成真歌词，宁可不动）
_MARKER_MAX_LEN = 24


def is_structure_marker(line: str) -> bool:
    """判断一行是「段落标记」而不是歌词。

    两类命中：
    1. 常见标记词（间奏/副歌/verse/chorus…），带不带括号都算；
    2. 整行被 `[]`/`【】`/`〔〕`/`()`/`（）`/`**` 包住，且括号内**不含中日韩字符**、
       长度 ≤24 —— 如 `[Verse 1]`、`(ahh)`；含汉字的如「(月亮代表我的心)」仍当歌词。
    """
    s = (line or "").strip()
    if not s:
        return False
    if _MARKER_WORDS.match(s):
        return True
    m = _WRAPPED.match(s)
    if not m:
        return False
    inner = next(g for g in m.groups() if g is not None).strip()
    if not inner or len(inner) > _MARKER_MAX_LEN:
        return False
    return not has_cjk(inner)


def has_cjk(text: str) -> bool:
    """文本里是否含中日韩字符（用来区分「原文行」与「译文行」的语种）。"""
    return bool(_CJK.search(text or ""))


def is_bilingual_alternating(lines: list[str]) -> bool:
    """判断一批纯文本行是否为「原文 / 译文」交替排版。

    结构标记行（`[Verse 1]` 之类）先剔除再判 —— 否则它们会冒充另一种语种，
    把整份文件误判成双语。判定口径（两语种各 ≥25%、相邻异类 ≥85%）见上方常量。
    """
    lines = [s for s in (lines or [])
             if s and s.strip() and not is_structure_marker(s)]
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

    结构标记行（`[Verse 1]` 之类）不参与配对、也不会被配对吞掉：各自单独成一条
    （译文为空），原样留在结果里。双语配对本身照旧一行两句。
    """
    rows = [s.strip() for s in (lines or []) if s and s.strip()]
    if not rows:
        return []
    marks = [is_structure_marker(s) for s in rows]
    body = [s for s, is_mark in zip(rows, marks, strict=True) if not is_mark]
    if not is_bilingual_alternating(body):
        return [(s, "") for s in rows]

    out: list[tuple[str, str]] = []
    i = 0
    while i < len(rows):
        if marks[i]:
            out.append((rows[i], ""))
            i += 1
            continue
        # 跳到下一个非标记行，中间的标记行先攒着（别让它们打断配对）
        j = i + 1
        pending: list[str] = []
        while j < len(rows) and marks[j]:
            pending.append(rows[j])
            j += 1
        nxt = rows[j] if j < len(rows) else None
        if nxt is not None and has_cjk(rows[i]) != has_cjk(nxt):
            out.append((rows[i], nxt))
            out.extend((marker, "") for marker in pending)
            i = j + 1
        else:
            out.append((rows[i], ""))
            i += 1
    return out



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


_STAMP_ONE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")


def _stamp_ms(match: re.Match) -> int:
    """把正则匹配到的时间标签换算成毫秒（百分秒与毫秒两种写法都认）。"""
    ms = int(match.group(1)) * 60000 + int(match.group(2)) * 1000
    frac = match.group(3)
    if frac:
        ms += int(frac.ljust(3, "0")[:3])
    return ms


def shift_lrc(lrc: str, delta_ms: int) -> tuple[str, int]:
    """把 LRC 里**所有**时间戳整体平移 `delta_ms`（负=提前），返回 `(新文本, 实际增量)`。

    为什么要这个：本地对齐只能按「有声段 + 字数」估算，前奏一长整条时间轴就会整体
    偏早（实测《何者》首句早 5.8 秒）。这种**系统性偏移**没法靠算法猜准，让用户
    听一遍、按 ±0.5s 步进推到位最实在——所以偏移量要写回 .lrc，切歌/重启仍然生效。

    只动「行首连续的时间标签」，正文里的方括号不碰；同时间戳的两行（双语）一起平移。
    钳位规则：不许把任何时间戳推成负数，实际增量取 `max(delta_ms, -最早时间戳)`，
    否则第一句会被压到 0 秒，后面几句糊在同一时刻。
    """
    lines = (lrc or "").splitlines()
    parsed: list[tuple[int, list[tuple[int, int, int]]]] = []
    for idx, line in enumerate(lines):
        stamps: list[tuple[int, int, int]] = []
        pos = 0
        while True:
            match = _STAMP_ONE.match(line, pos)
            if match is None:
                break
            stamps.append((match.start(), match.end(), _stamp_ms(match)))
            pos = match.end()
        if stamps:
            parsed.append((idx, stamps))
    if not parsed:
        return lrc, 0

    earliest = min(ms for _idx, stamps in parsed for _s, _e, ms in stamps)
    actual = max(int(delta_ms), -earliest)
    if actual == 0:
        return lrc, 0
    for idx, stamps in parsed:
        line = lines[idx]
        for start, end, ms in reversed(stamps):   # 从后往前替换，前面标签位置不受影响
            line = line[:start] + format_lrc_stamp(ms + actual) + line[end:]
        lines[idx] = line
    out = "\n".join(lines)
    if lrc.endswith("\n"):
        out += "\n"
    return out, actual


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
