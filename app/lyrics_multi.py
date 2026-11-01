# -*- coding: utf-8 -*-
"""多源联网歌词：LRCLIB + 网易云音乐 + QQ 音乐，并行取最优。

定位：LRCLIB 对英文歌强、对中国流行歌一般；网易云 / QQ 补上中文这块。
三个源**并行**检索，各自产出「已带歌词、通过身份门槛」的候选，最后统一用
`lyrics_online.pick_best` 跨源打分选最优——哪个源最可信就取哪个，某一路挂掉
自动被其它源兜住，不拖垮整体。

为什么「命中即离线可用」依然成立：多源命中的歌词原文会由调用方（主窗口）
写进 `lyrics_cache/<id>.lrc`，之后断网照常显示，和之前 LRCLIB 单源完全一致。

所有真实 HTTP 都通过 `fetch` 注入（签名 `(url, timeout) -> payload`），
本文件默认实现带各平台要求的 `Referer` 头（QQ 缺了直接返回 -1310），测试不联网。

接口事实（2026 实测，非官方，可能失效——所以做成降级链，任何源失败都不影响其余）：
- 网易云：搜索 `music.163.com/api/search/get?s={kw}&type=1&limit=8`，
  歌词 `music.163.com/api/song/lyric?id={id}&lv=1&kv=1&tv=-1`，均需
  `Referer: music.163.com/`；返回 `{lrc:{lyric: "..."}}` 标准 LRC。
- QQ：搜索 `c.y.qq.com/soso/fcgi-bin/client_search_cp?w={kw}&format=json&n=8&p=1`，
  歌词 `c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid={mid}&format=json&nobase64=1`，
  均需 `Referer: y.qq.com/`；`nobase64=1` 直接返回明文 LRC。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QThread, Signal

from app.lyrics_match import (
    CONF_LOW,
    CONSENSUS_BONUS,
    CONSENSUS_BONUS_MAX,
    MatchDetail,
    same_lyrics,
)
from app.lyrics_online import (
    DEFAULT_TIMEOUT,
    LyricHit,
    build_web_search_url,
    clean_artist,
    clean_title,
    fetch_best_hit,
    pick_best,
    score_hit_detail,
    usable_text,
)

# 网易云 / QQ 都要求「像浏览器」的 UA + Referer，缺了会被拒（QQ 歌词直接 -1310）。
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

NETEASE_REFERER = "https://music.163.com/"
NETEASE_SEARCH_URL = "https://music.163.com/api/search/get"
NETEASE_LYRIC_URL = "https://music.163.com/api/song/lyric"

QQ_REFERER = "https://y.qq.com/"
QQ_SEARCH_URL = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
QQ_LYRIC_URL = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"

# 每个源最多试几个搜索候选去拉歌词。网易云伴奏版常排第一且无歌词，
# 所以要遍历候选，找到第一个「有歌词且通过身份门槛」的（见 _pick_lyric）。
CANDIDATE_LIMIT = 3


# ---------- URL 构造 ----------


def build_netease_search_url(keyword: str, limit: int = 8) -> str:
    params = urllib.parse.urlencode({"s": keyword or "", "type": 1, "limit": limit})
    return f"{NETEASE_SEARCH_URL}?{params}"


def build_netease_lyric_url(song_id) -> str:
    params = urllib.parse.urlencode({"id": song_id, "lv": 1, "kv": 1, "tv": -1})
    return f"{NETEASE_LYRIC_URL}?{params}"


def build_qq_search_url(keyword: str, n: int = 8, p: int = 1) -> str:
    params = urllib.parse.urlencode({"w": keyword or "", "format": "json", "n": n, "p": p})
    return f"{QQ_SEARCH_URL}?{params}"


def build_qq_lyric_url(song_mid: str) -> str:
    params = urllib.parse.urlencode({"songmid": song_mid, "format": "json", "nobase64": 1})
    return f"{QQ_LYRIC_URL}?{params}"


# ---------- 解析 ----------


def parse_netease_search(payload) -> list[dict]:
    """网易云搜索结果 → [{id, title, artist, album, duration_sec}]，容忍脏数据。"""
    out: list[dict] = []
    if not isinstance(payload, dict):
        return out
    result = payload.get("result")
    if not isinstance(result, dict):
        return out
    songs = result.get("songs")
    if not isinstance(songs, list):
        return out
    for song in songs:
        if not isinstance(song, dict):
            continue
        try:
            song_id = int(song.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if not song_id:
            continue
        artist = ""
        artists = song.get("artists")
        if isinstance(artists, list) and artists and isinstance(artists[0], dict):
            artist = str(artists[0].get("name") or "")
        album = ""
        alb = song.get("album")
        if isinstance(alb, dict):
            album = str(alb.get("name") or "")
        try:
            duration_ms = int(song.get("duration") or 0)
        except (TypeError, ValueError):
            duration_ms = 0
        out.append({
            "id": song_id,
            "title": str(song.get("name") or ""),
            "artist": artist,
            "album": album,
            "duration_sec": duration_ms // 1000,
        })
    return out


def parse_netease_lyric(payload) -> str | None:
    """网易云歌词 → LRC 文本；无歌词/异常一律 None。"""
    if not isinstance(payload, dict):
        return None
    lrc = payload.get("lrc")
    if isinstance(lrc, dict):
        text = lrc.get("lyric")
        if isinstance(text, str) and text.strip():
            return text
    return None


def parse_qq_search(payload) -> list[dict]:
    """QQ 搜索结果 → [{mid, title, artist, album, duration_sec}]，容忍脏数据。"""
    out: list[dict] = []
    if not isinstance(payload, dict):
        return out
    data = payload.get("data")
    if not isinstance(data, dict):
        return out
    song = data.get("song")
    if not isinstance(song, dict):
        return out
    items = song.get("list")
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("songmid") or "").strip()
        if not mid:
            continue
        artist = ""
        singers = item.get("singer")
        if isinstance(singers, list) and singers and isinstance(singers[0], dict):
            artist = str(singers[0].get("name") or "")
        try:
            interval = int(item.get("interval") or 0)
        except (TypeError, ValueError):
            interval = 0
        out.append({
            "mid": mid,
            "title": str(item.get("songname") or ""),
            "artist": artist,
            "album": str(item.get("albumname") or ""),
            "duration_sec": interval,
        })
    return out


def parse_qq_lyric(payload) -> str | None:
    """QQ 歌词 → LRC 文本。成功码是 `retcode` 或 `code` 之一，0 表示成功。"""
    if not isinstance(payload, dict):
        return None
    code = payload.get("retcode", payload.get("code", 0))
    if code not in (0, "0"):
        return None
    text = payload.get("lyric")
    if isinstance(text, str) and text.strip():
        return text
    return None


# ---------- 网络 ----------


def _http_json(url: str, timeout: float, referer: str):
    """GET 并解析 JSON。`referer` 是平台要求的来源头（QQ 缺了会 -1310）。"""
    request = urllib.request.Request(url, headers={
        "User-Agent": BROWSER_UA,
        "Referer": referer,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        raw = response.read()
    return json.loads(raw.decode("utf-8", "replace"))


def _netease_http(url: str, timeout: float):
    return _http_json(url, timeout, NETEASE_REFERER)


def _qq_http(url: str, timeout: float):
    return _http_json(url, timeout, QQ_REFERER)


# ---------- 候选挑选（网易云 / QQ 共用） ----------


def _search_keyword(title: str, artist: str) -> str:
    """搜索关键词：优先清洗后的标题，标题空则退艺人。艺人靠打分过滤，不进关键词。"""
    return clean_title(title) or clean_artist(artist) or (title or "").strip()


def _pick_lyric(candidates: list[dict], title: str, artist: str, duration_ms: int,
                timeout: float, fetch, lyric_url_fn, lyric_parse_fn,
                album: str = "") -> LyricHit | None:
    """对前 N 个候选逐个拉歌词，选「通过身份门槛」的最佳。

    网易云伴奏版常排第一且无歌词，只试第一个会漏掉正版，所以遍历候选，
    每个候选拉歌词 → 转 `LyricHit` → 交给 `pick_best`（它已经内建「标题对上或
    时长差 ≤2s」的门槛与同步稿优先），宁可没结果也不配错词。
    """
    hits: list[LyricHit] = []
    for cand in candidates[:CANDIDATE_LIMIT]:
        try:
            payload = fetch(lyric_url_fn(cand), timeout)
        except Exception:  # noqa: BLE001  单条候选失败不影响下一个
            continue
        lrc = lyric_parse_fn(payload)
        if not lrc or not usable_text(lrc):
            continue
        hits.append(LyricHit(
            track_name=str(cand.get("title") or ""),
            artist_name=str(cand.get("artist") or ""),
            album_name=str(cand.get("album") or ""),
            duration=int(cand.get("duration_sec") or 0),
            synced=lrc,
            plain=None,
            instrumental=False,
        ))
    return pick_best(hits, title, artist, duration_ms, album)


# ---------- 各源入口 ----------


def fetch_netease(title: str, artist: str, duration_ms: int = 0,
                  timeout: float = DEFAULT_TIMEOUT, fetch=None,
                  album: str = "") -> tuple[LyricHit | None, bool]:
    """网易云源：搜索 → 遍历候选拉歌词 → 返回通过门槛的最佳 `(hit, aborted)`。"""
    fetch = fetch or _netease_http
    keyword = _search_keyword(title, artist)
    if not keyword:
        return None, False
    try:
        payload = fetch(build_netease_search_url(keyword), timeout)
    except Exception:  # noqa: BLE001  断网/被拒 → 该源降级，还有别的源兜底
        return None, False
    hit = _pick_lyric(parse_netease_search(payload), title, artist, duration_ms,
                      timeout, fetch, build_netease_lyric_url, parse_netease_lyric,
                      album)
    return hit, False


def fetch_qq(title: str, artist: str, duration_ms: int = 0,
             timeout: float = DEFAULT_TIMEOUT, fetch=None,
             album: str = "") -> tuple[LyricHit | None, bool]:
    """QQ 源：搜索 → 遍历候选拉歌词 → 返回通过门槛的最佳 `(hit, aborted)`。"""
    fetch = fetch or _qq_http
    keyword = _search_keyword(title, artist)
    if not keyword:
        return None, False
    try:
        payload = fetch(build_qq_search_url(keyword), timeout)
    except Exception:  # noqa: BLE001
        return None, False
    hit = _pick_lyric(parse_qq_search(payload), title, artist, duration_ms,
                      timeout, fetch, build_qq_lyric_url, parse_qq_lyric, album)
    return hit, False


def _lrclib_source(title: str, artist: str, duration_ms: int, timeout: float,
                   fetch, album: str) -> tuple[LyricHit | None, bool]:
    """LRCLIB 源：复用 `lyrics_online.fetch_best_hit`，返回 `(hit, aborted)`。"""
    return fetch_best_hit(title, artist, duration_ms, timeout, fetch, album)


# 源列表顺序即「同分时优先」的顺序：LRCLIB 是官方稳定源，放最前。
DEFAULT_SOURCES: list[tuple[str, object]] = [
    ("LRCLIB", _lrclib_source),
    ("网易云", fetch_netease),
    ("QQ音乐", fetch_qq),
]


# ---------- 手动在线搜索（给人看的网页，v3.0.4） ----------
#
# 自动三源都没命中时，右键「在线搜索歌词」让用户去网页自己找。原来只开
# lrclib.net，中文歌往往在那儿搜不到——这次按自动源的同一份清单，给每个
# 平台一个「给人看的」搜索地址（不是 JSON API），让用户能去最可能命中的平台兜底。

# 各平台网页搜索模板，`{q}` 处填 URL 编码后的「标题 艺人」。
# LRCLIB 复用 `lyrics_online.build_web_search_url`，不在两处各写一遍编码逻辑。
WEB_SEARCH_TEMPLATES = {
    "网易云": "https://music.163.com/#/search/m/?s={q}&type=1",
    "QQ音乐": "https://y.qq.com/n/ryqq/search?w={q}&t=song",
}


def build_web_search_urls(title: str, artist: str = "") -> list[tuple[str, str]]:
    """为各自动源构造网页搜索地址，返回 `[(平台名, url)]`（顺序同 DEFAULT_SOURCES）。

    与 `lyrics_online.build_web_search_url`（只拼 LRCLIB）互补：这里覆盖全部自动源，
    供右键「在线搜索歌词」子菜单使用。纯字符串拼接，可离线单测。
    """
    keyword = " ".join(p for p in ((title or "").strip(), (artist or "").strip()) if p)
    q = urllib.parse.quote_plus(keyword)
    out: list[tuple[str, str]] = []
    for name, _fn in DEFAULT_SOURCES:
        if name == "LRCLIB":
            out.append((name, build_web_search_url(title, artist)))
            continue
        template = WEB_SEARCH_TEMPLATES.get(name)
        if template:
            out.append((name, template.format(q=q)))
    return out


def web_search_url(platform: str, title: str, artist: str = "") -> str:
    """取指定平台的网页搜索地址；平台未知时返回空串（调用方据此提示）。"""
    for name, url in build_web_search_urls(title, artist):
        if name == platform:
            return url
    return ""


# ---------- 多源协调 ----------


def _best_with_source(pairs: list[tuple[str, LyricHit]], title: str, artist: str,
                      duration_ms: int, album: str = "") -> tuple[LyricHit | None, str]:
    """自 3.0.5 起由 `pick_with_consensus` 取代；保留只为不破坏可能有外部调用。

    新逻辑多了「跨源投票」与「low 置信档拒收」两件事，直接用新函数。
    """
    best = pick_best([hit for _, hit in pairs], title, artist, duration_ms, album)
    if best is None:
        return None, ""
    for source, hit in pairs:
        if hit is best:
            return best, source
    return best, pairs[0][0]


# ---------- 跨源投票（v3.0.5） ----------
#
# 单源命中有个固有风险：某个平台把「同名不同曲」排在第一，而它的身份信号
# 又恰好勉强过关（比如只靠时长对上）。三个源同时给出**逐字相同的歌词正文**时，
# 几乎可以断定就是这一版；只有一个源说「是它」时，就该多一分怀疑。
#
# 所以给「有共识的候选」加分，但**上限只有 1.2**——投票是用来打破平局的，
# 不该盖过身份信号（一个源标题精确 vs 三个源标题全错，仍然要选前者）。


def consensus_sources(pairs: list[tuple[str, LyricHit]], index: int,
                      threshold: float = 0.85) -> list[str]:
    """统计有多少个源给出的歌词正文与 `pairs[index]` 一致（含自己）。"""
    if not pairs or not 0 <= index < len(pairs):
        return []
    base = pairs[index][1].text
    if not base:
        return []
    agreed: list[str] = []
    for source, hit in pairs:
        if (hit.text and same_lyrics(base, hit.text, threshold)
                and source not in agreed):
            agreed.append(source)
    return agreed


def pick_with_consensus(pairs: list[tuple[str, LyricHit]], title: str, artist: str,
                        duration_ms: int = 0, album: str = "",
                        allow_low: bool = False,
                        ) -> tuple[LyricHit | None, str, MatchDetail | None, list[str]]:
    """跨源投票选最优，返回 `(hit, 来源, 打分详情, 一致的源名)`。

    流程：每个源先按身份信号打分 → 计数「有几个源给了同一份歌词」→
    总分 = 身份分 + 共识加分（`CONSENSUS_BONUS`/源，上限 `CONSENSUS_BONUS_MAX`）
    → 取最高分。平票时保持 `pairs` 的原始顺序（即 `DEFAULT_SOURCES` 的优先级），
    因为 LRCLIB 是唯一有官方文档的源，同分时它更可信。
    """
    if not pairs:
        return None, "", None, []

    want = duration_ms / 1000.0 if duration_ms else 0.0
    scored: list[tuple[float, int, MatchDetail, list[str]]] = []
    for index, (_source, hit) in enumerate(pairs):
        detail = score_hit_detail(hit, title, artist, want, album)
        if not detail.gate:
            continue
        if detail.confidence == CONF_LOW and not allow_low:
            continue
        agreed = consensus_sources(pairs, index)
        bonus = min(CONSENSUS_BONUS * (len(agreed) - 1), CONSENSUS_BONUS_MAX)
        scored.append((detail.score + max(bonus, 0.0), index, detail, agreed))

    if not scored:
        return None, "", None, []

    # 分数降序、下标升序（同分时保持源顺序），两个键都要显式写
    _ranked, index, detail, agreed = max(scored, key=lambda item: (item[0], -item[1]))
    hit = pairs[index][1]
    return hit, pairs[index][0], detail, agreed


def fetch_outcome_multi(title: str, artist: str, duration_ms: int = 0,
                        timeout: float = DEFAULT_TIMEOUT, fetches=None,
                        album: str = "", progress=None, parallel: bool = True,
                        sources=None, detail_sink: dict | None = None,
                        ) -> tuple[str | None, str, bool]:
    """多源并行检索歌词，返回 `(歌词原文, 来源名, 是否中止)`。

    `fetches` 可按来源名注入 fetch（`{"LRCLIB": fn, "网易云": fn, ...}`），
    测试不联网；`progress(done, total, source_name)` 每返回一个源上报一次，
    第三个参数是**刚返回的那个源名**（v2.7.7）。
    `parallel=False` 串行执行（测试用，结果与并行一致但无线程）。
    `aborted=True` 表示「至少一个源被限流/超时且全都没命中」，此时调用方
    绝不能写负缓存——一次网络抖动不等于这首歌没有歌词。
    `detail_sink`（v3.0.5）可选：传入一个 dict，命中时会被填入
    `{"score","confidence","title_sim","artist_sim","consensus"}`，
    供界面/日志解释「为什么是这一条」。**返回值签名保持不变**，因为这些
    细节是诊断信息，不该污染主调用路径。
    """
    sources = sources if sources is not None else DEFAULT_SOURCES
    if not sources:
        return None, "", False
    if not clean_title(title) and not clean_artist(artist):
        return None, "", False

    fetches = fetches or {}
    results: list[tuple[str, LyricHit | None, bool]] = []

    def _run_one(source_name: str, source_fn) -> tuple[str, LyricHit | None, bool]:
        fetch = fetches.get(source_name)
        hit, aborted = source_fn(title, artist, duration_ms, timeout, fetch, album)
        return source_name, hit, aborted

    total = len(sources)
    done = 0
    if parallel and total > 1:
        with ThreadPoolExecutor(max_workers=total) as pool:
            futures = [pool.submit(_run_one, name, fn) for name, fn in sources]
            for future in as_completed(futures):
                # v2.7.7：把「刚返回的源名」一并报上去。并行模式下三个源是同时
                # 发出的，所以只能说「谁回来了」，不能说「正在查谁」—— 进度文案
                # 必须如实反映这一点，否则界面显示的就是一句假话。
                source_name, hit, aborted = future.result()
                results.append((source_name, hit, aborted))
                done += 1
                if progress is not None:
                    progress(done, total, source_name)
    else:
        for name, fn in sources:
            results.append(_run_one(name, fn))
            done += 1
            if progress is not None:
                progress(done, total, name)

    pairs = [(name, hit) for name, hit, _ in results if hit is not None]
    any_aborted = any(aborted for _, _, aborted in results)
    if pairs:
        best, source, detail, agreed = pick_with_consensus(
            pairs, title, artist, duration_ms, album)
        if best is not None:
            if detail_sink is not None:
                detail_sink.update({
                    "score": detail.score,
                    "confidence": detail.confidence,
                    "title_sim": detail.title_sim,
                    "artist_sim": detail.artist_sim,
                    "album_sim": detail.album_sim,
                    "duration_diff": detail.duration_diff,
                    "reasons": detail.reasons,
                    "consensus": agreed,
                })
            return best.text, source, False
    return None, "", any_aborted


# ---------- 后台线程 ----------


class MultiSourceWorker(QThread):
    """后台多源联网抓歌词：命中发 `found(track_id, 歌词, 来源)`，确认没找到发
    `missed(track_id)`，被限流/超时中止发 `aborted(track_id)`（不落负缓存）。

    与 `lyrics_online.LyricsFetchWorker` 的区别只在两点：跑多源而非单源，
    `found` 多带一个来源名（"LRCLIB" / "网易云" / "QQ音乐"）供界面显示。
    `progress(done, total, names)` 按源上报，`names` 是「到目前为已返回的平台」，
    形如 `"LRCLIB、网易云"`，界面据此显示「正在匹配 2/3（LRCLIB、网易云 已返回）」。
    """

    found = Signal(str, str, str)
    missed = Signal(str)
    aborted = Signal(str)
    # v2.7.7：(已完成源数, 源总数, 已返回的源名，用「、」连接)
    # 第三个参数让人能看见"到底查了哪些平台"，不再只有一个 1/3 的数字。
    progress = Signal(int, int, str)

    def __init__(self, track_id: str, title: str, artist: str,
                 duration_ms: int = 0, album: str = "", parent=None) -> None:
        super().__init__(parent)
        self._track_id = track_id
        self._title = title
        self._artist = artist
        self._duration_ms = duration_ms
        self._album = album

    def run(self) -> None:
        # v2.7.7：累积已返回的源名。并行模式下各源回来的顺序不固定，
        # 所以每次上报都带上"到目前为止谁回来了"，而不是只报"正在查谁"。
        returned: list[str] = []

        def _report(done: int, total: int, source_name: str = "") -> None:
            if source_name and source_name not in returned:
                returned.append(source_name)
            self.progress.emit(done, total, "、".join(returned))

        text, source, aborted = fetch_outcome_multi(
            self._title, self._artist, self._duration_ms,
            album=self._album, progress=_report)
        # v2.7.5：窗口已经关掉就别再发信号了。
        # 主窗口关闭时会先 requestInterruption() 再 wait()，但多源抓取是并行
        # 线程池，请求发出去就收不回来（单源超时 4.5s）。这条检查保证「即使
        # 线程晚一步收工，也不会把信号投递给正在析构的窗口」。
        if self.isInterruptionRequested():
            return
        if text:
            self.found.emit(self._track_id, text, source)
        elif aborted:
            self.aborted.emit(self._track_id)
        else:
            self.missed.emit(self._track_id)
