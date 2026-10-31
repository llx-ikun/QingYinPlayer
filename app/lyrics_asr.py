# -*- coding: utf-8 -*-
"""AI 强制对齐（v3.0.0）：本地 whisper 词级时间戳 → 原歌词逐字时间轴。

五层，**每层都能独立降级**：

    L1 声道预处理   stereo → mid=(L+R)/2（人声通常居中，零成本压掉宽立体声伴奏）
    L2 faster-whisper  int8 推理 → 词级时间戳
    L3 序列比对     difflib 把「识别词」映射回「原文字符」，识别错字不影响整体
    L4 能量谷吸附   把字边界挪到本句附近的能量极小点（换气/辅音起点）
    L5 置信度自检   匹配率 / 平均概率过低就判失败，**不产出半对的歌词**

**为什么必须有 L3**：whisper 在唱歌上会听错词（尤其带伴奏的中文歌）。我们需要的是
时间戳，文本用用户自己那份；把识别结果直接当歌词是错的，只取它的时间轴才对。

**为什么必须有 L5**：没有自检就会「静静地生成一份错歌词」，比不做还糟。

本模块分两半：
- L1 与 L2 依赖可选依赖（miniaudio / numpy / faster-whisper），**全部延迟导入**，
  缺任何一个都只是返回错误码，不会把主程序启动拖死；
- L3/L4/L5 与逐行装配是纯逻辑，不碰音频也不碰模型，`tests/test_lyrics_asr.py`
  用构造的词时间戳直接把它们钉死。
"""
from __future__ import annotations

import contextlib
import difflib
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

from app.lyrics import LyricLine, WordSpan
from app.lyrics_local_align import TARGET_SR, decode_mono, rms_envelope
from app.lyrics_words import save_from_lines
from app.models import DEFAULT_AI_MODEL

# ---------- 可调阈值 ----------
#
# 这几个数字是「宁可不给，也别给错」的口径，改之前先想清楚代价。

# L4：在 ±120ms 内找能量谷。再宽就会把边界挪到隔壁字上去。
SNAP_MS = 120
# 一个字最短多长。吸附后的边界不许把字压得比这更短，否则会闪一下就没。
MIN_CHAR_MS = 40
# L5：匹配率下限。低于这个数说明「唱的内容和歌词基本对不上」——
# 常见于纯音乐/哼唱/识别语言错。
MIN_MATCH_RATIO = 0.55
# L5：识别平均置信度下限。Phase 0 实测：无语音的合成音会被"听"出内容，
# 但 probability 只有 0.03~0.12；正常演唱在 0.5 以上。
MIN_MEAN_PROB = 0.25

_ERROR_MESSAGES = {
    "no_lyrics": "这首歌没有可对齐的同步歌词",
    "no_speech": "没有识别到任何人声内容",
    "model_missing": "AI 模型还没下载",
    # 这两句会接在「AI 对齐失败：」后面，所以别再重复「AI」二字
    "download_failed": "模型下载失败",
    "disk_failed": "模型写入失败（检查磁盘空间与权限）",
    "import_failed": "AI 组件缺失或不兼容",
    "decode_failed": "音频解码失败",
    "low_confidence": "识别结果与歌词对不上，已放弃（不会写入错的时间轴）",
    "cancelled": "已取消",
}


def describe_error(code: str) -> str:
    return _ERROR_MESSAGES.get(code, code or "")


@dataclass(frozen=True)
class RecognizedWord:
    """whisper 识别出的一个词（时间单位已换成毫秒）。"""

    start_ms: int
    end_ms: int
    text: str
    probability: float = 0.0


@dataclass
class AsrOutcome:
    """一次识别（L1+L2）的结果。`error` 非空时 `words` 没有意义。"""

    words: list[RecognizedWord] = field(default_factory=list)
    language: str = ""
    duration_ms: int = 0
    error: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class AlignOutcome:
    """一次逐字对齐（L3+L4+L5）的结果。"""

    lines: list[LyricLine] = field(default_factory=list)
    matched_ratio: float = 0.0
    mean_probability: float = 0.0
    # 对齐出的首字时间与原有行时间戳的最大偏差。超过 ~1s 说明这份 .lrc 的行时间
    # 本身就不准（典型：本地近似对齐出来的），只写字级数据没用——行高亮会先错位。
    max_shift_ms: int = 0
    error: str = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


