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


# ---------- 标签清洗与文本归一化 ----------
#
# v3.0.5：清洗/归一化/相似度整体搬到 `app.lyrics_match`（纯文本层，无网络无 Qt），
# 这里只做 re-export，保持既有调用方（本文件、lyrics_multi、测试）不用改 import。
# 搬走的理由：这堆逻辑跟「怎么发 HTTP」毫无关系，混在 740 行里既难读也难测。

from app.lyrics_match import (  # noqa: E402  放在文件中部是为了贴近使用处
    ALBUM_EXACT,
    ALBUM_STRONG,
    ARTIST_EXACT,
    ARTIST_STRONG,
    ARTIST_WEAK,
    CONF_LOW,
    DURATION_EXACT_SEC,
    DURATION_FAR_SEC,
    DURATION_NEAR_SEC,
    PENALTY_COVER,
    TITLE_EXACT,
    TITLE_STRONG,
    TITLE_WEAK,
    W_ALBUM_EXACT,
    W_ALBUM_STRONG,
    W_ARTIST_EXACT,
    W_ARTIST_STRONG,
    W_ARTIST_WEAK,
    W_DURATION_EXACT,
    W_DURATION_FAR,
    W_DURATION_NEAR,
    W_SYNCED,
    W_TITLE_EXACT,
    W_TITLE_STRONG,
    W_TITLE_WEAK,
    MatchDetail,
    classify_confidence,
    clean_artist,
    clean_title,
    normalize,
    prepare_title,
    scripts_disjoint,
    similarity,
    # 兼容性 re-export：v3.0.5 之前 `to_halfwidth` 住在本模块，外部还有调用方
    to_halfwidth,  # noqa: F401
    version_penalty,
)


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
    """归一化（NFKC + 拆变音 + 小写 + 繁简归并 + 去标点）。v3.0.5 起等同 `normalize`。"""
    return normalize(text)


