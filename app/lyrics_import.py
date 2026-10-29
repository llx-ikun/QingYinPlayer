# -*- coding: utf-8 -*-
"""歌词文件批量导入：按文件名把 .lrc / .txt 匹配到曲目（纯逻辑，可单测）。

用户「自己导入歌词」的落地：把一摞歌词文件按文件名认到曲库里的歌。
匹配规则保守——**宁可跳过，也不配错**：一个文件名键命中多首就视为歧义跳过。
函数名沿用 `match_lrc_files`（历史命名），但对 .txt 同样适用——它只取文件名
去扩展名后归一化匹配，不关心是 .lrc 还是 .txt。
"""
from __future__ import annotations

import os


def normalize_key(text: str) -> str:
    """归一化匹配键：小写 + 只留字母数字（含中文），去掉空格/标点/扩展名差异。"""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def track_keys(track) -> list[str]:
    """一首曲目所有可能的匹配键（去重，按优先级：文件名 → 标题 → 艺人 → 组合）。"""
    base = os.path.splitext(os.path.basename(track.path or ""))[0]
    keys: list[str] = []
    for candidate in (base, getattr(track, "title", ""), getattr(track, "artist", "")):
        key = normalize_key(candidate)
        if key and key not in keys:
            keys.append(key)
    title = normalize_key(getattr(track, "title", ""))
    artist = normalize_key(getattr(track, "artist", ""))
    for combo in (f"{title}{artist}", f"{artist}{title}"):
        if title and artist and combo not in keys:
            keys.append(combo)
    return keys


def match_lrc_files(lrc_paths: list[str], tracks: list) -> tuple[dict, list]:
    """把 .lrc 文件名匹配到曲目。

    返回 `(matched, unmatched)`：
    - `matched`: `{lrc_path: track}`，每个 .lrc 至多认到一首；
    - `unmatched`: 认不出（键为空 / 无命中 / 命中多首歧义）的 .lrc 路径。

    歧义判定：同一个归一化键命中**多首不同曲目**时跳过——比如两张专辑里都有
    `晴天.lrc`，没法仅凭文件名区分，就别乱绑。
    """
    index: dict[str, list] = {}
    for track in tracks:
        for key in track_keys(track):
            bucket = index.setdefault(key, [])
            if not any(t is track for t in bucket):
                bucket.append(track)

    matched: dict = {}
    unmatched: list[str] = []
    for path in lrc_paths:
        key = normalize_key(os.path.splitext(os.path.basename(path))[0])
        hits = index.get(key)
        if key and hits and len(hits) == 1:
            matched[path] = hits[0]
        else:
            unmatched.append(path)
    return matched, unmatched
