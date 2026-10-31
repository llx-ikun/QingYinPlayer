# -*- coding: utf-8 -*-
"""Phase 0 探针：验证 faster-whisper 能本地跑通并产出词级时间戳。

用途（v3.0.0「AI 对齐歌词」可行性关卡）：
- 确认 ctranslate2 / av / onnxruntime 在本机 Python 3.13 下能加载；
- 确认 `transcribe(word_timestamps=True)` 的词级时间戳结构可用；
- 记录单首耗时与模型体积，用于回填 DESIGN 40.7 的体积/性能估算。

用法：
    env -u PYTHONPATH .venv/Scripts/python.exe tools/probe_asr.py \
        --audio tests/fixtures/_generated/我的音乐/晴天 - 周杰伦.mp3 --model base

国内网络访问 HF 常失败，脚本会默认把 HF_ENDPOINT 指向镜像（可用 --endpoint 覆盖）。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--model", default="base", help="tiny / base / small / medium")
    ap.add_argument("--language", default="zh")
    ap.add_argument("--endpoint", default="https://hf-mirror.com")
    ap.add_argument("--head", type=int, default=12, help="打印前 N 个词")
    ap.add_argument("--vad", action="store_true", help="启用 VAD（需 onnxruntime + silero 模型）")
    args = ap.parse_args()

    if args.endpoint:
        os.environ.setdefault("HF_ENDPOINT", args.endpoint)
    # 镜像站不支持 Xet 存储：hf-xet 会去 cas-server.xethub.hf.co 取文件并拿到 401。
    # 关掉 Xet 退回普通 HTTP 下载即可；顺带证明 hf_xet 可以整个从安装包里排除。
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    audio = os.path.abspath(args.audio)
    if not os.path.isfile(audio):
        print(f"音频不存在: {audio}")
        return 2

    t0 = time.perf_counter()
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        print(f"[FAIL] 导入 faster_whisper 失败: {type(exc).__name__}: {exc}")
        return 3
    print(f"[OK] import faster_whisper  用时 {time.perf_counter() - t0:.2f}s")

    t0 = time.perf_counter()
    try:
        model = WhisperModel(args.model, device="cpu", compute_type="int8")
    except Exception as exc:
        print(f"[FAIL] 加载模型失败: {type(exc).__name__}: {exc}")
        return 4
    print(f"[OK] 加载模型 {args.model}  用时 {time.perf_counter() - t0:.2f}s")

    t0 = time.perf_counter()
    # 自己解码：faster-whisper 默认走 av，但 av 19 删掉了 metadata_errors 参数
    # （faster-whisper 1.2.1 还在传），直接传文件必崩。项目本来就有 miniaudio 解码，
    # 顺手把 L1 的中置声道提取也在这里做，av 可以整个从安装包里排除。
    import numpy as np

    from app.lyrics_local_align import decode_mono
    try:
        raw, sr = decode_mono(audio, 16000)
    except Exception as exc:
        print(f"[FAIL] miniaudio 解码失败: {type(exc).__name__}: {exc}")
        return 6
    pcm = np.array(raw, dtype=np.float32)
    print(f"[OK] 解码 {len(pcm) / sr:.1f}s @ {sr}Hz  用时 {time.perf_counter() - t0:.2f}s")

    t0 = time.perf_counter()
    segments, info = model.transcribe(
        pcm, language=args.language, word_timestamps=True,
        vad_filter=args.vad, beam_size=5)
    seg_list = list(segments)          # 生成器，必须消费才真正跑
    elapsed = time.perf_counter() - t0
    print(f"[OK] 推理完成  用时 {elapsed:.2f}s  "
          f"音频时长 {info.duration:.1f}s  语言 {info.language}")

    words = [(w.start, w.end, w.word, getattr(w, "probability", 0.0))
             for seg in seg_list for w in (seg.words or [])]
    print(f"段数 {len(seg_list)} / 词数 {len(words)}")
    if not words:
        print("[FAIL] 没有拿到词级时间戳")
        return 5
    for start, end, word, prob in words[:args.head]:
        print(f"  {start:7.2f} -> {end:7.2f}  p={prob:.2f}  {word!r}")

    # 模型缓存体积
    cache = os.environ.get("HF_HUB_CACHE") or os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface", "hub")
    total = 0
    for root, _dirs, files in os.walk(cache):
        for name in files:
            with _suppress():
                total += os.path.getsize(os.path.join(root, name))
    print(f"HF 缓存 {cache}  合计 {total / 1024 / 1024:.1f} MB")
    print("PHASE0-P0-2 PASS")
    return 0


class _suppress:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True


if __name__ == "__main__":
    raise SystemExit(main())