# ---------- L1 声道预处理 ----------


def decode_for_asr(audio_path: str, target_sr: int = TARGET_SR):
    """解码成 mono float32 numpy 数组，并做人声中置提取。

    返回 `(pcm, sample_rate)`；numpy 缺失时退回 `array('f')`（whisper 也收）。

    **为什么要自己解码**：faster-whisper 传文件路径时会走 `av.open()`，而 av 19 删掉了
    `metadata_errors` 参数、faster-whisper 1.2.1 还在传 → 必崩。自己解码成数组喂进去
    既绕开这个雷，又能顺手做 L1，还让 `av`（68MB）可以从安装包里整个排除。

    单声道 / 伪立体声（左右几乎一致）不做中置提取：那只是把音量减半，白白降低信噪比。
    """
    with open(audio_path, "rb") as f:
        data = f.read()
    try:
        import miniaudio
    except Exception:  # noqa: BLE001 - 缺依赖就走单声道回退
        return _fallback_mono(audio_path, target_sr)

    try:
        decoded = miniaudio.decode(
            data,
            output_format=miniaudio.SampleFormat.FLOAT32,
            nchannels=2,
            sample_rate=target_sr,
        )
    except Exception:  # noqa: BLE001 - 立体声解不出来，退回单声道
        return _fallback_mono(audio_path, target_sr)

    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        return _fallback_mono(audio_path, target_sr)

    pcm = np.array(decoded.samples, dtype=np.float32)
    if pcm.size < 2:
        return _fallback_mono(audio_path, target_sr)
    if pcm.size % 2:
        pcm = pcm[:-1]
    stereo = pcm.reshape(-1, 2)
    left = stereo[:, 0]
    right = stereo[:, 1]
    if float(np.abs(left - right).mean()) < 1e-4:
        return left, decoded.sample_rate      # 伪立体声：直接取左声道
    return (left + right) * 0.5, decoded.sample_rate


def _fallback_mono(audio_path: str, target_sr: int):
    raw, sr = decode_mono(audio_path, target_sr)
    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        return raw, sr
    return np.array(raw, dtype=np.float32), sr


# ---------- L2 识别 ----------


def model_dir_for(name: str) -> str:
    """档位名 → 本地模型目录（`<数据根>/models/<name>`）。"""
    from app.paths import models_dir

    return os.path.join(models_dir(), name)


# 档位 → HuggingFace 仓库。用 Systran 的 CTranslate2 转换版，faster-whisper 直接吃。
MODEL_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
}
# 只下这几个文件：仓库里的 README / 其它框架的权重（如 model.safetensors）一律不要。
_MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
# 国内直连 HF 基本必失败，默认走镜像（用户可用 QY_HF_ENDPOINT / HF_ENDPOINT 覆盖）
DEFAULT_ENDPOINT = "https://hf-mirror.com"

# 直链：<endpoint>/<repo>/resolve/main/<file>，镜像会 302 到 CDN（v3.0.1 实测可用）
_DOWNLOAD_TIMEOUT = 30
_DOWNLOAD_RETRIES = 3
_DOWNLOAD_CHUNK = 1 << 20
_USER_AGENT = "QingYinPlayer/3.0 (+local; python-urllib)"


def download_endpoint() -> str:
    """解析下载站根地址。环境变量优先，方便换镜像而不改代码。"""
    raw = (os.environ.get("QY_HF_ENDPOINT")
           or os.environ.get("HF_ENDPOINT")
           or DEFAULT_ENDPOINT)
    return raw.strip().rstrip("/")


def model_ready(path: str) -> bool:
    """目录里四个必需文件齐了才算「可用」。

    只判目录存在是不够的：下载中断会留下一个半空的目录，之后每次加载都 segfault
    或抛 OSError，看起来像「AI 功能坏了」。宁可让它重下。
    """
    if not path or not os.path.isdir(path):
        return False
    return all(os.path.isfile(os.path.join(path, name)) for name in _MODEL_FILES)


