# -*- coding: utf-8 -*-
"""一次性技术探测脚本（不属于应用本体，验证后保留备查）。

验证目标：
1. PySide6 QtMultimedia (Windows WMF 后端) 能加载/解码哪些音频格式
2. miniaudio 能解码哪些格式（作为备选引擎）
3. mutagen 能否读取各格式元数据
4. PySide6 wheel 是否自带 ffmpeg multimedia 插件
"""
import os
import sys
import array
import math

HERE = os.path.dirname(os.path.abspath(__file__))
TESTDIR = os.path.join(HERE, "files")
os.makedirs(TESTDIR, exist_ok=True)


def gen_tone(freq=440.0, seconds=2.0, rate=44100):
    n = int(seconds * rate)
    return array.array("h", [int(0.3 * 32767 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]), rate


def gen_wav():
    import wave
    buf, rate = gen_tone()
    p = os.path.join(TESTDIR, "tone.wav")
    with wave.open(p, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(buf.tobytes())
    return p


def gen_flac():
    import numpy as np
    import soundfile as sf
    buf, rate = gen_tone()
    p = os.path.join(TESTDIR, "tone.flac")
    sf.write(p, np.frombuffer(buf.tobytes(), dtype=np.int16), rate, format="FLAC")
    return p


def gen_ogg():
    import numpy as np
    import soundfile as sf
    buf, rate = gen_tone()
    p = os.path.join(TESTDIR, "tone.ogg")
    sf.write(p, np.frombuffer(buf.tobytes(), dtype=np.int16), rate, format="OGG")
    return p


def gen_mp3():
    import lameenc
    buf, rate = gen_tone()
    enc = lameenc.Encoder()
    enc.set_channels(1)
    enc.set_in_sample_rate(rate)
    enc.set_bit_rate(128)
    enc.set_quality(2)
    data = enc.encode(buf.tobytes())
    data += enc.flush()
    p = os.path.join(TESTDIR, "tone.mp3")
    with open(p, "wb") as f:
        f.write(data)
    return p


def list_qt_multimedia_plugins():
    import PySide6
    d = os.path.join(os.path.dirname(PySide6.__file__), "Qt", "plugins", "multimedia")
    if os.path.isdir(d):
        return sorted(os.listdir(d))
    return ["(无 multimedia 插件目录，FFmpeg 后端应直接内置于 Qt6Multimedia)"]


def probe_qt(path, timeout_ms=4000):
    """用 QMediaPlayer 尝试加载并播放文件。"""
    from PySide6.QtCore import QUrl, QEventLoop, QTimer
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

    player = QMediaPlayer()
    audio = QAudioOutput()
    player.setAudioOutput(audio)
    result = {"status": None, "duration_ms": 0, "error": "", "play_pos_ms": -1, "play_state": ""}
    done = {"v": False}

    def on_status(s):
        result["status"] = s.name
        if s.name in ("LoadedMedia", "BufferedMedia", "EndOfMedia", "InvalidMedia") and not done["v"]:
            done["v"] = True
            loop.quit()

    def on_error(err, msg):
        result["error"] = msg
        if not done["v"]:
            done["v"] = True
            loop.quit()

    player.mediaStatusChanged.connect(on_status)
    player.errorOccurred.connect(on_error)

    loop = QEventLoop()
    player.setSource(QUrl.fromLocalFile(path))
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()

    result["duration_ms"] = player.duration()
    if not result["error"]:
        result["error"] = player.errorString()

    # 播放 800ms，检查 position 是否推进（验证解码+输出链路）
    player.setPosition(0)
    player.play()
    import time
    from PySide6.QtCore import QCoreApplication
    t0 = time.time()
    while time.time() - t0 < 0.9:
        QCoreApplication.processEvents()
        time.sleep(0.05)
    result["play_pos_ms"] = player.position()
    result["play_state"] = player.playbackState().name
    player.stop()
    return result


def probe_miniaudio(path):
    import miniaudio
    try:
        snd = miniaudio.decode_file(
            path,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=2,
            sample_rate=44100,
        )
        return {"ok": True, "duration_s": round(snd.duration, 3), "frames": len(snd.samples)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def probe_mutagen(path):
    import mutagen
    try:
        f = mutagen.File(path)
        if f is None:
            return {"ok": False, "error": "mutagen 返回 None"}
        return {"ok": True, "type": type(f).__name__, "length_s": round(getattr(f.info, "length", 0.0), 3)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    print("== Qt multimedia 插件 ==")
    print("  ", list_qt_multimedia_plugins())

    gens = {"wav": gen_wav, "flac": gen_flac, "ogg": gen_ogg, "mp3": gen_mp3}
    files = {}
    for ext, fn in gens.items():
        try:
            files[ext] = fn()
            print(f"[生成] {ext}: OK -> {files[ext]}")
        except Exception as e:  # noqa: BLE001
            print(f"[生成] {ext}: FAIL -> {e}")

    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    print("\n== QMediaPlayer (WMF) 加载探测 ==")
    qt_results = {}
    for ext, path in files.items():
        r = probe_qt(path)
        qt_results[ext] = r
        print(f"  {ext:5s} status={r['status']} duration={r['duration_ms']}ms error={r['error']!r}")

    print("\n== miniaudio 解码探测 ==")
    for ext, path in files.items():
        r = probe_miniaudio(path)
        print(f"  {ext:5s} {r}")

    print("\n== mutagen 读取探测 ==")
    for ext, path in files.items():
        r = probe_mutagen(path)
        print(f"  {ext:5s} {r}")

    print("\n== 结论摘要 ==")
    playable_qt = [e for e, r in qt_results.items()
                   if r["status"] in ("LoadedMedia", "BufferedMedia", "EndOfMedia") and r["duration_ms"] > 0]
    print("  QMediaPlayer 可播放:", playable_qt or "无")
    print("  播放推进(position/state):", {e: (r["play_pos_ms"], r["play_state"]) for e, r in qt_results.items()})


if __name__ == "__main__":
    main()
