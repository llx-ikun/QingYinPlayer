# -*- coding: utf-8 -*-
"""联网歌词对齐（LyricTimestamps，把纯文本歌词配到音频时间轴，产出 LRC）。

定位：仅当用户导入了**纯文本歌词**（无时间戳、无法跟歌滚动）时，作为把纯文本
转成带时间轴 LRC 的兜底手段。需要用户自备 API key（服务不免密钥），且会把本地
音频上传到第三方服务器——这是「联网自动对齐」的固有代价，触发前界面已说明。

服务端 API（https://api.lyrictimestamps.com，照 docs 实现不猜）：
- POST /v1/alignments        multipart 上传 audio_file + lyrics_text，201 返回 job_id；
- GET  /v1/alignments/{id}   轮询状态（queued→…→done/failed），done 可能带 soft_fail；
- GET  /v1/alignments/{id}/exports/lrc   直接返回 LRC 文件内容；
- GET  /v1/usage             校验 key（plan != anonymous 才算有效）。

关键坑（均来自 docs 的 "Things that trip people"）：
- 必须 form data，不能 JSON——JSON body 会被静默接受然后 `400 missing_audio`；
- 错误 key 在**创建任务**时 401，但在**读端点**会被当匿名游客（只回 60 秒预览），
  所以必须先 `verify_key` 再创建任务，否则会拿到「只有前 60 秒」的残缺结果；
- `/exports/lrc` 的响应就是文件本身，没有签名 URL、也不会过期。
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

from app.lyrics import (format_lrc, pair_bilingual, parse_lrc, parse_plain,
                        strip_meta_lines)

ALIGN_BASE = "https://api.lyrictimestamps.com"
USER_AGENT = "QingYinPlayer/2.6.7 (+local desktop music player)"

# 直传上限 30MB（两段式上传 120MB 暂不接，超了直接提示「文件过大」）。
DIRECT_UPLOAD_LIMIT = 30 * 1024 * 1024
# 免费档单曲上限 12 分钟。
MAX_SONG_SECONDS = 12 * 60
# 服务端 accepted files（照 docs 抄，用于本地提前拦截明显不支持的格式）。
SUPPORTED_EXTENSIONS = (
    ".aac", ".aif", ".aiff", ".avi", ".flac", ".m4a", ".m4v", ".mkv",
    ".mov", ".mp3", ".mp4", ".oga", ".ogg", ".opus", ".wav", ".webm", ".wma",
)

# 轮询间隔与整轮墙钟预算。对齐一首歌通常 1~2 分钟。
POLL_INTERVAL = 2.5
TOTAL_BUDGET = 180.0


@dataclass(frozen=True)
class AlignOutcome:
    """一次对齐的结果。

    - 成功：`lrc` 有值、`error_code` 为空；
    - `soft_fail`：服务端「完成但不可信」，`lrc` 仍给出，界面提示核对；
    - 失败：`lrc` 为空、`error_code` 非空，`describe_error` 转中文提示。
    """

    lrc: str | None = None
    soft_fail: bool = False
    error_code: str = ""
    error_message: str = ""


# 错误码 → 中文提示。本地预检码与第三方服务端码（docs 里的 code）混排在一起，
# 统一走这一个映射；未知码由调用方用 `error_message` 兜底。
_ERROR_MESSAGES = {
    "missing_key": "未填写歌词对齐 Key，请到「设置 → 歌词与统计」填写",
    "no_audio": "音频文件不存在或不可读",
    "file_too_large": "音频超过 30MB，超出对齐服务的直传上限",
    "unsupported_format": "该文件格式暂不支持对齐",
    "read_failed": "读取音频文件失败",
    "no_lyrics": "没有可对齐的歌词文本",
    "invalid_api_key": "对齐 Key 无效或已失效，请到设置里重新填写",
    "song_too_long": "歌曲超过 12 分钟，超出免费档单曲上限",
    "limit_reached": "本月对齐额度已用完（15 分钟/月），下月自动恢复",
    "missing_audio": "音频上传失败",
    "duplicate_in_progress": "同一首歌正在对齐中，请稍候",
    "network": "网络错误，请检查网络后重试",
    "timeout": "对齐超时，请重试",
    "failed": "对齐失败",
    "bad_response": "服务返回异常，请重试",
    "temporarily_unavailable": "服务暂时不可用，稍后再试",
    "job_not_found": "对齐任务不存在，请重试",
}


def describe_error(code: str) -> str:
    """错误码 → 中文提示。未知码给一句通用兜底。"""
    if not code:
        return ""
    return _ERROR_MESSAGES.get(code, "对齐失败，请重试")


# ---------- HTTP 底层 ----------
#
# 与 lyrics_online 一样，真正的 HTTP 通过 `fetch` 参数注入，测试不联网。
# 这里比 lyrics_online 多一个 method/body 维度，所以注入签名是
# `fetch(method, url, headers, body, timeout) -> _Response`。


@dataclass
class _Response:
    status: int
    body: bytes
    content_type: str = ""


def _http(method: str, url: str, headers: dict, body: bytes | None = None,
          timeout: float = 30.0) -> _Response:
    """用 urllib 发请求，返回 (status, body, content-type)。"""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return _Response(
                status=response.status,
                body=response.read(),
                content_type=response.headers.get("Content-Type", ""),
            )
    except urllib.error.HTTPError as exc:
        return _Response(status=exc.code, body=exc.read() or b"",
                         content_type=exc.headers.get("Content-Type", ""))


def _safe_filename(name: str) -> str:
    """Content-Disposition 的 filename 转义：去掉引号/反斜杠/换行，避免破坏头。"""
    return re.sub(r'["\\\r\n]', "_", name or "audio")


def _build_multipart(audio_bytes: bytes, filename: str, lyrics_text: str) -> tuple[str, bytes]:
    """拼 multipart/form-data：audio_file + lyrics_text。返回 (content_type, body)。"""
    boundary = "----QingYin" + uuid.uuid4().hex
    safe = _safe_filename(filename)
    parts = [
        (f"--{boundary}\r\n"
         f'Content-Disposition: form-data; name="audio_file"; filename="{safe}"\r\n'
         f"Content-Type: application/octet-stream\r\n\r\n").encode("utf-8"),
        audio_bytes,
        b"\r\n",
        (f"--{boundary}\r\n"
         f'Content-Disposition: form-data; name="lyrics_text"\r\n\r\n').encode("utf-8"),
        lyrics_text.encode("utf-8"),
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


def _restore_translations(lrc: str, subs: list[str]) -> str:
    """把译文按行序回填到对齐结果，写成「同时间戳两行」。

    行数对不上就原样返回：服务端可能合并/拆分行，硬按索引配对会把译文挂到错的
    句子上——配错词比没词更糟。
    """
    if not any(subs or []):
        return lrc
    lines = parse_lrc(lrc)
    if len(lines) != len(subs):
        return lrc
    for line, sub in zip(lines, subs, strict=True):
        line.translation = sub
    return format_lrc(lines).strip() or lrc


def _parse_json(resp: _Response) -> dict:
    try:
        data = json.loads(resp.body.decode("utf-8", "replace"))
        return data if isinstance(data, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def _error_outcome(resp: _Response) -> AlignOutcome:
    """把服务端错误响应转成 AlignOutcome；解析不出 code 就按 HTTP 状态兜底。"""
    data = _parse_json(resp)
    code = str(data.get("code") or "")
    if not code and resp.status == 401:
        code = "invalid_api_key"
    if not code and resp.status == 413:
        code = "file_too_large"
    if not code and resp.status == 429:
        code = "limit_reached"
    return AlignOutcome(error_code=code, error_message=str(data.get("message") or ""))


def verify_key(api_key: str, fetch=None, timeout: float = 15.0) -> bool:
    """GET /v1/usage 校验 key。有效 = 返回 200 且 plan != anonymous（或有 tier）。"""
    if not (api_key or "").strip():
        return False
    fetch = fetch or _http
    headers = {"Authorization": f"Bearer {api_key.strip()}", "User-Agent": USER_AGENT}
    try:
        resp = fetch("GET", f"{ALIGN_BASE}/v1/usage", headers, None, timeout)
    except Exception:  # noqa: BLE001
        return False
    if resp.status != 200:
        return False
    data = _parse_json(resp)
    plan = str(data.get("plan") or "")
    tier = data.get("tier")
    return plan != "anonymous" or bool(tier)


def align_lyrics(audio_path: str, lyrics_text: str, api_key: str, fetch=None,
                 progress=None, poll_interval: float = POLL_INTERVAL,
                 budget: float = TOTAL_BUDGET) -> AlignOutcome:
    """把纯文本歌词对齐到音频，返回 LRC。

    `progress(percent:int, stage:str)` 可选回调，供 UI 显示进度。
    `fetch` 可注入（测试不联网）；`poll_interval`/`budget` 供测试调快。
    """
    fetch = fetch or _http
    api_key = (api_key or "").strip()
    lyrics_text = (lyrics_text or "").strip()

    # 双语歌词（原文行 / 译文行交替）只把**原文**交给服务对齐：把译文也发过去，
    # 服务端只能按行数分配时间轴，行数翻倍会让整首错位、译文还晚半句。
    # 拿回 LRC 后再按行序把译文回填成「同时间戳第二行」。
    rows: list[tuple[str, str]] = []
    upload_text = lyrics_text
    if lyrics_text and not parse_lrc(lyrics_text):
        rows = pair_bilingual(parse_plain(strip_meta_lines(lyrics_text)))
        if rows:
            upload_text = "\n".join(main for main, _sub in rows)
    subs = [sub for _main, sub in rows]

    # ---- 本地预检（把能提前拦的拦掉，不白传 30MB）----
    if not api_key:
        return AlignOutcome(error_code="missing_key")
    if not lyrics_text:
        return AlignOutcome(error_code="no_lyrics")
    if not os.path.isfile(audio_path):
        return AlignOutcome(error_code="no_audio")
    ext = os.path.splitext(audio_path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return AlignOutcome(error_code="unsupported_format")
    try:
        size = os.path.getsize(audio_path)
    except OSError:
        return AlignOutcome(error_code="no_audio")
    if size > DIRECT_UPLOAD_LIMIT:
        return AlignOutcome(error_code="file_too_large")
    try:
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
    except OSError:
        return AlignOutcome(error_code="read_failed")

    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT}

    # ---- 0. 先校验 key（否则读端点会把错误 key 当匿名游客，只回 60 秒预览）----
    if progress is not None:
        progress(3, "校验对齐 Key…")
    if not verify_key(api_key, fetch=fetch):
        return AlignOutcome(error_code="invalid_api_key")

    # ---- 1. 创建任务（multipart 上传音频 + 歌词）----
    if progress is not None:
        progress(8, "上传音频与歌词…")
    content_type, body = _build_multipart(audio_bytes, os.path.basename(audio_path), upload_text)
    try:
        resp = fetch("POST", f"{ALIGN_BASE}/v1/alignments",
                     {**headers, "Content-Type": content_type}, body, timeout=120.0)
    except Exception:  # noqa: BLE001
        return AlignOutcome(error_code="network")
    if resp.status not in (200, 201):
        return _error_outcome(resp)
    job_id = str(_parse_json(resp).get("job_id") or "")
    if not job_id:
        return AlignOutcome(error_code="bad_response")

    # ---- 2. 轮询直到 done / failed ----
    deadline = time.monotonic() + budget
    soft_fail = False
    soft_fail_code = ""
    while True:
        if time.monotonic() > deadline:
            return AlignOutcome(error_code="timeout")
        if progress is not None:
            progress(20, "对齐中，请稍候…")
        try:
            resp = fetch("GET", f"{ALIGN_BASE}/v1/alignments/{job_id}",
                         headers, None, timeout=30.0)
        except Exception:  # noqa: BLE001
            return AlignOutcome(error_code="network")
        if resp.status != 200:
            return _error_outcome(resp)
        data = _parse_json(resp)
        status = str(data.get("status") or "")
        if status == "done":
            soft_fail = bool(data.get("soft_fail"))
            soft_fail_code = str(data.get("soft_fail_code") or "")
            break
        if status == "failed":
            return AlignOutcome(error_code="failed",
                                error_message=str(data.get("error") or ""))
        time.sleep(poll_interval)

    # ---- 3. 下载 LRC ----
    if progress is not None:
        progress(95, "下载时间轴…")
    try:
        resp = fetch("GET", f"{ALIGN_BASE}/v1/alignments/{job_id}/exports/lrc",
                     headers, None, timeout=30.0)
    except Exception:  # noqa: BLE001
        return AlignOutcome(error_code="network")
    if resp.status != 200:
        return _error_outcome(resp)
    lrc = resp.body.decode("utf-8", "replace").strip()
    if not lrc:
        return AlignOutcome(error_code="bad_response")
    lrc = _restore_translations(lrc, subs)
    if progress is not None:
        progress(100, "完成")
    message = f"对齐完成，但结果可能不准（{soft_fail_code}），请核对" if soft_fail else ""
    return AlignOutcome(lrc=lrc, soft_fail=soft_fail, error_message=message)


# ---------- 同名 .lrc 落地（v2.6.7） ----------
#
# 对齐结果写成「歌曲同目录同名 .lrc」：播放器 `_resolve_lyrics` 第 2 级来源会
# 自动识别同名 .lrc（晴天.mp3 → 晴天.lrc），比写缓存更直观、可迁移、可手动管理。


def sidecar_lrc_path(audio_path: str) -> str:
    """歌曲同目录同名 .lrc 的路径（去扩展名 + .lrc）。"""
    return os.path.splitext(audio_path)[0] + ".lrc"


def write_sidecar_lrc(audio_path: str, lrc: str) -> str | None:
    """把 LRC 原子写到歌曲同目录同名 .lrc，返回写入路径；失败（目录不可写等）返回 None。

    覆盖已有同名 .lrc 前由调用方确认；这里只负责原子写，不删不改其它文件。
    """
    if not audio_path or not lrc:
        return None
    path = sidecar_lrc_path(audio_path)
    tmp = path + ".part"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(lrc)
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        return None
    return path


# ---------- 后台线程 ----------


class LyricsAlignWorker(QThread):
    """后台跑对齐：成功发 `done(track_id, lrc)`，完成但不可信发 `soft_fail(track_id, lrc)`，
    失败发 `failed(track_id, 中文提示)`。`progress(percent, stage)` 逐步上报。"""

    done = Signal(str, str)
    soft_fail = Signal(str, str)
    failed = Signal(str, str)
    progress = Signal(int, str)

    def __init__(self, track_id: str, audio_path: str, lyrics_text: str,
                 api_key: str, parent=None) -> None:
        super().__init__(parent)
        self._track_id = track_id
        self._audio_path = audio_path
        self._lyrics_text = lyrics_text
        self._api_key = api_key

    def run(self) -> None:
        def _report(percent: int, stage: str) -> None:
            self.progress.emit(percent, stage)

        outcome = align_lyrics(self._audio_path, self._lyrics_text, self._api_key,
                               progress=_report)
        if outcome.lrc:
            if outcome.soft_fail:
                self.soft_fail.emit(self._track_id, outcome.lrc)
            else:
                self.done.emit(self._track_id, outcome.lrc)
        else:
            message = describe_error(outcome.error_code) or outcome.error_message or "对齐失败"
            self.failed.emit(self._track_id, message)
