# -*- coding: utf-8 -*-
"""歌词匹配评测（v3.0.5）：用构造式黄金集量化 precision / recall / 误配率。

为什么用「构造式」而不是真实曲库：
- 匹配逻辑 `pick_best` 是纯函数（query + 候选 → 选第几条或拒绝），用「query +
  候选列表 + 期望」的黄金集就能**离线、可复现**地量化；
- 真实曲库要「人工逐首标正确歌词」，成本高、不可复现，且同一首歌不同平台结果
  今天对明天错。真实样本作为后续增量补充，不挡日常回归。

指标口径（precision 优先，对齐 v3.0.4 决策「宁可配不到也不配错」）：
- precision = 配上的里正确的比例（越接近 1 越不会配错词）
- recall    = 该配的都配上了的比例（覆盖率）
- 误配率    = 配错的比例（最该盯，配错比没配更糟）

**这套题有一个已知偏差**：很多用例的时长与本地完全一致，于是「时长差 ≤2s」
一条就把结果兜住了，标题/艺人写得再烂也能过。v3.0.5 因此专门加了一批
「时长漂移 8~20s + 无专辑可依」的硬题（用例名带「硬题·」前缀），
它们才是真正考标题/艺人信号的题。

跑法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/eval_match.py
    env -u PYTHONPATH .venv/Scripts/python.exe tools/eval_match.py --detail
    env -u PYTHONPATH .venv/Scripts/python.exe tools/eval_match.py --cases <path>
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.lyrics_online import LyricHit, pick_best_detail  # noqa: E402

DEFAULT_CASES = os.path.join(ROOT, "tests", "lyrics_eval_cases.json")

_SYNC = "[00:00.00] 占位同步歌词 SYNC"
_PLAIN = "占位纯文本歌词 PLAIN"


def _to_hits(candidates: list[dict]) -> list[LyricHit]:
    return [
        LyricHit(
            track_name=str(c.get("track") or ""),
            artist_name=str(c.get("artist") or ""),
            album_name=str(c.get("album") or ""),
            duration=int(c.get("duration") or 0),
            synced=_SYNC if c.get("synced") else None,
            plain=_PLAIN if c.get("plain") else None,
            instrumental=bool(c.get("instrumental")),
        )
        for c in candidates
    ]


def _predict(case: dict, allow_low: bool = False) -> tuple[object, object]:
    """返回 (选中的候选下标或 "reject", 打分详情或 None)。"""
    q = case.get("query") or {}
    hits = _to_hits(case.get("candidates") or [])
    result, detail = pick_best_detail(
        hits,
        str(q.get("title") or ""),
        str(q.get("artist") or ""),
        int(q.get("duration") or 0) * 1000,
        str(q.get("album") or ""),
        allow_low=allow_low,
    )
    if result is None:
        return "reject", None
    # 用身份定位而不是 __eq__：候选字段可能高度相似，== 会命中错误的那个
    for index, hit in enumerate(hits):
        if hit is result:
            return index, detail
    return "reject", None


def evaluate(cases: list[dict], verbose: bool = True, detail: bool = False,
             allow_low: bool = False) -> dict:
    rows = []
    for case in cases:
        expect = case.get("expect")
        got, info = _predict(case, allow_low)
        rows.append({"name": case.get("name", "?"), "expect": expect, "got": got,
                     "ok": got == expect, "detail": info})

    should_hit = sum(1 for r in rows if r["expect"] != "reject")
    hits_pred = sum(1 for r in rows if r["got"] != "reject")
    correct_hits = sum(1 for r in rows if r["got"] != "reject" and r["ok"])
    wrong_hits = hits_pred - correct_hits
    missed = sum(1 for r in rows if r["got"] == "reject" and r["expect"] != "reject")
    correct_reject = sum(1 for r in rows if r["got"] == "reject" and r["expect"] == "reject")

    precision = correct_hits / hits_pred if hits_pred else 1.0
    recall = correct_hits / should_hit if should_hit else 1.0
    summary = {
        "total": len(rows), "should_hit": should_hit, "hits_pred": hits_pred,
        "correct_hits": correct_hits, "wrong_hits": wrong_hits, "missed": missed,
        "correct_reject": correct_reject,
        "precision": precision, "recall": recall,
        "wrong_rate": wrong_hits / hits_pred if hits_pred else 0.0,
    }

    if verbose:
        print("=" * 72)
        print("歌词匹配评测（构造式黄金集）")
        print("=" * 72)
        for r in rows:
            mark = "ok  " if r["ok"] else "FAIL"
            print(f"  [{mark}] {r['name']}  expect={r['expect']} got={r['got']}")
            if detail and r["detail"] is not None:
                d = r["detail"]
                print(f"         score={d.score:.2f} conf={d.confidence} "
                      f"title={d.title_sim:.2f} artist={d.artist_sim:.2f} "
                      f"album={d.album_sim:.2f} dur差={d.duration_diff:.0f} "
                      f"| {' / '.join(d.reasons)}")
        print("-" * 72)
        print(f"  用例 {summary['total']}｜应命中 {should_hit}｜应拒绝 "
              f"{summary['total'] - should_hit}")
        print(f"  命中 {hits_pred}（正确 {correct_hits}，误配 {wrong_hits}）｜"
              f"漏配 {missed}｜正确拒绝 {correct_reject}")
        print(f"  precision {precision:.0%}｜recall {recall:.0%}｜"
              f"误配率 {summary['wrong_rate']:.0%}")
    else:
        print(f"precision {precision:.0%}｜recall {recall:.0%}｜"
              f"误配率 {summary['wrong_rate']:.0%}｜用例 {len(rows)}"
              f"（误配 {wrong_hits}，漏配 {missed}）")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=DEFAULT_CASES, help="黄金集 JSON 路径")
    ap.add_argument("--detail", action="store_true", help="打印每个用例的打分详情")
    ap.add_argument("--allow-low", action="store_true",
                    help="放行 low 置信档，用来观察「低置信拒绝了哪些」")
    ap.add_argument("--quiet", action="store_true", help="只打印汇总")
    args = ap.parse_args()
    try:
        with open(args.cases, encoding="utf-8") as f:
            cases = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"读取黄金集失败：{type(exc).__name__}: {exc}")
        return 2
    evaluate(cases, verbose=not args.quiet, detail=args.detail,
             allow_low=args.allow_low)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
