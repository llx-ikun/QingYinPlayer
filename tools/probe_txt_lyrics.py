"""探针：纯文本 .txt 歌词在解析链上哪几步被改动（行数/内容）。

用途：判断「歌词不完全匹配 txt」到底丢在哪一步：
  strip_meta_lines（删头部信息行） / parse_plain（丢空行） / pair_bilingual（配句合并）

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_txt_lyrics.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lyrics import (  # noqa: E402
    lyrics_from_text,
    pair_bilingual,
    strip_meta_lines,
)


def _nonempty(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


CASES: dict[str, str] = {
    "A 中文单语 + 头部信息 + 空行分段": "\n".join([
        "唯有追赶风的方向 (Only By Chasing the)",
        "作词 : 音融三喜",
        "作曲 : 音融三喜",
        "编曲 : 音融三喜",
        "",
        "风将吹向何方",
        "我追着光",
        "",
        "(间奏)",
        "",
        "雨落在肩上",
        "我不再回头",
    ]),
    "B 双语交替": "\n".join([
        "Who can surely know",
        "风将吹向何方",
        "I chase the light",
        "我追着光",
        "Rain falls on my shoulder",
        "雨落在肩上",
    ]),
    "C 正文里出现『制作』字样": "\n".join([
        "风将吹向何方",
        "制作 : 这是一句歌词",
        "我追着光",
    ]),
    "D 方括号非时间戳": "\n".join([
        "[Verse 1]",
        "风将吹向何方",
        "[Chorus]",
        "我追着光",
    ]),
    "E 纯单语（对照组）": "\n".join([
        "风将吹向何方",
        "我追着光",
        "雨落在肩上",
    ]),
}


def main() -> int:
    for name, text in CASES.items():
        raw = _nonempty(text)
        stripped = _nonempty(strip_meta_lines(text))
        synced, plain = lyrics_from_text(text)
        rows = pair_bilingual(plain) if plain else []
        print(f"--- {name}")
        print(f"    txt 非空行 {len(raw)} -> 去元数据 {len(stripped)} -> 解析 {len(plain)} 行"
              f" / 双语配句 {len(rows)} 句")
        lost = [ln for ln in raw if ln not in stripped]
        if lost:
            print(f"    [删行] {lost}")
        paired = len(plain) - len(rows)
        if paired:
            print(f"    [合并] 配句后少了 {paired} 行（译文并进原文行）")
        if synced:
            print(f"    [注意] 被当成同步歌词解析：{len(synced)} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
