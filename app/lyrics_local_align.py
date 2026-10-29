# -*- coding: utf-8 -*-
"""本地歌词对齐：把纯文本歌词配到音频时间轴，产出 LRC（无需联网、无需 Key）。

与 `app/lyrics_align.py`（联网 LyricTimestamps）的区别：这里**完全本地**完成，
不依赖外部服务、不上传音频、零额度限制。代价是精度是「近似对齐」而非「逐字
卡点」——适合「让歌词大致跟着唱、别一整坨不动」的场景；想要精准卡点仍可走联网。

算法（纯信号处理，无 AI 模型）：
1. 解码音频到 mono 16kHz 的 float32 采样（miniaudio，纯 C，无 numpy）；
2. 分帧算 RMS 能量包络；
3. 动态阈值检测「有声段 / 静音段」——前奏/间奏/尾奏的静音会被识别出来；
4. 把歌词行**均匀铺在「有声段」上**（跳过前奏/间奏/尾奏），生成 LRC。

关键坑（实测）：
- `miniaudio.decode_file(path)` 对**中文路径**解码失败（C 层用 ANSI 打开文件名），
  必须自己 `open(path,'rb').read()` 后走 `miniaudio.decode(bytes)` 绕开。
- `miniaudio.decode` 返回的 `samples` 是 `array.array('f')`，纯 Python 分帧算 RMS
  对一首 3 分钟歌只要 ~0.2s，不必引入 numpy。
- LRC 时间戳用 `[mm:ss.xx]`（百分秒），与 `app/lyrics.parse_lrc` 兼容。
"""
from __future__ import annotations

import os
import statistics
from array import array
from dataclasses import dataclass

import miniaudio
from PySide6.QtCore import QThread, Signal

from app.lyrics import lyrics_from_text

TARGET_SR = 16000
FRAME_MS = 20
HOP_MS = 10
# 相邻有声段间隔小于这个值就合并成一段（避免把一句里的换气当成间奏）。
MIN_SILENCE_MS = 350
# 一段有声至少要持续这么久才算「真的在唱」，否则当噪声忽略。
MIN_SPEECH_MS = 200


@dataclass
class LocalAlignOutcome:
    """一次本地对齐的结果：成功 `lrc` 有值；失败 `error_code` 非空。"""

    lrc: str | None = None
    error_code: str = ""
    error_message: str = ""


_ERROR_MESSAGES = {
    "no_audio": "音频文件不存在或不可读",
    "decode_failed": "无法解码该音频（本地对齐支持 mp3/flac/wav/ogg，其余格式请用联网对齐）",
    "no_lyrics": "没有可对齐的歌词文本",
    "already_synced": "这首已是带时间轴的歌词，无需对齐",
    "read_failed": "读取音频文件失败",
}


def describe_error(code: str) -> str:
    return _ERROR_MESSAGES.get(code, "本地对齐失败，请重试")


# ---------- 解码 ----------


def decode_mono(audio_path: str, target_sr: int = TARGET_SR) -> tuple[array, int]:
    """解码音频为 mono float32 采样，返回 `(samples, sample_rate)`。

    `samples` 是 `array.array('f')`。用 `open().read()` + `decode(bytes)` 而非
    `decode_file(path)`，绕开 miniaudio 对中文路径的 ANSI 解码失败。
    """
    with open(audio_path, "rb") as f:
        data = f.read()
    decoded = miniaudio.decode(
        data,
        output_format=miniaudio.SampleFormat.FLOAT32,
        nchannels=1,
        sample_rate=target_sr,
    )
    return decoded.samples, decoded.sample_rate


# ---------- 能量与静音检测 ----------


def rms_envelope(samples: array, sample_rate: int, frame_ms: int = FRAME_MS,
                 hop_ms: int = HOP_MS) -> list[float]:
    """分帧算 RMS，返回每帧的均方根（帧长 frame_ms、步进 hop_ms）。"""
    frame = sample_rate * frame_ms // 1000
    hop = sample_rate * hop_ms // 1000
    if frame <= 0 or hop <= 0:
        return []
    out: list[float] = []
    n = len(samples)
    for i in range(0, n - frame + 1, hop):
        chunk = samples[i:i + frame]
        total = 0.0
        for x in chunk:
            total += x * x
        out.append((total / frame) ** 0.5)
    return out


