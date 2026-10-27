# -*- coding: utf-8 -*-
"""联网歌词匹配（LRCLIB，公开免费、无需 API key）。

定位：**本地优先，联网兜底**。仅当「手动绑定 / 同名 .lrc / 内嵌歌词 / 本地缓存」
都没有时，才按「歌名 + 艺人」向 LRCLIB 检索；命中后缓存到
`%APPDATA%/轻音播放器/lyrics_cache/<track_id>.lrc`，之后离线也能显示。

为什么把网络请求留在 app 层：解析与选曲逻辑是纯函数，可以完全离线单测；
真正的 HTTP 通过 `fetch` 参数注入，测试不联网。
"""
from __future__ import annotations

import contextlib
import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from app.paths import lyrics_cache_dir

SEARCH_URL = "https://lrclib.net/api/search"
USER_AGENT = "QingYinPlayer/2.2 (+local desktop music player)"
CACHE_SUFFIX = ".lrc"


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


def build_search_url(title: str, artist: str) -> str:
    params = urllib.parse.urlencode({
        "track_name": title or "",
        "artist_name": artist or "",
    })
    return f"{SEARCH_URL}?{params}"


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


def _norm(text: str) -> str:
    """归一化：小写 + 只留字母数字（含中文），用来做包含式比对。"""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def _score(hit: LyricHit, title: str, artist: str, want: float) -> tuple[float, bool]:
    """返回 (得分, 是否有身份信号)。没有身份信号的结果一律丢弃，避免匹配到别的歌。"""
    score = 0.0
    identity = False
    hn, ha = _norm(hit.track_name), _norm(hit.artist_name)
    if title and hn and (title in hn or hn in title):
        score += 2.0
        identity = True
    if artist and ha and (artist in ha or ha in artist):
        score += 1.0
        identity = True
    if want and hit.duration:
        diff = abs(hit.duration - want)
        if diff <= 3:
            score += 3.0
            identity = True
        elif diff <= 10:
            score += 1.0
    if hit.synced:
        score += 0.5      # 有同步歌词优先于纯文本
    return score, identity


def pick_best(hits: list[LyricHit], title: str, artist: str,
              duration_ms: int = 0) -> LyricHit | None:
    """在候选里选最可信的一条；没有「对得上」的信号就不猜。"""
    t, a = _norm(title), _norm(artist)
    want = duration_ms / 1000.0 if duration_ms else 0.0
    best: LyricHit | None = None
    best_score = float("-inf")
    for hit in hits:
        if hit.instrumental or not hit.text:
            continue
        score, identity = _score(hit, t, a, want)
        if not identity:
            continue
        if score > best_score:
            best, best_score = hit, score
    return best


def fetch_lyrics(title: str, artist: str, duration_ms: int = 0,
                 timeout: float = 6.0, fetch=None) -> str | None:
    """检索并返回最合适的歌词原文；任何网络/解析异常都返回 None（静默降级）。"""
    fetch = fetch or _http_get_json
    try:
        payload = fetch(build_search_url(title, artist), timeout)
    except Exception:  # noqa: BLE001  网络不可用时不该影响播放
        return None
    hit = pick_best(parse_hits(payload), title, artist, duration_ms)
    return hit.text if hit else None


def _http_get_json(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8", "replace"))


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


class LyricsFetchWorker(QThread):
    """后台联网抓歌词：成功发 `found(track_id, 歌词原文)`，失败静默结束。

    放 QThread 是为了不阻塞 UI；调用方自己持有引用并 connect `finished` 清理。
    """

    found = Signal(str, str)

    def __init__(self, track_id: str, title: str, artist: str,
                 duration_ms: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._track_id = track_id
        self._title = title
        self._artist = artist
        self._duration_ms = duration_ms

    def run(self) -> None:
        text = fetch_lyrics(self._title, self._artist, self._duration_ms)
        if text:
            self.found.emit(self._track_id, text)

