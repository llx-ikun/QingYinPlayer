# -*- coding: utf-8 -*-
"""探针：用「联网歌词的真实时间戳」当基准，量化本地对齐的误差。

为什么这么评估：本地对齐是纯信号处理启发式，精度无法靠肉眼看出来。联网多源歌词
（LRCLIB / 网易云 / QQ）给的是人工/官方同步稿，可以当**真值**——把它的纯文本行
喂给本地对齐，再逐句比较时间差，就能得到客观误差（首句误差 = 前奏判定准不准）。

跑法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/eval_align.py
    env -u PYTHONPATH .venv/Scripts/python.exe tools/eval_align.py --only 何者
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.lyrics import lyrics_from_text  # noqa: E402
from app.lyrics_local_align import align_local  # noqa: E402
from app.lyrics_multi import fetch_outcome_multi  # noqa: E402


def data_json_path() -> str:
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, "轻音播放器", "data.json")


def load_tracks() -> list[dict]:
    p = data_json_path()
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        raw = json.load(f)
    tracks = raw.get("tracks") or {}
    items = list(tracks.values()) if isinstance(tracks, dict) else tracks
    out = []
    for t in items:
        if not t.get("title") or not t.get("path"):
            continue
        if not os.path.isfile(t["path"]):
            continue
        out.append(t)
    return out


def safe_name(text: str) -> str:
    bad = '<>:"/\\|?*'
    return "".join("_" if ch in bad else ch for ch in text)[:80]


def fmt(ms: int) -> str:
    return f"{ms // 60000}:{(ms // 1000) % 60:02d}.{(ms % 1000) // 10:02d}"


def evaluate(track: dict) -> dict | None:
    title = track.get("title", "")
    artist = track.get("artist", "")
    dur = int(track.get("duration_ms") or 0)
    path = track.get("path", "")
    print(f"\n{'=' * 78}\n{title} — {artist}  ({fmt(dur)}, {os.path.basename(path)})\n{'=' * 78}")

    cache_dir = os.path.join(ROOT, "shots", "eval_cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, safe_name(title) + ".lrc")
    source = "缓存"
    if os.path.isfile(cache):
        with open(cache, encoding="utf-8") as f:
            text = f.read()
        aborted = False
    else:
        text, source, aborted = fetch_outcome_multi(title, artist, dur)
        if text:
            with open(cache, "w", encoding="utf-8") as f:
                f.write(text)
    if not text:
        print(f"  ⚠️ 没拿到联网歌词（source={source!r} aborted={aborted}），跳过")
        return None
    truth_synced, _plain = lyrics_from_text(text)
    if not truth_synced:
        print(f"  ⚠️ 联网歌词没有时间轴（来源 {source}），不能当真值")
        return None
    truth = [(ln.text, ln.time_ms) for ln in truth_synced]
    print(f"  真值来源：{source}｜{len(truth)} 句｜首句 {fmt(truth[0][1])}｜末句 {fmt(truth[-1][1])}")

    lyr_text = "\n".join(t for t, _ in truth)
    outcome = align_local(path, lyr_text)
    if not outcome.lrc:
        print(f"  ⚠️ 本地对齐失败：{outcome.error_code}")
        return None
    mine_synced, _ = lyrics_from_text(outcome.lrc)
    mine = [(ln.text, ln.time_ms) for ln in mine_synced]
    print(f"  本地对齐：{len(mine)} 句｜首句 {fmt(mine[0][1])}｜末句 {fmt(mine[-1][1])}")

    if len(mine) != len(truth):
        print(f"  ⚠️ 句数不一致（{len(mine)} vs {len(truth)}），只比前 {min(len(mine), len(truth))} 句")
    n = min(len(mine), len(truth))
    diffs = [(mine[i][1] - truth[i][1]) / 1000.0 for i in range(n)]
    absd = [abs(d) for d in diffs]
    intro_err = diffs[0]
    print(f"  首句误差 {intro_err:+.2f}s（负=歌词偏早，正=偏晚）")
    print(f"  逐句误差：平均 {statistics.mean(diffs):+.2f}s｜"
          f"绝对误差中位 {statistics.median(absd):.2f}s｜最大 {max(absd):.2f}s")
    late = sum(1 for d in diffs if d > 1.0)
    early = sum(1 for d in diffs if d < -1.0)
    print(f"  偏差分布：偏晚 >1s 有 {late} 句｜偏早 >1s 有 {early} 句｜"
          f"±1s 内 {n - late - early}/{n} 句")
    print("  前 8 句对照（真值 → 本地｜误差）：")
    for i in range(min(8, n)):
        print(f"    {i + 1:>2}. {fmt(truth[i][1])} → {fmt(mine[i][1])}  {diffs[i]:+6.2f}s"
              f"  {truth[i][0][:16]}")
    return {"title": title, "n": n, "intro_err": intro_err,
            "mean": statistics.mean(diffs), "median_abs": statistics.median(absd),
            "max": max(absd)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只评估标题包含该串的曲目")
    args = ap.parse_args()
    tracks = load_tracks()
    if args.only:
        tracks = [t for t in tracks if args.only in t.get("title", "")]
    if not tracks:
        print("没有可评估的曲目")
        return 1
    rows = []
    for t in tracks[:5]:
        try:
            r = evaluate(t)
        except Exception as exc:  # 探针不该因单首失败中断
            print(f"  ⚠️ 异常：{type(exc).__name__}: {exc}")
            r = None
        if r:
            rows.append(r)
    if rows:
        print(f"\n{'=' * 78}\n汇总\n{'=' * 78}")
        print(f"{'曲目':<28}{'句数':>4}{'首句误差':>10}{'平均':>9}{'中位绝对':>9}{'最大':>8}")
        for r in rows:
            print(f"{r['title'][:26]:<28}{r['n']:>4}{r['intro_err']:>+10.2f}"
                  f"{r['mean']:>+9.2f}{r['median_abs']:>9.2f}{r['max']:>8.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