class _DownloadError(Exception):
    """下载过程中可分类型的失败。`detail` 会原样进 toast，必须是真实原因。"""

    code = "download_failed"


class _NetworkError(_DownloadError):
    code = "download_failed"


class _DiskError(_DownloadError):
    code = "disk_failed"


def _brief(exc: BaseException) -> str:
    """异常 → 一行人能读的说明。空 message 的异常（如 URLError(None)）只留类型名。"""
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _open_part(path: str, append: bool):
    """打开 `.part` 写句柄；写不进去单独归成 `disk_failed`（磁盘满/只读/权限）。"""
    try:
        return open(path, "ab" if append else "wb")   # noqa: SIM115 - 句柄由调用方 with 关
    except OSError as exc:
        raise _DiskError(_brief(exc)) from exc


def _fetch_once(url: str, tmp: str, on_progress=None) -> None:
    """一次下载尝试：支持 Range 续传，写 `.part` 而不是目标文件。

    **为什么不用 huggingface_hub.snapshot_download**：v3.0.0 出货后用户在真实环境
    里必现「模型下载失败」，而开发态同样的代码能下完 —— 差别只在冻结产物。
    snapshot_download 一条路要背上 httpx2 / httpcore2 / anyio / fsspec / click /
    tqdm / filelock 七个三方包，任何一个被 PyInstaller 漏收就是全盘失败，而且异常
    被它自己的包装层吃掉、看不出根因。我们要的只是 4 个静态文件，标准库足够，
    错误也能分得清（v3.0.1）。
    """
    start = os.path.getsize(tmp) if os.path.isfile(tmp) else 0
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    if start:
        request.add_header("Range", f"bytes={start}-")
    try:
        response = urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and start:
            # 断点比服务器上的文件还长 —— `.part` 是坏片段，删掉从头来
            _silent_remove(tmp)
        raise
    with response:
        # 服务端不认 Range 会返回 200 + 整个文件，此时必须从头写
        resuming = response.status == 206 and start > 0
        written = start if resuming else 0
        length = int(response.headers.get("Content-Length") or 0)
        total = written + length if length > 0 else 0
        with _open_part(tmp, resuming) as handle:
            while True:
                try:
                    block = response.read(_DOWNLOAD_CHUNK)
                except OSError as exc:      # 传输中断：连接被重置 / 超时
                    raise _NetworkError(_brief(exc)) from exc
                if not block:
                    break
                try:
                    handle.write(block)
                except OSError as exc:      # 磁盘满 / 只读 / 权限
                    raise _DiskError(_brief(exc)) from exc
                written += len(block)
                if on_progress and total > 0:
                    on_progress(min(1.0, written / total))
        if total > 0 and written < total:
            raise _NetworkError(f"下载不完整（{written}/{total} 字节）")