def detect_speech(rms: list[float], hop_ms: int = HOP_MS,
                  min_silence_ms: int = MIN_SILENCE_MS,
                  min_speech_ms: int = MIN_SPEECH_MS) -> list[tuple[int, int]]:
    """返回有声段 `[(start_ms, end_ms)]`。

    阈值用「非零 RMS 的中位数 × 0.15」动态定——不同响度的歌都能用，不写死绝对值。
    短于 `min_speech_ms` 的「有声」当噪声忽略；相邻段间隔小于 `min_silence_ms` 合并。
    """
    if not rms:
        return []
    nonzero = [x for x in rms if x > 1e-6]
    if not nonzero:
        return []
    threshold = max(statistics.median(nonzero) * 0.15, 1e-4)

    min_speech_frames = max(1, min_speech_ms // hop_ms)
    segments: list[tuple[int, int]] = []
    in_speech = False
    start = 0
    n = len(rms)
    for i, value in enumerate(rms):
        if value > threshold and not in_speech:
            in_speech = True
            start = i
        elif value <= threshold and in_speech:
            if i - start >= min_speech_frames:
                segments.append((start * hop_ms, i * hop_ms))
            in_speech = False
    if in_speech and n - start >= min_speech_frames:
        segments.append((start * hop_ms, n * hop_ms))

    merged: list[tuple[int, int]] = []
    for s, e in segments:
        if merged and s - merged[-1][1] < min_silence_ms:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged


# ---------- 时间戳分配 ----------


def assign_timestamps(lines: list[str], segments: list[tuple[int, int]],
                      total_ms: int) -> list[tuple[str, int]]:
    """把歌词行均匀铺在「有声段」上，返回 `[(行文本, 时间ms)]`。

    无有声段（纯音乐/整首都有声没测出静音）时退化为「全时长均分」。
    每行取「它在有声时间轴上的中点」映射回实际时间——歌词不会铺在前奏/间奏/尾奏上。
    """
    n = len(lines)
    if n == 0:
        return []
    if not segments:
        return [(text, int(i * total_ms / n)) for i, text in enumerate(lines)]
    speech_total = sum(e - s for s, e in segments)
    if speech_total <= 0:
        return [(text, int(i * total_ms / n)) for i, text in enumerate(lines)]

    result: list[tuple[str, int]] = []
    seg_idx = 0
    accum_before = 0.0
    for i, text in enumerate(lines):
        pos = (i + 0.5) * speech_total / n
        while seg_idx < len(segments) - 1:
            s, e = segments[seg_idx]
            if pos <= accum_before + (e - s):
                break
            accum_before += e - s
            seg_idx += 1
        s, e = segments[seg_idx]
        offset = max(0.0, pos - accum_before)
        actual_ms = s + min(offset, float(e - s))
        result.append((text, int(actual_ms)))
    return result


def _format_lrc_time(ms: int) -> str:
    total_s = ms // 1000
    m = total_s // 60
    s = total_s % 60
    cs = (ms % 1000) // 10
    return f"[{m:02d}:{s:02d}.{cs:02d}]"


# ---------- 对齐入口 ----------


def align_local(audio_path: str, lyrics_text: str, progress=None) -> LocalAlignOutcome:
    """把纯文本歌词本地对齐到音频，返回 LRC。

    `progress(percent, stage)` 可选回调，供 UI 显示进度。全程离线、无网络。
    """
    lyrics_text = (lyrics_text or "").strip()
    if not lyrics_text:
        return LocalAlignOutcome(error_code="no_lyrics")
    if not os.path.isfile(audio_path):
        return LocalAlignOutcome(error_code="no_audio")

    synced, plain = lyrics_from_text(lyrics_text)
    if synced:
        return LocalAlignOutcome(error_code="already_synced")
    lines = [ln.strip() for ln in plain if ln.strip()]
    if not lines:
        return LocalAlignOutcome(error_code="no_lyrics")

    if progress is not None:
        progress(10, "解码音频…")
    try:
        samples, sample_rate = decode_mono(audio_path)
    except FileNotFoundError:
        return LocalAlignOutcome(error_code="no_audio")
    except miniaudio.DecodeError:
        return LocalAlignOutcome(error_code="decode_failed")
    except OSError:
        return LocalAlignOutcome(error_code="read_failed")
    total_ms = len(samples) * 1000 // sample_rate

    if progress is not None:
        progress(40, "分析节奏…")
    rms = rms_envelope(samples, sample_rate)
    segments = detect_speech(rms)

    if progress is not None:
        progress(70, "分配时间轴…")
    pairs = assign_timestamps(lines, segments, total_ms)
    lrc = "\n".join(f"{_format_lrc_time(ms)}{text}" for text, ms in pairs) + "\n"
    if progress is not None:
        progress(100, "完成")
    return LocalAlignOutcome(lrc=lrc)


# ---------- 后台线程 ----------


class LyricsLocalAlignWorker(QThread):
    """后台跑本地对齐：成功发 `done(track_id, lrc)`，失败发 `failed(track_id, 中文提示)`，
    `progress(percent, stage)` 逐步上报。"""

    done = Signal(str, str)
    failed = Signal(str, str)
    progress = Signal(int, str)

    def __init__(self, track_id: str, audio_path: str, lyrics_text: str,
                 parent=None) -> None:
        super().__init__(parent)
        self._track_id = track_id
        self._audio_path = audio_path
        self._lyrics_text = lyrics_text

    def run(self) -> None:
        def _report(percent: int, stage: str) -> None:
            self.progress.emit(percent, stage)

        outcome = align_local(self._audio_path, self._lyrics_text, progress=_report)
        if outcome.lrc:
            self.done.emit(self._track_id, outcome.lrc)
        else:
            message = describe_error(outcome.error_code) or outcome.error_message or "本地对齐失败"
            self.failed.emit(self._track_id, message)
