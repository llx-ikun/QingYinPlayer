# -*- coding: utf-8 -*-
"""探针：量「长前奏」场景下本地对齐的实际行为。

用真实音频（APPDATA 曲库）解码 → 能量包络 → `detect_speech` 段结构 → 首句落点，
并与「同名 .lrc / 联网歌词」的第一句时间对比，量化「前奏判定」误差。

跑法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_align_intro.py
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_align_intro.py --file "xxx.flac"
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lyrics_local_align import (  # noqa: E402
    HOP_MS,
    assign_timestamps,
    decode_mono,
    detect_speech,
    rms_envelope,
)


def library_dir() -> str:
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, "轻音播放器", "library")


def audio_files(folder: str) -> list[str]:
    if not os.path.isdir(folder):
        return []
    exts = (".flac", ".mp3", ".wav", ".ogg", ".m4a")
    return [os.path.join(folder, f) for f in sorted(os.listdir(folder))
            if f.lower().endswith(exts)]


def fmt(ms: int) -> str:
    return f"{ms // 60000:02d}:{(ms // 1000) % 60:02d}.{(ms % 1000) // 10:02d}"


def envelope_report(rms: list[float], total_ms: int) -> None:
    """把包络按秒聚合成「每秒平均 RMS」，用条形图看出前奏在哪。"""
    per_sec = max(1, 1000 // HOP_MS)
    nonzero = [x for x in rms if x > 1e-6]
    med = statistics.median(nonzero) if nonzero else 0.0
    print(f"  RMS 中位数 {med:.4f}｜现有阈值（中位数×0.15）= {med * 0.15:.4f}")
    print("  每秒平均 RMS（█ 高度≈响度，竖线=现有阈值）：")
    peak = max(rms) if rms else 1.0
    for sec in range((total_ms // 1000) + 1):
        chunk = rms[sec * per_sec:(sec + 1) * per_sec]
        if not chunk:
            break
        avg = sum(chunk) / len(chunk)
        bars = round(avg / peak * 40)
        mark = "|" if avg > med * 0.15 else " "
        print(f"   {sec:>3}s {fmt(sec * 1000)[-6:]} {avg:6.3f} {mark}{'█' * bars}")


def analyze(path: str, line_count: int = 20) -> None:
    name = os.path.basename(path)
    print(f"\n{'=' * 78}\n{name}\n{'=' * 78}")
    samples, sr = decode_mono(path)
    total_ms = len(samples) * 1000 // sr
    rms = rms_envelope(samples, sr)
    segments = detect_speech(rms)
    print(f"时长 {fmt(total_ms)}｜帧数 {len(rms)}｜有声段 {len(segments)} 段")
    for i, (s, e) in enumerate(segments[:8]):
        print(f"   段{i + 1}: {fmt(s)} → {fmt(e)}  长 {(e - s) / 1000:.1f}s")
    if len(segments) > 8:
        print(f"   … 共 {len(segments)} 段")

    speech_total = sum(e - s for s, e in segments)
    print(f"  「有声」总时长 {speech_total / 1000:.1f}s / 全曲 {total_ms / 1000:.1f}s"
          f"（占比 {speech_total / max(total_ms, 1) * 100:.0f}%）")

    # 假设 20 句歌词，看首句落在哪
    stamped = assign_timestamps([f"L{i}" for i in range(line_count)], segments, total_ms)
    print(f"  若 {line_count} 句：首句 {fmt(stamped[0][1])}｜"
          f"次句 {fmt(stamped[1][1])}｜句间隔 {(stamped[1][1] - stamped[0][1]) / 1000:.2f}s")
    return total_ms, rms, segments


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="")
    ap.add_argument("--bars", action="store_true", help="打印每秒能量条形图（只对单首）")
    args = ap.parse_args()

    paths = [args.file] if args.file else audio_files(library_dir())
    if not paths:
        print("没找到音频文件")
        return 1
    for p in paths[:4]:
        total_ms, rms, _seg = analyze(p)
        if args.bars:
            envelope_report(rms, total_ms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