def _silent_remove(path: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(path)


def download_file(url: str, dest: str, on_progress=None) -> tuple[str, str]:
    """把 url 下到 dest，返回 `(错误码, 详情)`；成功是 `("", "")`。

    失败重试 3 次（续传，不从头来）。4xx 除 408/429 之外立刻收手 —— 仓库改名或
    文件不存在时重试只会让用户多等三次超时。
    """
    tmp = dest + ".part"
    detail = ""
    for _attempt in range(_DOWNLOAD_RETRIES):
        try:
            _fetch_once(url, tmp, on_progress)
            os.replace(tmp, dest)       # 先 .part 后改名：不会留下「看起来完整」的半个文件
            return "", ""
        except _DownloadError as exc:
            detail = str(exc)
            if isinstance(exc, _DiskError):
                return exc.code, detail
        except urllib.error.HTTPError as exc:
            detail = f"HTTP {exc.code} {exc.reason}"
            if exc.code == 416:
                # 断点比服务器上的文件还长：`_fetch_once` 已经删掉坏片段，重来一次
                continue
            if 400 <= exc.code < 500 and exc.code not in (408, 429):
                return "download_failed", detail
        except urllib.error.URLError as exc:
            detail = _brief(exc.reason if exc.reason else exc)
        except OSError as exc:
            return "disk_failed", _brief(exc)
        except Exception as exc:  # noqa: BLE001 - 兜底也要留下真实类型
            detail = _brief(exc)
    return "download_failed", detail


def ensure_model(name: str, progress=None) -> tuple[str, str, str]:
    """确保某个档位的模型在本地，返回 `(目录, 错误码, 详情)`；已就绪不联网。

    第三项是 v3.0.1 加的：v3.0.0 把异常整个吞成 `download_failed`，界面上只剩
    「检查网络」四个字，连开发侧都无法判断到底是 DNS、HTTP 404、还是磁盘权限。
    **错误码给人看结论，详情给定位用**，两者都要。
    """
    target = model_dir_for(name)
    if model_ready(target):
        return target, "", ""
    repo = MODEL_REPOS.get(name)
    if not repo:
        return target, "model_missing", f"未知档位 {name}"
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as exc:
        return target, "disk_failed", _brief(exc)

    endpoint = download_endpoint()
    count = len(_MODEL_FILES)
    for index, file_name in enumerate(_MODEL_FILES):
        def _report(done: float, index: int = index) -> None:
            if progress:
                progress("download", (index + done) / count)

        url = f"{endpoint}/{repo}/resolve/main/{file_name}"
        code, detail = download_file(url, os.path.join(target, file_name), _report)
        if code:
            return target, code, f"{file_name}: {detail}"
    if progress:
        progress("download", 1.0)
    if not model_ready(target):
        return target, "download_failed", "下载后文件仍不完整"
    return target, "", ""


def transcribe(audio_path: str, model_dir: str, language: str = "zh",
               progress=None, predecoded=None) -> AsrOutcome:
    """L1+L2：解码 → whisper 推理 → 词级时间戳。

    一切异常都收敛成 `AsrOutcome.error`，**绝不向上抛**：对齐是后台任务，
    抛出去只会在控制台留一段堆栈，用户那边表现为「点了没反应」。

    `predecoded=(pcm, sr)` 可跳过解码：`align_track` 要同时算能量包络，解码一次就够。
    """
    if not model_dir or not os.path.isdir(model_dir):
        return AsrOutcome(error="model_missing", detail=str(model_dir))

    # 本地目录加载不需要联网，但 huggingface_hub 仍会读这两个开关；
    # Xet 在镜像站会 401（Phase 0 实测），设上没坏处。
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    if predecoded is not None:
        pcm, _sr = predecoded
    else:
        if progress:
            progress("decode", 0.0)
        try:
            pcm, _sr = decode_for_asr(audio_path)
        except Exception as exc:  # noqa: BLE001
            return AsrOutcome(error="decode_failed",
                              detail=f"{type(exc).__name__}: {exc}")

    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # noqa: BLE001
        return AsrOutcome(error="import_failed", detail=f"{type(exc).__name__}: {exc}")

    if progress:
        progress("load", 0.05)
    try:
        # 必须传**本地目录**：传 "base" 这类名字会联网查版本，离线或代理不通时抛错。
        model = WhisperModel(model_dir, device="cpu", compute_type="int8")
    except Exception as exc:  # noqa: BLE001
        return AsrOutcome(error="import_failed", detail=f"{type(exc).__name__}: {exc}")

    if progress:
        progress("transcribe", 0.2)
    try:
        segments, info = model.transcribe(
            pcm,
            language=(language or None),
            word_timestamps=True,
            vad_filter=False,      # VAD 要 onnxruntime（45MB），我们直接排除掉
            beam_size=5,
        )
        words: list[RecognizedWord] = []
        for seg in segments:        # 生成器：这里才真正开始推理
            for word in (seg.words or ()):
                text = (word.word or "").strip()
                if not text:
                    continue
                words.append(RecognizedWord(
                    round(word.start * 1000),
                    round(word.end * 1000),
                    text,
                    float(getattr(word, "probability", 0.0) or 0.0),
                ))
            if progress:
                progress("transcribe", 0.2 + 0.7 * min(1.0, seg.end / max(info.duration, 1e-6)))
    except Exception as exc:  # noqa: BLE001
        return AsrOutcome(error="import_failed", detail=f"{type(exc).__name__}: {exc}")

    if progress:
        progress("done", 1.0)
    outcome = AsrOutcome(words=words, language=getattr(info, "language", "") or "",
                         duration_ms=int((getattr(info, "duration", 0.0) or 0.0) * 1000))
    if not words:
        outcome.error = "no_speech"
    return outcome


# ---------- L3 序列比对 ----------
#
# 归一化口径：只保留「字母/数字/汉字」，小写化。标点、空格一律丢掉——
# whisper 输出带空格与标点，原文也带，两边统一剥掉才能对得上。


def normalize_lines(lines: list[LyricLine]) -> tuple[str, list[tuple[int, int]]]:
    """把歌词正文拼成一串待匹配字符，并记录每个字回到 `(行下标, 行内下标)`。"""
    chars: list[str] = []
    positions: list[tuple[int, int]] = []
    for li, line in enumerate(lines or []):
        for ci, ch in enumerate(line.text or ""):
            if ch.isalnum():
                chars.append(ch.lower())
                positions.append((li, ci))
    return "".join(chars), positions


def normalize_recognized(words: list[RecognizedWord]) -> tuple[str, list[tuple[int, int]],
                                                                list[float]]:
    """把识别词展开成字符序列，每个字符继承所属词的时间窗与置信度。

    一个中文词往往 2~3 个字，词内均分留到 `_spread` 做——这里先让同词的字共享窗口。
    """
    chars: list[str] = []
    spans: list[tuple[int, int]] = []
    probs: list[float] = []
    for word in words or []:
        kept = [c.lower() for c in (word.text or "") if c.isalnum()]
        for ch in kept:
            chars.append(ch)
            spans.append((word.start_ms, word.end_ms))
            probs.append(word.probability)
    return "".join(chars), spans, probs


def _match_windows(lyric: str, recog: str, spans: list[tuple[int, int]]):
    """difflib 对齐两条字符序列，返回 `(每字时间窗, 命中的识别下标集合)`。

    识别错的字对不上是**正常现象**（唱歌 + 伴奏），`SequenceMatcher` 会把它们当成
    插入/删除跳过，剩下的匹配块照样能给出时间。所以匹配率低于阈值时才需要放弃
    （L5），个别字对不上不用管。
    """
    windows: list[tuple[int, int] | None] = [None] * len(lyric)
    matched: set[int] = set()
    matcher = difflib.SequenceMatcher(None, lyric, recog, autojunk=False)
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            windows[a + k] = spans[b + k]
            matched.add(b + k)
    return windows, matched


def _spread(windows: list[tuple[int, int] | None]) -> list[tuple[int, int] | None]:
    """同一个词里的多个字共享一个时间窗 → 按字数均分，变成各自的窗口。

    不做这一步的话，一句「故事的小黄花」如果被识别成一个词，7 个字会同时亮起来，
    逐字效果直接退化成整行。
    """
    out = list(windows)
    i = 0
    n = len(out)
    while i < n:
        j = i
        while j + 1 < n and out[j + 1] is not None and out[j + 1] == out[i]:
            j += 1
        if out[i] is not None and j > i:
            start, end = out[i]
            count = j - i + 1
            step = (end - start) / count
            for k in range(count):
                out[i + k] = (round(start + step * k),
                              round(start + step * (k + 1)))
        i = j + 1
    return out


def _fill_gaps(windows: list[tuple[int, int] | None]) -> list[tuple[int, int] | None]:
    """把没对上的字（None）用左右邻居插值补上：识别漏字不该在歌词里留个洞。"""
    out = list(windows)
    n = len(out)
    i = 0
    while i < n:
        if out[i] is not None:
            i += 1
            continue
        j = i
        while j < n and out[j] is None:
            j += 1
        prev_end = out[i - 1][1] if i > 0 and out[i - 1] is not None else None
        next_start = out[j][0] if j < n and out[j] is not None else None
        if prev_end is None and next_start is None:
            return out                      # 全都没匹配上，交给 L5 判失败
        if prev_end is None:
            prev_end = next_start
        if next_start is None:
            next_start = prev_end
        count = j - i
        step = (next_start - prev_end) / count
        for k in range(count):
            out[i + k] = (round(prev_end + step * k),
                          round(prev_end + step * (k + 1)))
        i = j
    return out


# ---------- L4 能量谷吸附 ----------


def snap_to_energy(windows: list[tuple[int, int] | None], rms: list[float],
                   hop_ms: int = 10, snap_ms: int = SNAP_MS,
                   min_char_ms: int = MIN_CHAR_MS) -> list[tuple[int, int] | None]:
    """把每个字边界挪到 ±snap_ms 内的能量极小点（换气口 / 辅音起点）。

    whisper 给的是「整词一个窗」，字与字的交界只能靠均分猜；歌声的能量谷通常正好落在
    换气或咬字起音处。实测能把字边界误差从 ±150ms 压到 ±80ms 量级。

    `rms` 为 None/空时原样返回（没有音频也能跑对齐，只是不吸附）。
    """
    if not rms or len(windows) < 2:
        return windows
    out = list(windows)
    last_frame = len(rms) - 1

    def frame_of(ms: int) -> int:
        k = ms // hop_ms
        return min(last_frame, max(0, k))

    for i in range(len(out) - 1):
        left, right = out[i], out[i + 1]
        if left is None or right is None:
            continue
        boundary = left[1]
        lo = max(left[0] + min_char_ms, boundary - snap_ms)
        hi = min(right[1] - min_char_ms, boundary + snap_ms)
        if hi <= lo:
            continue
        best_ms, best_val = boundary, None
        for ms in range(lo, hi + 1, hop_ms):
            val = rms[frame_of(ms)]
            if best_val is None or val < best_val:
                best_val, best_ms = val, ms
        out[i] = (left[0], best_ms)
        out[i + 1] = (best_ms, right[1])
    return out


# ---------- 逐行装配 ----------


def build_line_words(lines: list[LyricLine], positions: list[tuple[int, int]],
                     windows: list[tuple[int, int] | None]) -> list[tuple[WordSpan, ...]]:
    """把「字级时间窗」装回每一行，产出 `LyricLine.words`。

    硬约束：**每个字元的文本拼起来必须等于整行原文**。所以标点、空格这些没有时间的
    字符不能丢——它们并进相邻字元的文本里（能对上时间的那一侧）。
    这条约束是渲染层「按字切分」的前提，破了就会整体错位。
    """
    per_line: dict[int, list[tuple[int, int, int]]] = {}
    for index, (li, ci) in enumerate(positions):
        window = windows[index] if index < len(windows) else None
        if window is None:
            continue
        per_line.setdefault(li, []).append((ci, int(window[0]), int(window[1])))

    out: list[tuple[WordSpan, ...]] = [() for _ in lines]
    for li, timed in per_line.items():
        if not 0 <= li < len(lines):
            continue
        text = lines[li].text or ""
        timed.sort()
        spans: list[WordSpan] = []
        prev_ci = -1
        prev_start = -1
        for ci, start, end in timed:
            if ci < prev_ci:                        # 理论上不会发生，防御一下
                continue
            start = max(start, prev_start)          # 边界不许倒退（L4 之后可能压出负宽）
            prev_start = start
            if end <= start:
                end = start + 1
            spans.append(WordSpan(start, end, text[prev_ci + 1:ci + 1]))
            prev_ci = ci
            prev_start = start
        if not spans:
            continue
        if prev_ci + 1 < len(text):
            last = spans[-1]
            spans[-1] = WordSpan(last.start_ms, last.end_ms, last.text + text[prev_ci + 1:])
        # 末字的 end 交给渲染层按行尾兜底：这里给 0 表示「终点未知」，
        # 与增强 LRC 的约定保持一致。
        out[li] = tuple(spans)
    return out


# ---------- L5 置信度自检 + 总装 ----------


def align_lyrics(lines: list[LyricLine], recognized: list[RecognizedWord],
                 rms: list[float] | None = None, hop_ms: int = 10,
                 min_match_ratio: float = MIN_MATCH_RATIO,
                 min_mean_prob: float = MIN_MEAN_PROB) -> AlignOutcome:
    """L3~L5 总装：词级时间戳 + 原歌词 → 逐字时间轴。

    `rms` 传能量包络时启用 L4 吸附；不传就只做均分（纯逻辑可单测）。
    失败一律返回 `error` 且 **`lines` 原样返回**——调用方据此决定要不要落盘。
    """
    lines = list(lines or [])
    lyric, positions = normalize_lines(lines)
    if not lyric:
        return AlignOutcome(lines, error="no_lyrics", detail=describe_error("no_lyrics"))

    recog, spans, probs = normalize_recognized(recognized)
    if not recog:
        return AlignOutcome(lines, error="no_speech", detail=describe_error("no_speech"))

    windows, matched = _match_windows(lyric, recog, spans)
    ratio = len(matched) / len(lyric)
    mean_prob = (sum(probs[i] for i in matched) / len(matched)) if matched else 0.0

    if ratio < min_match_ratio or mean_prob < min_mean_prob:
        # 低置信度：**不写入**。写一份错的逐字时间轴比没有更糟——用户会以为是播放器卡。
        return AlignOutcome(lines, matched_ratio=ratio, mean_probability=mean_prob,
                            error="low_confidence",
                            detail=f"匹配率 {ratio:.0%}、置信度 {mean_prob:.2f}")

    windows = _spread(windows)
    windows = _fill_gaps(windows)
    windows = snap_to_energy(windows, rms or [], hop_ms)
    blocks = build_line_words(lines, positions, windows)
    out = [LyricLine(line.time_ms, line.text, line.translation, block)
           for line, block in zip(lines, blocks, strict=True)]
    max_shift = 0
    for line, block in zip(lines, blocks, strict=True):
        if block:
            max_shift = max(max_shift, abs(block[0].start_ms - line.time_ms))
    return AlignOutcome(out, matched_ratio=ratio, mean_probability=mean_prob,
                        max_shift_ms=max_shift)


def retime_lines(lines: list[LyricLine], min_gap_ms: int = 120) -> list[LyricLine]:
    """用对齐出的首字时间重打**行**时间轴，返回新列表。

    这是「行级误差 6.04s → <0.5s」的落点：本地近似对齐只能按有声段和字数估，前奏一长
    整条时间轴就整体偏早；whisper 给出的首字时刻是实测值，直接拿来当行起点。

    三条约束：
    1. 只有拿到逐字数据的行才重打，其余行保持原时间（宁可不改）；
    2. 时间必须严格递增（间隔至少 `min_gap_ms`），否则高亮会跳来跳去；
    3. 不写回任何文件——调用方决定这棵新时间轴要不要落成 .lrc。
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


def align_track(audio_path: str, lines: list[LyricLine], model_dir: str,
                language: str = "zh", progress=None) -> AlignOutcome:
    """端到端：解码 → 识别 → 对齐。给 UI 用的单入口。

    解码只做一次：pcm 既喂 whisper，也算 L4 的能量包络。
    """
    if progress:
        progress("decode", 0.0)
    try:
        pcm, sr = decode_for_asr(audio_path)
    except Exception as exc:  # noqa: BLE001
        return AlignOutcome(list(lines or []), error="decode_failed",
                            detail=f"{type(exc).__name__}: {exc}")
    asr = transcribe(audio_path, model_dir, language, progress, predecoded=(pcm, sr))
    if not asr.ok:
        return AlignOutcome(list(lines or []), error=asr.error,
                            detail=asr.detail or describe_error(asr.error))
    if progress:
        progress("align", 0.9)
    outcome = align_lyrics(lines, asr.words, rms_fast(pcm, sr))
    if progress:
        progress("done", 1.0)
    return outcome


def rms_fast(samples, sample_rate: int, frame_ms: int = 20,
             hop_ms: int = 10) -> list[float]:
    """向量化 RMS 包络（与 `rms_envelope` 同口径，但快两个数量级）。

    为什么不用现成的 `rms_envelope`：它是纯 Python 双重循环，4 分钟歌要过 960 万个
    采样点，实测十几秒——为了省几秒编码时间把对齐拖慢一倍不值得。
    这里用平方的累积和做滑窗，一次算完，没有大块中间数组。
    """
    try:
        import numpy as np
    except Exception:  # noqa: BLE001
        return rms_envelope(samples, sample_rate, frame_ms, hop_ms)
    x = np.asarray(samples, dtype=np.float32)
    frame = sample_rate * frame_ms // 1000
    hop = sample_rate * hop_ms // 1000
    if frame <= 0 or hop <= 0 or x.size < frame:
        return []
    count = 1 + (x.size - frame) // hop
    csum = np.concatenate((np.zeros(1, dtype=np.float64),
                           np.cumsum(x.astype(np.float64) ** 2)))
    starts = np.arange(count, dtype=np.int64) * hop
    sums = csum[starts + frame] - csum[starts]
    return np.sqrt(sums / frame).tolist()


# ---------- 后台线程 ----------
#
# 单曲对齐要跑几十秒（解码 + 推理），必须离开 UI 线程。批量对齐由对话框串行复用
# 这个 worker，不另写一套 —— 两条路走同一份代码，行为不会分叉。

_STAGE_TEXT = {
    "download": "下载 AI 模型",
    "decode": "解码音频",
    "load": "加载 AI 模型",
    "transcribe": "识别演唱",
    "align": "对齐逐字",
    "done": "完成",
}


class LyricsAsrWorker(QThread):
    """单曲 AI 对齐：确保模型 → 解码 → 识别 → 对齐 → **落盘** → 通知界面。

    为什么落盘放在线程里：sidecar 不大（一首几十 KB），但数据目录可能在慢盘/网络盘上，
    在主线程里写会在切歌瞬间卡一下；而且写失败也不该让 UI 崩。
    """

    done = Signal(str, object)      # track_id, AlignOutcome（已落盘）
    failed = Signal(str, str)       # track_id, 中文提示
    progress = Signal(int, str)     # 0~100, 阶段名

    def __init__(self, track_id: str, audio_path: str, lines: list[LyricLine],
                 model_name: str = DEFAULT_AI_MODEL, language: str = "zh",
                 parent=None) -> None:
        super().__init__(parent)
        self._track_id = track_id
        self._audio_path = audio_path
        self._lines = list(lines or [])
        self._model_name = model_name
        self._language = language

    def run(self) -> None:
        def _report(stage: str, fraction: float) -> None:
            percent = int(max(0.0, min(1.0, fraction)) * 100)
            self.progress.emit(percent, _STAGE_TEXT.get(stage, stage))

        try:
            model_dir, err, detail = ensure_model(self._model_name, _report)
            if err:
                # 详情一定要带出去：v3.0.0 只显示「检查网络」，用户在真实环境里
                # 反复失败也说不清是什么，开发侧同样无从下手（v3.0.1）。
                message = describe_error(err)
                if detail:
                    message = f"{message}（{detail}）"
                self.failed.emit(self._track_id, message)
                return
            if self.isInterruptionRequested():
                self.failed.emit(self._track_id, describe_error("cancelled"))
                return
            outcome = align_track(self._audio_path, self._lines, model_dir,
                                  self._language, _report)
        except Exception as exc:  # noqa: BLE001 - 线程里抛异常等于静默失败
            self.failed.emit(self._track_id, f"对齐出错：{type(exc).__name__}: {exc}")
            return
        # v2.7.5 的老坑：窗口关了还 emit 就是往正在析构的对象投信号
        if self.isInterruptionRequested():
            self.failed.emit(self._track_id, describe_error("cancelled"))
            return
        if not outcome.ok:
            message = describe_error(outcome.error)
            if outcome.detail:
                message = f"{message}（{outcome.detail}）"
            self.failed.emit(self._track_id, message)
            return
        save_from_lines(self._track_id, outcome.lines)
        self.done.emit(self._track_id, outcome)