def score_hit_detail(hit: LyricHit, title: str, artist: str,
                     want: float, album: str = "") -> MatchDetail:
    """打分并返回**完整过程**（各信号相似度 + 置信档位）。

    v3.0.5 重写。相对 v2.4 的三处变化：

    1. **逐项相似度替代包含式布尔判断**。以前 `_overlap` 只有「是/否」，
       错一个字就是 0 分；现在 `similarity()` 给出 0~1 的连续值，再按
       精确/强/弱三档取权重——繁简差异、拼写微差、多余装饰词都能落进
       「强」档而不是掉到 0。
    2. **候选侧也做清洗**（`prepare_title`）。以前只洗查询侧，候选标题里的
       `(Live)`、`周杰伦 - 稻香` 这类装饰始终是噪声；现在两边对称清洗，
       `稻香` 对 `周杰伦 - 稻香` 从「不相似」变成「完全相同」。
    3. **门槛从「标题对上」改成「标题相似度 ≥ 弱档」**，并新增置信分档：
       只有弱标题一项支撑的结果会被判 `low`，默认不接受（见 `pick_best`）。

    门槛仍有三条路：**标题够像**，或**时长差 ≤2 秒**，或**专辑够像且艺人相符**
    （v2.8.2 的跨语言桥梁，一字未改）。`want` 单位是秒，0 表示本地没有时长。
    """
    reasons: list[str] = []

    query_title = prepare_title(title, artist)
    hit_title = prepare_title(hit.track_name, hit.artist_name)
    query_artist = clean_artist(artist)
    hit_artist = clean_artist(hit.artist_name)
    query_album = clean_title(album)
    hit_album = clean_title(hit.album_name)

    title_sim = similarity(query_title, hit_title) if (query_title and hit_title) else 0.0
    artist_sim = (similarity(query_artist, hit_artist)
                  if (query_artist and hit_artist) else 0.0)
    album_sim = (similarity(query_album, hit_album)
                 if (query_album and hit_album) else 0.0)

    score = 0.0

    title_ok = False
    if title_sim >= TITLE_EXACT:
        score += W_TITLE_EXACT
        title_ok = True
        reasons.append("标题精确")
    elif title_sim >= TITLE_STRONG:
        score += W_TITLE_STRONG
        title_ok = True
        reasons.append(f"标题强匹配{title_sim:.2f}")
    elif title_sim >= TITLE_WEAK:
        score += W_TITLE_WEAK
        title_ok = True
        reasons.append(f"标题弱匹配{title_sim:.2f}")

    artist_ok = False
    if artist_sim >= ARTIST_EXACT:
        score += W_ARTIST_EXACT
        artist_ok = True
        reasons.append("艺人精确")
    elif artist_sim >= ARTIST_STRONG:
        score += W_ARTIST_STRONG
        artist_ok = True
        reasons.append(f"艺人强匹配{artist_sim:.2f}")
    elif artist_sim >= ARTIST_WEAK:
        score += W_ARTIST_WEAK
        reasons.append(f"艺人弱匹配{artist_sim:.2f}")

    duration_ok = False
    diff = -1.0
    if want and hit.duration:
        diff = abs(hit.duration - want)
        if diff <= DURATION_EXACT_SEC:
            score += W_DURATION_EXACT
            duration_ok = True
            reasons.append(f"时长差{diff:.0f}s")
        elif diff <= DURATION_NEAR_SEC:
            score += W_DURATION_NEAR
            reasons.append(f"时长近{diff:.0f}s")
        elif diff <= DURATION_FAR_SEC:
            score += W_DURATION_FAR
            reasons.append(f"时长偏{diff:.0f}s")
        elif title_ok and artist and not artist_ok and not scripts_disjoint(
                query_artist, hit_artist):
            # 歌名对上、但艺人和时长双双不符：多半是同名翻唱，压一压。
            # **跨书写系统时除外**（`BTS` vs `방탄소년단`）：那不是「不相似」，
            # 是无从比较，扣分等于惩罚跨语言曲库（v3.0.5）。
            score += PENALTY_COVER
            reasons.append("疑似翻唱")

    album_ok = False
    if album_sim >= ALBUM_EXACT:
        score += W_ALBUM_EXACT
        album_ok = True
        reasons.append("专辑精确")
    elif album_sim >= ALBUM_STRONG:
        score += W_ALBUM_STRONG
        album_ok = True
        reasons.append(f"专辑强匹配{album_sim:.2f}")

    if hit.synced and usable_text(hit.synced):
        score += W_SYNCED               # 同步稿严格优于纯文本稿
        reasons.append("同步稿")

    # 版次负信号：候选标题带「伴奏/翻唱/Live」——清洗后它和原版一模一样，
    # 只能靠这一项把它压到原版后面（v3.0.5）。
    penalty = version_penalty(hit.track_name)
    if penalty:
        score += penalty
        reasons.append("版次减分")

    gate = bool(title_ok or duration_ok or (album_ok and artist_ok))
    confidence = classify_confidence(
        title_sim, artist_sim, album_sim, diff, gate,
        artist_known=bool(query_artist and hit_artist),
        duration_known=bool(want and hit.duration),
    )
    return MatchDetail(
        score=round(score, 4), gate=gate,
        title_sim=round(title_sim, 4), artist_sim=round(artist_sim, 4),
        album_sim=round(album_sim, 4), duration_diff=diff,
        synced=bool(hit.synced and usable_text(hit.synced)),
        confidence=confidence, reasons=tuple(reasons),
    )


def score_hit(hit: LyricHit, title: str, artist: str,
              want: float, album: str = "") -> tuple[float, bool]:
    """`score_hit_detail` 的兼容封装：只要 (得分, 是否过门槛)。"""
    detail = score_hit_detail(hit, title, artist, want, album)
    return detail.score, detail.gate


def _best_of(candidates: list[LyricHit], title: str, artist: str,
             want: float, album: str = "",
             allow_low: bool = False) -> tuple[LyricHit | None, MatchDetail | None]:
    best: LyricHit | None = None
    best_detail: MatchDetail | None = None
    best_score = float("-inf")
    for hit in candidates:
        detail = score_hit_detail(hit, title, artist, want, album)
        if not detail.gate:
            continue
        if detail.confidence == CONF_LOW and not allow_low:
            continue                       # 只有弱标题一项支撑：不值得冒险
        if detail.score > best_score:
            best, best_detail, best_score = hit, detail, detail.score
    return best, best_detail


