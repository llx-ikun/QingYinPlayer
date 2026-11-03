# -*- coding: utf-8 -*-
"""音频能量包络（v3.3.0）：把一首歌压成每秒 20 个 0~1 的响度值，供动态背景跟随。

**为什么不在播放时实时取音量**：Qt 6 不给 PCM / 频谱回调（QAudioProbe 已废弃），
想拿实时音量只能自己抓音频流，跨平台且极易崩。而背景动画要的粒度本来就很粗
（50ms 一个数就够），所以「离线解码成包络 + 播放时按位置查表」在观感上完全等价，
代价却从「每帧取频谱」降到「一次数组下标 + 一次线性插值」。

**为什么不做成纯时间驱动的呼吸**：那样换一首歌背景一模一样，本质是屏保。
有包络才真的跟着鼓点起伏 —— 这是这个功能唯一的「值」。

**解码成本实测**（8kHz mono）：mp3 约 1.2ms / 秒音频 → 4 分钟的歌约 0.3 秒。
所以放在后台线程算 + 落盘缓存（`energy/<track_id>.json`），同一首歌第二次播放
直接命中缓存。缓存带 `src` 指纹（size + mtime），源文件被替换后自动失效。

这个模块刻意**不导入 Qt**：包络是一条纯数学流水线，能不碰 Qt 就别碰（可单测、
可在 tools/ 脚本里直接跑，也不会在无 QApplication 的进程里把解释器带崩）。
"""
from __future__ import annotations

import contextlib
import json
import math
import os

# 每秒采样数。50ms 一档：比人眼能分辨的背景起伏细，又比逐帧计算便宜两个数量级
ENERGY_HZ = 20

# 解码采样率。能量是低频信息，8kHz 足够（还顺带省掉 90% 的解码时间）
DECODE_SR = 8000

ENVELOPE_VERSION = 1

# 归一化参考取 95 分位而不是最大值：一首歌里往往有一两个特别响的爆点，
# 用最大值当分母会把其余部分全压成一条平线（背景看起来「不动」）
_REF_PERCENTILE = 0.95

# 感知补偿指数：RMS 是线性量，直接画出来「响的地方很亮、轻的地方几乎没变化」，
# 取 0.65 次幂把动态范围拉回来一点（低于 1 会抬高小值）
_SHAPE_EXP = 0.65


def build_envelope(samples, sample_rate: int, hz: int = ENERGY_HZ) -> list[float]:
    """把 mono 采样压成 0~1 的 RMS 包络。

    `samples` 支持 `array('f')` / list（只用到 `len()` 和下标）。
    静音 / 全零返回全 0 的等长列表（不是空列表）—— 长度信息本身有用（时长）。
    """
    if sample_rate <= 0 or hz <= 0:
        return []
    hop = max(1, int(sample_rate / hz))
    total = len(samples)
    if total <= 0:
        return []

    frames: list[float] = []
    for start in range(0, total, hop):
        end = min(total, start + hop)
        acc = 0.0
        for i in range(start, end):
            v = float(samples[i])
            acc += v * v
        frames.append(math.sqrt(acc / max(1, end - start)))

    reference = _percentile(frames, _REF_PERCENTILE)
    if reference <= 1e-6:
        return [0.0] * len(frames)

    shaped = [min(1.0, (v / reference) ** _SHAPE_EXP) for v in frames]
    return _smooth3(shaped)


def _percentile(values: list[float], q: float) -> float:
    """线性插值分位数（不引 numpy：这里只要一个数）。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = min(1.0, max(0.0, q)) * (len(ordered) - 1)
    lo = int(pos)
    hi = min(len(ordered) - 1, lo + 1)
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _smooth3(values: list[float]) -> list[float]:
    """三点平滑 [0.25, 0.5, 0.25]：去掉单帧毛刺。

    不做平滑的话，压缩音频的块边界会让背景每 26ms 抖一下，看起来像接触不良。
    首尾各自退化（不出界、不补零 —— 补零会让开头尾各有一档掉光）。
    """
    n = len(values)
    if n < 3:
        return list(values)
    out = [values[0]]
    for i in range(1, n - 1):
        out.append(values[i - 1] * 0.25 + values[i] * 0.5 + values[i + 1] * 0.25)
    out.append(values[-1])
    return out


def energy_at(envelope: list[float] | None, position_ms: int, hz: int = ENERGY_HZ) -> float:
    """按播放位置查能量（线性插值，夹在 0~1）。

    越界返回 0：歌播完之后背景应当安静下来，而不是停在最后一个高点上。
    """
    if not envelope or hz <= 0 or position_ms <= 0:
        return 0.0
    pos = position_ms / 1000.0 * hz
    index = int(pos)
    if index >= len(envelope):
        return 0.0
    nxt = min(len(envelope) - 1, index + 1)
    frac = pos - index
    value = envelope[index] * (1.0 - frac) + envelope[nxt] * frac
    return min(1.0, max(0.0, value))


# ---------------- 磁盘缓存 ----------------


def source_key(path: str) -> str:
    """源文件指纹。取不到（文件没了）返回空串，调用方据此放弃缓存。"""
    try:
        st = os.stat(path)
    except OSError:
        return ""
    return f"{st.st_size}:{int(st.st_mtime)}"


def envelope_path(cache_dir: str, track_id: str) -> str:
    """缓存文件路径：`<cache_dir>/<track_id>.json`。track_id 已是路径哈希，直接当文件名。"""
    safe = "".join(ch for ch in track_id if ch.isalnum() or ch in "-_") or "track"
    return os.path.join(cache_dir, f"{safe}.json")


def save_envelope(path: str, envelope: list[float], duration_ms: int,
                  src: str, hz: int = ENERGY_HZ) -> bool:
    """写缓存。失败返回 False 不抛（缓存写不进去不该影响播放）。"""
    if not envelope or not src:
        return False
    payload = {
        "v": ENVELOPE_VERSION,
        "hz": hz,
        "ms": int(max(0, duration_ms)),
        "src": src,
        "data": [round(v, 4) for v in envelope],
    }
    tmp = path + ".part"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
        os.replace(tmp, path)       # 原子落盘：写一半崩掉不会留下半个 JSON
        return True
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        return False


def load_envelope(path: str, src: str, hz: int = ENERGY_HZ) -> list[float] | None:
    """读缓存。版本/采样率/源指纹任一不符、或数据不合法，一律返回 None。

    逐项校验而不是 try 包住全部：坏缓存只应让这一首歌退回「无能量」，
    不该连带把调用方（播放流程）打断。
    """
    if not src or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("v") != ENVELOPE_VERSION or payload.get("hz") != hz:
        return None
    if payload.get("src") != src:
        return None
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None
    out: list[float] = []
    for value in data:
        if not isinstance(value, (int, float)):
            return None
        number = float(value)
        if number != number:            # nan
            return None
        out.append(min(1.0, max(0.0, number)))
    return out
