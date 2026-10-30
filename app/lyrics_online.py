# -*- coding: utf-8 -*-
"""联网歌词匹配（LRCLIB，公开免费、无需 API key）。

定位：**本地优先，联网兜底**。仅当「手动绑定 / 同名 .lrc / 内嵌歌词 / 本地缓存」
都没有时，才向 LRCLIB 检索；命中后缓存到
`%APPDATA%/轻音播放器/lyrics_cache/<track_id>.lrc`，之后离线也能显示。

为什么把网络请求留在 app 层：解析与选曲逻辑是纯函数，可以完全离线单测；
真正的 HTTP 通过 `fetch` 参数注入，测试不联网。

## v2.4 相对 v2.2 的四处改进

1. **多轮降级检索**（`lookup_plan`）：以前只有「歌名+艺人」一条结构化查询，
   标签一脏（`晴天 (Live)`、`周杰伦/费玉清`、`01 - 晴天`）就零结果。现在按
   精确→宽泛排成有序查询计划，命中高信任度即早停，不多打请求。
2. **标签清洗**（`clean_title` / `clean_artist`）：去括号噪声、`feat.` 尾巴、
   前导音轨号、全角符号；多艺人切分只认 `;/／、|feat.`，**不切 `&` 和 `,`**
   （`Simon & Garfunkel`、`Earth, Wind & Fire` 会被切坏）。
3. **打分收紧**：身份门槛改成「标题对上 **或** 时长 ≤2s」，去掉原来
   「只有艺人对上也算」——同名不同曲最容易这样配错；同步歌词单独分区，
   有同步稿时绝不用纯文本稿。
4. **负缓存**（`.miss`，7 天 TTL）：查不到的歌不再每次启动都重打四个请求。
   用户可在歌词区右键「重新联网匹配歌词」强制重来。

LRCLIB 的硬约束（照 docs 实现，不猜）：
- `/api/get` 是精确端点，`duration` 必须落在 1..3600 秒且与库内记录差 **±2s**
  以内才返回，未命中 **404**；
- `/api/search` 最多 20 条、**不支持分页**，`q` 优先于结构化参数；
- 参数校验失败返回**纯文本**而非 JSON（400），所以解析必须容错；
- 匿名 ~45 请求/分钟、标识 UA ~90 请求/分钟，超限 **429 + Retry-After**，
  要求串行、失败按 `Retry-After` 退避。因此本模块串行发请求、限流即刻收手。
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from app.paths import lyrics_cache_dir

SEARCH_URL = "https://lrclib.net/api/search"
GET_URL = "https://lrclib.net/api/get"
# LRCLIB 按 UA 分档配额（标识应用名可拿到 ~90/min 而非 ~45/min），所以要带名字和版本。
USER_AGENT = "QingYinPlayer/2.4 (+local desktop music player)"
CACHE_SUFFIX = ".lrc"
MISS_SUFFIX = ".miss"

# 单条请求超时：用户感知里 4~5 秒还没结果就该放弃了（原来 6s 偏长）。
DEFAULT_TIMEOUT = 4.5
# 整轮检索的墙钟预算：即使每个请求都慢，也不会让后台线程挂几十秒。
TOTAL_BUDGET = 9.0
# 达到这个分就认为「就是这首」，不再往下打查询（分数构成见 `_score`）。
GOOD_ENOUGH = 6.5
# 本地没有时长信息时够用的阈值：标题+艺人全等 = 4.5，已经足够可信。
GOOD_ENOUGH_NO_DURATION = 4.5
# 未命中的记忆时长：冷门歌/纯音乐不值得每次启动都重试。
MISS_TTL_DAYS = 7.0


@dataclass
class LyricHit:
    track_name: str
    artist_name: str
    album_name: str
    duration: int                 # 秒
    synced: str | None            # 带时间戳的 LRC
    plain: str | None             # 纯文本
    instrumental: bool            # 纯音乐（无歌词）

    @property
    def text(self) -> str | None:
        """优先同步歌词；没有就退纯文本。"""
        return self.synced or self.plain


@dataclass(frozen=True)
class Query:
    """一条待发请求。`kind` 只用于日志与测试断言，不影响行为。"""

    url: str
    kind: str                     # get | search | keyword


# ---------- 标签清洗 ----------
#
# 真实曲库的脏标签是匹配失败的头号原因。清洗的原则是「只删明确的噪声」：
# 括号里出现 live/remaster/伴奏/主题曲 这类词才删，不含噪声词的括号保留
# （有些歌名本身带括号，如 `Bohemian Rhapsody (Live Aid)` 之外的正常用法）。

_NOISE_WORDS = (
    # 英文
    "live", "remaster", "version", "ver.", "edit", "mix", "remix", "re-record",
    "feat", "ft.", "featuring", "cover", "demo", "acoustic", "mono", "stereo",
    "explicit", "clean", "instrumental", "karaoke", "ost", "soundtrack", "theme",
    "deluxe", "bonus", "single", "radio", "extended", "sped up", "slowed", "reverb",
    "live at", "mv",
    # 中文
    "现场", "演唱会", "伴奏", "纯音乐", "翻唱", "女声", "男声", "高音质", "无损",
    "版", "主题曲", "片头曲", "片尾曲", "插曲", "电视剧", "电影", "动画", "游戏",
    "重置", "重制", "混音", "配乐", "官方", "完整版", "超清", "原唱", "合唱", "组曲",
    "国语", "粤语", "日语", "闽南语",
)

_BRACKET_GROUP = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")
# 前导音轨号，两种形态分开写：
#   ① `[07] 歌名`、`(07) 歌名`——号码带括号时本身就是音轨号的强信号，不必再要求分隔符；
#   ② `01. 歌名`、`01 - 歌名`、`1、歌名`——裸号码必须跟分隔符，
#      否则 Taylor Swift 的《22》这种纯数字歌名会被一起吃掉。
_LEADING_INDEX = re.compile(r"^\s*(?:[\[\(]\d{1,3}[\]\)]\s*|\d{1,3}\s*[.\-、:：_]\s*)")
# 标题里的 `feat. X` 尾巴整段砍掉（艺人字段另外处理，那里是切分而不是砍掉）。
_FEAT_TAIL = re.compile(r"\s*(?:feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)
# 多艺人切分：只认这些分隔符。**不含 `&` 和 `,`**——
# `Simon & Garfunkel`、`Earth, Wind & Fire` 是单一艺人名，切了反而搜不到。
_ARTIST_SPLIT = re.compile(
    r"\s*(?:[;/／、|]|\bfeat\.?\b|\bft\.?\b|\bfeaturing\b)\s*", re.IGNORECASE)


def to_halfwidth(text: str) -> str:
    """全角 ASCII（U+FF01..FF5E）与全角空格转半角，只做字符映射不改语义。"""
    out = []
    for ch in text or "":
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def _strip_noise_groups(text: str) -> str:
    """删掉「含噪声词」的括号组；不含噪声词的括号原样留着。"""
    def repl(match: re.Match) -> str:
        inner = match.group(1).strip()
        if not inner:
            return ""                       # 空括号 `()` 也删
        lowered = inner.lower()
        return "" if any(word in lowered for word in _NOISE_WORDS) else match.group(0)

    previous = None
    while previous != text:                 # 循环处理嵌套/连续括号组
        previous = text
        text = _BRACKET_GROUP.sub(repl, text)
    return text


def clean_title(title: str) -> str:
    """把标题洗成「适合拿去检索」的样子；洗空了就退回原文，绝不返回空串。"""
    original = to_halfwidth(title or "").strip()
    if not original:
        return ""
    text = _strip_noise_groups(original)
    text = _FEAT_TAIL.sub("", text)
    text = _strip_noise_tail(text)
    text = _LEADING_INDEX.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" -_·.")
    return text or original


def _strip_noise_tail(text: str) -> str:
    """砍掉 `歌名 - Remastered 2011` 这种「破折号 + 噪声后缀」的尾巴。

    只处理最后一段、且该段含噪声词，避免误伤 `Jay-Z - 99 Problems` 这类
    破折号本来就在歌名里的情况（`99 problems` 不含噪声词，原样保留）。
    """
    parts = text.split(" - ")
    if len(parts) > 1 and any(word in parts[-1].lower() for word in _NOISE_WORDS):
        return " - ".join(parts[:-1])
    return text


def clean_artist(artist: str) -> str:
    """多艺人取主艺人；切不动就原样返回。"""
    original = to_halfwidth(artist or "").strip()
    if not original:
        return ""
    primary = _ARTIST_SPLIT.split(original)[0].strip(" -_·,")
    return primary or original


# ---------- URL 构造 ----------


def build_search_url(title: str, artist: str = "") -> str:
    """结构化检索 URL。两个键始终存在（空值也是空参数），便于调用方判断。"""
    params = urllib.parse.urlencode({
        "track_name": title or "",
        "artist_name": artist or "",
    })
    return f"{SEARCH_URL}?{params}"


def build_keyword_url(text: str) -> str:
    """自由文本检索：`q` 在标题/艺人/专辑任意字段里搜，且优先于结构化参数。"""
    return f"{SEARCH_URL}?{urllib.parse.urlencode({'q': text or ''})}"


def build_web_search_url(title: str, artist: str = "") -> str:
    """构造 LRCLIB 网页搜索地址（供「在线搜索歌词」在浏览器里打开）。

    与 `build_keyword_url` 不同：这里拼的是**给人看的网页**（lrclib.net/search），
    不是 JSON API（lrclib.net/api/search）。自动带上「标题 + 艺人」，让用户
    联网匹配失败时能自己到网页上搜。
    """
    query = " ".join(p for p in (title or "", artist or "") if p)
    return f"https://lrclib.net/search?{urllib.parse.urlencode({'q': query})}"


def build_get_url(title: str, artist: str, album: str = "",
                  duration_ms: int = 0) -> str:
    """精确端点。`duration` 只接受 1..3600 秒，越界会被服务端 400，先在这里钳住。"""
    params = {"track_name": title, "artist_name": artist}
    if album:
        params["album_name"] = album
    seconds = round(duration_ms / 1000.0) if duration_ms else 0
    if 1 <= seconds <= 3600:
        params["duration"] = seconds
    return f"{GET_URL}?{urllib.parse.urlencode(params)}"


def lookup_plan(title: str, artist: str, album: str = "",
                duration_ms: int = 0) -> list[Query]:
    """有序查询计划：**精确在前，宽泛在后**，重复 URL 只留第一次。

    顺序理由：`/api/get` 一次请求就能拿到高精度结果（还顺带校验时长），
    所以放最前；`q=` 覆盖面最广但最不准，兜底用。
    """
    clean_t = clean_title(title)
    if not clean_t:
        return []
    raw_artist = (artist or "").strip()
    primary_artist = clean_artist(artist)

    plan: list[Query] = []
    if raw_artist:
        plan.append(Query(build_get_url(clean_t, raw_artist, album, duration_ms), "get"))
        plan.append(Query(build_search_url(clean_t, raw_artist), "search"))
        if primary_artist and primary_artist != raw_artist:
            plan.append(Query(build_search_url(clean_t, primary_artist), "search"))
    plan.append(Query(build_keyword_url(clean_t), "keyword"))
    # 更宽泛的兜底：标题 + 主艺人一起全文搜。结构化查询（track_name/artist_name）
    # 对「艺人名写法略不一致」很敏感，全文 q= 反而常能捞回来。
    if primary_artist:
        plan.append(Query(build_keyword_url(f"{clean_t} {primary_artist}"), "keyword"))

    seen: set[str] = set()
    unique: list[Query] = []
    for query in plan:
        if query.url in seen:
            continue
        seen.add(query.url)
        unique.append(query)
    return unique


# ---------- 解析与选曲 ----------


def parse_hits(payload) -> list[LyricHit]:
    """把 LRCLIB 的 JSON 列表转成 LyricHit；容忍脏数据。"""
    hits: list[LyricHit] = []
    if not isinstance(payload, list):
        return hits
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            duration = int(item.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        hits.append(LyricHit(
            track_name=str(item.get("trackName") or ""),
            artist_name=str(item.get("artistName") or ""),
            album_name=str(item.get("albumName") or ""),
            duration=duration,
            synced=(item.get("syncedLyrics") or None),
            plain=(item.get("plainLyrics") or None),
            instrumental=bool(item.get("instrumental")),
        ))
    return hits


def as_hits(payload) -> list[LyricHit]:
    """`/api/get` 返回单个对象，`/api/search` 返回数组——这里统一成列表。"""
    if isinstance(payload, dict):
        return parse_hits([payload])
    return parse_hits(payload)


_LRC_TAG = re.compile(r"\[[^\]]*\]")


def usable_text(text: str | None) -> bool:
    """有实际文字才算歌词：纯空白、只有时间戳/`[Chorus]` 标记的都不算。"""
    if not text:
        return False
    return any(ch.isalnum() for ch in _LRC_TAG.sub("", text))


def _norm(text: str) -> str:
    """归一化：小写 + 只留字母数字（含中文），用来做包含式比对。"""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _overlap(a: str, b: str, floor: float = 0.5) -> bool:
    """包含式匹配，但要求长度相近。

    没有长度校验的话，标题「雨」会匹配上「下雨天」这种只有一两个字重叠的候选，
    是「配错词」的典型来源。
    """
    if not a or not b:
        return False
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b)) >= floor
    return False


def score_hit(hit: LyricHit, title: str, artist: str,
              want: float) -> tuple[float, bool]:
    """返回 (得分, 是否通过身份门槛)。`title`/`artist` 需已归一化，`want` 是秒。

    门槛只有两条路：**标题对得上**，或**时长差 ≤2 秒**。曾经允许「只有艺人对得上」，
    但同名不同曲（不同歌手唱同一首）正好落在这个口子上，配错歌词比没歌词更糟。
    """
    score = 0.0
    hit_title, hit_artist = _norm(hit.track_name), _norm(hit.artist_name)

    title_ok = False
    if title and hit_title:
        if title == hit_title:
            score += 3.0
            title_ok = True
        elif _overlap(title, hit_title):
            score += 2.0
            title_ok = True

    artist_ok = False
    if artist and hit_artist:
        if artist == hit_artist:
            score += 1.5
            artist_ok = True
        elif _overlap(artist, hit_artist, floor=0.4):
            score += 1.2
            artist_ok = True

    duration_ok = False
    if want and hit.duration:
        diff = abs(hit.duration - want)
        if diff <= 2:
            score += 3.0
            duration_ok = True
        elif diff <= 5:
            score += 2.0
        elif diff <= 10:
            score += 1.0
        elif title_ok and artist and not artist_ok:
            # 歌名对上、但艺人和时长双双不符：多半是同名翻唱，压一压。
            score -= 1.5

    if hit.synced and usable_text(hit.synced):
        score += 0.5                       # 同步稿严格优于纯文本稿

    return score, (title_ok or duration_ok)


def _best_of(candidates: list[LyricHit], title: str, artist: str,
             want: float) -> LyricHit | None:
    best: LyricHit | None = None
    best_score = float("-inf")
    for hit in candidates:
        score, gate = score_hit(hit, title, artist, want)
        if not gate:
            continue
        if score > best_score:
            best, best_score = hit, score
    return best


def pick_best(hits: list[LyricHit], title: str, artist: str,
              duration_ms: int = 0) -> LyricHit | None:
    """在候选里选最可信的一条；没有「对得上」的信号就不猜。

    先只在**带同步时间轴**的候选里选，一条都没通过才退到纯文本稿：
    不能滚动的高亮歌词体验差得多，只要同一首歌有同步稿就绝不用纯文本。
    """
    normalized_title, normalized_artist = _norm(title), _norm(artist)
    want = duration_ms / 1000.0 if duration_ms else 0.0
    usable = [h for h in hits if not h.instrumental and usable_text(h.text)]
    synced_only = [h for h in usable if h.synced and usable_text(h.synced)]
    return (_best_of(synced_only, normalized_title, normalized_artist, want)
            or _best_of(usable, normalized_title, normalized_artist, want))


# ---------- 网络 ----------


class RateLimited(Exception):
    """LRCLIB 返回 429/503：本轮立刻收手，不要连发（否则可能被临时封禁）。"""


@dataclass(frozen=True)
class FetchOutcome:
    """一次检索的结果。

    `aborted=True` 表示**中途放弃**（限流、预算耗尽），此时 `text` 为空并不代表
    「这首歌没有歌词」——调用方绝不能据此写负缓存，否则一次限流就会把一首明明
    有歌词的歌记住 7 天。真实联网验证时踩到过这个：连发十几个请求后 429，
    结果被当成「未命中」写进了负缓存。
    """

    text: str | None = None
    aborted: bool = False


# LRCLIB 文档明确建议请求之间留 200~500ms（尤其连续查询时）。
# 只作用于真实 HTTP 路径；测试注入的 `fetch` 不受影响，不会被拖慢。
_MIN_INTERVAL = 0.25
_last_request_at = 0.0


def _throttle() -> None:
    global _last_request_at
    wait = _MIN_INTERVAL - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _http_get_json(url: str, timeout: float):
    """GET 并解析 JSON。

    返回 None 表示「这个查询没有结果」（404、非 JSON 的校验错误、空响应）；
    抛出 `RateLimited` 表示限流/服务过载；其它异常原样抛给上层降级。
    """
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    _throttle()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code in (429, 503):
            raise RateLimited(f"HTTP {exc.code}") from exc
        raise
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        return None                       # 参数校验失败时服务端回纯文本，不是 JSON


def fetch_outcome(title: str, artist: str, duration_ms: int = 0,
                  timeout: float = DEFAULT_TIMEOUT, fetch=None,
                  album: str = "", progress=None) -> FetchOutcome:
    """按查询计划检索，返回「歌词 + 是否中途放弃」。

    `fetch` 可注入，测试不联网。命中高信任度结果即早停，避免为了同一首歌
    把四个查询全打一遍（LRCLIB 有速率限制，且用户在等着看歌词）。

    `progress(cur, total)` 可选回调：每发一个查询前调用一次，供 UI 显示
    「正在匹配 2/4」这类进度。测试不传它，行为不变。
    """
    fetch = fetch or _http_get_json
    plan = lookup_plan(title, artist, album, duration_ms)
    if not plan:
        return FetchOutcome()

    normalized_title, normalized_artist = _norm(title), _norm(artist)
    want = duration_ms / 1000.0 if duration_ms else 0.0
    threshold = GOOD_ENOUGH if want else GOOD_ENOUGH_NO_DURATION
    deadline = time.monotonic() + TOTAL_BUDGET

    best: LyricHit | None = None
    best_score = float("-inf")
    for i, query in enumerate(plan):
        if progress is not None:
            progress(i + 1, len(plan))
        if time.monotonic() > deadline:
            return FetchOutcome(best.text if best else None, aborted=True)
        try:
            payload = fetch(query.url, timeout)
        except RateLimited:
            # 限流立即停手，不再发下一条；已有结果照常返回，但没有就报 aborted
            return FetchOutcome(best.text if best else None, aborted=True)
        except Exception:  # noqa: BLE001  单条查询失败不该影响后续查询
            continue
        hit = pick_best(as_hits(payload), title, artist, duration_ms)
        if hit is None:
            continue
        score, _ = score_hit(hit, normalized_title, normalized_artist, want)
        if score > best_score:
            best, best_score = hit, score
        if best_score >= threshold:
            break

    return FetchOutcome(best.text if best else None)


def fetch_lyrics(title: str, artist: str, duration_ms: int = 0,
                 timeout: float = DEFAULT_TIMEOUT, fetch=None,
                 album: str = "") -> str | None:
    """`fetch_outcome` 的简化封装：只要歌词原文，任何异常都降级为 None。"""
    return fetch_outcome(title, artist, duration_ms, timeout, fetch, album).text


def fetch_best_hit(title: str, artist: str, duration_ms: int = 0,
                   timeout: float = DEFAULT_TIMEOUT, fetch=None,
                   album: str = "") -> tuple[LyricHit | None, bool]:
    """同 `fetch_outcome`，但返回选中的 `LyricHit`（而非纯文本）。

    多源检索（见 `app/lyrics_multi.py`）需要跨源统一打分，只拿文本不够——
    文本已丢失「艺人/时长/是否有同步稿」这些身份信号。所以这里抽出「返回 hit」
    的变体：命中返回 `(hit, aborted)`，`hit` 是候选里最可信的一条（`pick_best`
    已经按「标题对上或时长差 ≤2s」过滤过，配错词比没词更糟）。
    """
    fetch = fetch or _http_get_json
    plan = lookup_plan(title, artist, album, duration_ms)
    if not plan:
        return None, False

    normalized_title, normalized_artist = _norm(title), _norm(artist)
    want = duration_ms / 1000.0 if duration_ms else 0.0
    threshold = GOOD_ENOUGH if want else GOOD_ENOUGH_NO_DURATION
    deadline = time.monotonic() + TOTAL_BUDGET

    best: LyricHit | None = None
    best_score = float("-inf")
    for query in plan:
        if time.monotonic() > deadline:
            return best, True
        try:
            payload = fetch(query.url, timeout)
        except RateLimited:
            return best, True
        except Exception:  # noqa: BLE001  单条查询失败不该影响后续查询
            continue
        hit = pick_best(as_hits(payload), title, artist, duration_ms)
        if hit is None:
            continue
        score, _ = score_hit(hit, normalized_title, normalized_artist, want)
        if score > best_score:
            best, best_score = hit, score
        if best_score >= threshold:
            break

    return best, False


# ---------- 缓存（命中即离线可用） ----------
#
# track_id 是路径哈希的 16 位十六进制（见 models.make_track_id），直接当文件名安全。
# `base_dir` 可注入，测试用 tmpdir，不碰用户真实缓存。


def cache_path(track_id: str, base_dir: str | None = None) -> str:
    base = base_dir or lyrics_cache_dir()
    return os.path.join(base, f"{track_id}{CACHE_SUFFIX}")


def read_cache(track_id: str, base_dir: str | None = None) -> str | None:
    """读缓存歌词；不存在/不可解码一律 None。"""
    if not track_id:
        return None
    path = cache_path(track_id, base_dir)
    if not os.path.isfile(path):
        return None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read() or None
        except (UnicodeDecodeError, OSError):
            continue
    return None


def write_cache(track_id: str, text: str, base_dir: str | None = None) -> str | None:
    """原子写缓存（`.part` + `os.replace`）；写盘失败返回 None 且不抛。"""
    if not track_id or not text:
        return None
    path = cache_path(track_id, base_dir)
    tmp = path + ".part"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        return None
    return path


def clear_cache(track_id: str, base_dir: str | None = None) -> None:
    if not track_id:
        return
    with contextlib.suppress(OSError):
        os.remove(cache_path(track_id, base_dir))


# ---------- 负缓存（没查到这件事也值得记住） ----------


def miss_path(track_id: str, base_dir: str | None = None) -> str:
    base = base_dir or lyrics_cache_dir()
    return os.path.join(base, f"{track_id}{MISS_SUFFIX}")


def write_miss(track_id: str, base_dir: str | None = None) -> None:
    """记录「这歌查过、没查到」，只有时间戳，失败静默。"""
    if not track_id:
        return
    path = miss_path(track_id, base_dir)
    tmp = path + ".part"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(f"{time.time():.0f}")
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)


def read_miss(track_id: str, base_dir: str | None = None,
              ttl_days: float = MISS_TTL_DAYS) -> bool:
    """TTL 内查过且没查到 → True。文件损坏/不存在都当没查过。"""
    if not track_id:
        return False
    try:
        with open(miss_path(track_id, base_dir), "r", encoding="utf-8") as f:
            stamp = float(f.read().strip() or 0)
    except (OSError, ValueError):
        return False
    return (time.time() - stamp) < ttl_days * 86400


def clear_miss(track_id: str, base_dir: str | None = None) -> None:
    if not track_id:
        return
    with contextlib.suppress(OSError):
        os.remove(miss_path(track_id, base_dir))


# ---------- 后台线程 ----------


class LyricsFetchWorker(QThread):
    """后台联网抓歌词：成功发 `found(track_id, 歌词原文)`，确认没找到发 `missed(track_id)`。

    放 QThread 是为了不阻塞 UI；调用方自己持有引用并 connect `finished` 清理。
    `missed` 让调用方能落负缓存，避免下次启动为一个查不到的歌重打四个请求——
    但**限流/超时中止时不发**，否则一次 429 就会把有好歌词的歌记住 7 天。
    中止时改发 `aborted(track_id)`：界面据此把「正在找」换成「失败，可重试」，
    同样**不落负缓存**——一次网络抖动不等于这首歌没有歌词。
    `progress(cur, total)` 按查询计划逐步上报，供界面显示「正在匹配 2/4」。
    """

    found = Signal(str, str)
    missed = Signal(str)
    aborted = Signal(str)
    progress = Signal(int, int)

    def __init__(self, track_id: str, title: str, artist: str,
                 duration_ms: int = 0, album: str = "", parent=None) -> None:
        super().__init__(parent)
        self._track_id = track_id
        self._title = title
        self._artist = artist
        self._duration_ms = duration_ms
        self._album = album

    def run(self) -> None:
        def _report(cur: int, total: int) -> None:
            self.progress.emit(cur, total)

        outcome = fetch_outcome(self._title, self._artist, self._duration_ms,
                                album=self._album, progress=_report)
        # v2.7.5：窗口已关则不发信号（见 lyrics_multi 同处说明）
        if self.isInterruptionRequested():
            return
        if outcome.text:
            self.found.emit(self._track_id, outcome.text)
        elif outcome.aborted:
            self.aborted.emit(self._track_id)
        else:
            self.missed.emit(self._track_id)