def pick_best_detail(hits: list[LyricHit], title: str, artist: str,
                     duration_ms: int = 0, album: str = "",
                     allow_low: bool = False) -> tuple[LyricHit | None, MatchDetail | None]:
    """`pick_best` 的详版：额外返回命中那一条的 `MatchDetail`（供日志/评测）。

    先用**带同步时间轴**的候选选一轮，一条都没通过才退到纯文本稿：
    不能滚动的高亮歌词体验差得多，只要同一首歌有同步稿就绝不用纯文本。
    """
    want = duration_ms / 1000.0 if duration_ms else 0.0
    usable = [h for h in hits if not h.instrumental and usable_text(h.text)]
    synced_only = [h for h in usable if h.synced and usable_text(h.synced)]
    best, detail = _best_of(synced_only, title, artist, want, album, allow_low)
    if best is not None:
        return best, detail
    return _best_of(usable, title, artist, want, album, allow_low)


def pick_best(hits: list[LyricHit], title: str, artist: str,
              duration_ms: int = 0, album: str = "",
              allow_low: bool = False) -> LyricHit | None:
    """在候选里选最可信的一条；没有「对得上」的信号就不猜。

    `allow_low=False`（默认）会丢掉置信档位为 `low` 的候选——那一档只靠
    「标题弱相似」撑着，正是「晴天」配到「晴天娃娃」的来源。配错词比没有词
    更糟，所以默认不冒这个险；评测想看清「到底差在哪」时传 True。
    """
    return pick_best_detail(hits, title, artist, duration_ms, album, allow_low)[0]


# ---------- 网络 ----------


class RateLimited(Exception):
    """LRCLIB 返回 429（请求过频）：本轮立刻收手，不要连发（否则可能被临时封禁）。"""


class ServerBusy(Exception):
    """LRCLIB 返回 503（ServerOverloaded）：**瞬时的服务过载，不是限流**。

    v2.8.2 从 `RateLimited` 里拆出来。以前 503 与 429 混在一起，第一个
    `get` 查询一旦撞上 503 就整轮中止，永远到不了那个真正能命中的 `q=` 关键词
    查询（实测：`痴人说梦` 的 `get` 端点间歇 503，但 `q=痴人说梦` 稳定返回命中）。
    503 应当「跳过这条、试下一条」，而不是把整首歌判死。"""


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
    抛出 `RateLimited` 表示 429 限流（立即收手）；抛出 `ServerBusy` 表示 503
    服务过载（瞬时，可跳过这条改试下一条）；其它异常原样抛给上层降级。
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
        if exc.code == 429:
            raise RateLimited(f"HTTP {exc.code}") from exc
        if exc.code == 503:
            raise ServerBusy(f"HTTP {exc.code}") from exc
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

    want = duration_ms / 1000.0 if duration_ms else 0.0
    threshold = GOOD_ENOUGH if want else GOOD_ENOUGH_NO_DURATION
    deadline = time.monotonic() + TOTAL_BUDGET

    best: LyricHit | None = None
    best_score = float("-inf")
    saw_busy = False
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
        except ServerBusy:
            # v2.8.2：503 是瞬时过载，跳过这条改试下一条，别把整首歌判死。
            # 记一笔：若最终一条都没中，要报 aborted 而不是 missed（不写负缓存）。
            saw_busy = True
            continue
        except Exception:  # noqa: BLE001  单条查询失败不该影响后续查询
            continue
        hit, detail = pick_best_detail(as_hits(payload), title, artist,
                                       duration_ms, album)
        if hit is None or detail is None:
            continue
        if detail.score > best_score:
            best, best_score = hit, detail.score
        if best_score >= threshold:
            break

    return FetchOutcome(best.text if best else None,
                        aborted=(best is None and saw_busy))


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

    want = duration_ms / 1000.0 if duration_ms else 0.0
    threshold = GOOD_ENOUGH if want else GOOD_ENOUGH_NO_DURATION
    deadline = time.monotonic() + TOTAL_BUDGET

    best: LyricHit | None = None
    best_score = float("-inf")
    saw_busy = False
    for query in plan:
        if time.monotonic() > deadline:
            return best, True
        try:
            payload = fetch(query.url, timeout)
        except RateLimited:
            return best, True
        except ServerBusy:
            # v2.8.2：503 瞬时过载，跳过这条试下一条；全都没中时按 aborted 返回。
            saw_busy = True
            continue
        except Exception:  # noqa: BLE001  单条查询失败不该影响后续查询
            continue
        hit, detail = pick_best_detail(as_hits(payload), title, artist,
                                       duration_ms, album)
        if hit is None or detail is None:
            continue
        if detail.score > best_score:
            best, best_score = hit, detail.score
        if best_score >= threshold:
            break

    return best, (best is None and saw_busy)


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
