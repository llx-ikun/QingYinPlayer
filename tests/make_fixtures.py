# -*- coding: utf-8 -*-
"""生成测试夹具：多格式合成音频（含中文文件名、ID3/FLAC/WAVE/Vorbis 标签、内嵌封面、歌词）。

运行：python tests/make_fixtures.py
产物写入 tests/fixtures/_generated/（已被 .gitignore 忽略，可随时重新生成）。

为什么是 `_generated/` 而不是直接写 `tests/fixtures/`：
用户明确要求 `tests/fixtures/我的音乐` 只能放他自己提供的音乐，不得生成或混入
合成音频。此前合成夹具直接写进该目录，导致①该目录每次跑测试都被塞满 6 个
合成文件；②应用导入过这些路径后，夹具被清理时库里留下失效条目。
生成物统一放到 `_generated/` 子目录后，`我的音乐` 永久归用户支配。
子目录名仍保留中文（`我的音乐` / `我的视频`），全链路中文路径编码覆盖不丢。
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

FIXTURES = os.path.join(HERE, "fixtures")
# 合成产物一律落在 _generated/ 下，绝不写进 tests/fixtures/我的音乐（用户专属目录）
GENERATED = os.path.join(FIXTURES, "_generated")
MUSIC_DIR = os.path.join(GENERATED, "我的音乐")   # 中文路径，验证全链路编码


def _tone_bytes(freq=440.0, seconds=2.0, rate=44100):
    """合成单声道 16bit 正弦波 PCM bytes。"""
    import array
    import math
    n = int(seconds * rate)
    buf = array.array("h", [int(0.3 * 32767 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)])
    return buf.tobytes(), rate


def _cover_png(size=64):
    """用 QImage 画一张封面图（渐变 + 手绘音符），无需 PIL。

    注意：Qt 的 QFont/QPainter 在**控件**上绘制时没有应用实例会直接崩溃
    （进程退出码 127 且无 traceback）；这里只画 QImage，不碰控件，故安全。

    特别注意：**不要**在这里创建 QGuiApplication/QApplication——Qt 全进程只允许
    一个 QCoreApplication 实例，一旦这里建了 QGuiApplication，测试里的
    QApplication.instance() 就会返回它，真正的 QApplication 永远建不出来，
    随后任何 QWidget 构造都会崩（退出码 127、无 traceback）。
    """
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter

    img = QImage(size, size, QImage.Format.Format_ARGB32)
    grad = QLinearGradient(QPointF(0, 0), QPointF(size, size))
    grad.setColorAt(0.0, QColor("#5b8cff"))
    grad.setColorAt(1.0, QColor("#a45bff"))
    p = QPainter(img)
    p.fillRect(0, 0, size, size, grad)
    p.setPen(QColor("#ffffff"))
    p.setBrush(QColor("#ffffff"))
    u = float(size)
    p.drawEllipse(QRectF(u * 0.30, u * 0.58, u * 0.22, u * 0.16))
    p.drawLine(QPointF(u * 0.52, u * 0.64), QPointF(u * 0.52, u * 0.22))
    p.drawLine(QPointF(u * 0.52, u * 0.22), QPointF(u * 0.74, u * 0.32))
    p.drawLine(QPointF(u * 0.52, u * 0.36), QPointF(u * 0.74, u * 0.46))
    p.end()
    path = os.path.join(GENERATED, "_cover.png")
    os.makedirs(GENERATED, exist_ok=True)
    img.save(path, "PNG")
    return path


def _write_mp3(path, freq=440.0):
    import lameenc
    pcm, rate = _tone_bytes(freq)
    enc = lameenc.Encoder()
    enc.set_channels(1)
    enc.set_in_sample_rate(rate)
    enc.set_bit_rate(128)
    enc.set_quality(2)
    data = enc.encode(pcm) + enc.flush()
    with open(path, "wb") as f:
        f.write(data)


def _write_lossless(path, fmt, freq=523.0):
    import numpy as np
    import soundfile as sf
    pcm, rate = _tone_bytes(freq)
    sf.write(path, np.frombuffer(pcm, dtype=np.int16), rate, format=fmt)


LRC_TEXT = """[ti:晴天]
[ar:周杰伦]
[al:叶惠美]
[offset:0]
[00:00.50]故事的小黄花
[00:03.20]从出生那年就飘着
[00:06.10]童年的荡秋千
[00:09.00]随记忆一直晃到现在
[00:12.00][00:24.00]Re Do Si Re Do Si La
[00:15.50]♪ 哼唱 ♪
[00:18.00]合成音频测试行
"""

# ---------- 视频夹具（v2.1） ----------

# 沙箱内没有 ffmpeg CLI，QMediaRecorder 也因无采集设备不可用，
# 因此用「Qt 合成 JPEG 帧 + 纯 Python 写 RIFF/AVI 容器」的方式造视频。
# 产物是**真实可播放**的 MJPEG AVI（FFmpeg 后端可解码，实测 duration 正确），
# 而不是占位文件——这样视频链路的解码、时长、画面输出都能被自动化断言。
VIDEO_DIR = os.path.join(GENERATED, "我的视频")
VIDEO_NAME = "测试短片.avi"
VIDEO_W, VIDEO_H, VIDEO_FPS, VIDEO_FRAMES = 320, 240, 5, 10


def _jpeg_frame(index: int, width: int, height: int) -> bytes:
    """合成一帧彩色画面并编码为 JPEG 字节流。"""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    img = QImage(width, height, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.fillRect(img.rect(), QColor((index * 25) % 255, 90, 200))
    p.setPen(QColor("#ffffff"))
    # 画一个随帧数移动的方块，便于断言「画面确实在更新」
    offset = (index * 12) % max(1, width - 40)
    p.fillRect(QRectF(offset, height / 3, 40, 40), QColor("#ffffff"))
    p.end()
    path = os.path.join(GENERATED, "_frame.jpg")
    os.makedirs(GENERATED, exist_ok=True)
    img.save(path, "JPEG", 85)
    with open(path, "rb") as f:
        data = f.read()
    os.remove(path)
    return data


def _riff_chunk(tag: bytes, data: bytes) -> bytes:
    out = tag + struct.pack("<I", len(data)) + data
    if len(data) % 2:
        out += b"\x00"   # RIFF 块按偶数字节对齐
    return out


def _riff_list(list_type: bytes, payload: bytes) -> bytes:
    body = list_type + payload
    return b"LIST" + struct.pack("<I", len(body)) + body


def _build_avi(frames: list[bytes], width: int, height: int, fps: int) -> bytes:
    """组装 MJPEG AVI（单视频流，无音轨）。"""
    count = len(frames)
    max_size = max(len(f) for f in frames)

    avih = struct.pack(
        "<IIIIIIIIII4I",
        int(1_000_000 / fps),   # dwMicroSecPerFrame
        max_size * fps,         # dwMaxBytesPerSec
        0,                      # dwPaddingGranularity
        0x10,                   # dwFlags: AVIF_HASINDEX
        count,                  # dwTotalFrames
        0,                      # dwInitialFrames
        1,                      # dwStreams
        max_size,               # dwSuggestedBufferSize
        width, height,
        0, 0, 0, 0,             # dwReserved[4]
    )
    strh = struct.pack(
        "<4s4sIHHIIIIIIIIhhhh",
        b"vids", b"MJPG",
        0,                      # dwFlags
        0, 0,                   # wPriority, wLanguage
        0,                      # dwInitialFrames
        1,                      # dwScale
        fps,                    # dwRate
        0,                      # dwStart
        count,                  # dwLength
        max_size,               # dwSuggestedBufferSize
        0xFFFFFFFF,             # dwQuality
        0,                      # dwSampleSize
        0, 0, width, height,    # rcFrame
    )
    strf = struct.pack(
        "<IiiHH4sIiiII",
        40, width, height, 1, 24, b"MJPG", width * height * 3, 0, 0, 0, 0,
    )
    strl = _riff_list(b"strl", _riff_chunk(b"strh", strh) + _riff_chunk(b"strf", strf))
    hdrl = _riff_list(b"hdrl", _riff_chunk(b"avih", avih) + strl)

    movi_payload = b""
    index = b""
    base = 4   # dwChunkOffset 相对 'movi' FOURCC 起点的偏移
    for data in frames:
        offset = base + len(movi_payload)
        movi_payload += _riff_chunk(b"00dc", data)
        index += struct.pack("<4sIII", b"00dc", 0x10, offset, len(data))
    movi = _riff_list(b"movi", movi_payload)
    idx1 = _riff_chunk(b"idx1", index)

    body = b"AVI " + hdrl + movi + idx1
    return b"RIFF" + struct.pack("<I", len(body)) + body


def ensure_video_fixture() -> str:
    """确保视频夹具存在（幂等）；返回视频文件路径。"""
    path = os.path.join(VIDEO_DIR, VIDEO_NAME)
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    os.makedirs(VIDEO_DIR, exist_ok=True)
    frames = [_jpeg_frame(i, VIDEO_W, VIDEO_H) for i in range(VIDEO_FRAMES)]
    with open(path, "wb") as f:
        f.write(_build_avi(frames, VIDEO_W, VIDEO_H, VIDEO_FPS))
    return path


def _tag_mp3(path, cover_path, with_lyrics=True):
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, APIC, USLT
    tags = ID3()
    tags.add(TIT2(encoding=3, text="晴天"))
    tags.add(TPE1(encoding=3, text="周杰伦"))
    tags.add(TALB(encoding=3, text="叶惠美"))
    tags.add(TCON(encoding=3, text="流行"))
    with open(cover_path, "rb") as f:
        tags.add(APIC(encoding=3, mime="image/png", type=3, desc="Cover", data=f.read()))
    if with_lyrics:
        tags.add(USLT(encoding=3, lang="chi", desc="", text="内嵌纯文本歌词第一行\n内嵌纯文本歌词第二行"))
    tags.save(path)


def _tag_flac(path, cover_path):
    from mutagen.flac import FLAC, Picture
    f = FLAC(path)
    f["title"] = ["夜曲"]
    f["artist"] = ["周杰伦"]
    f["album"] = ["十一月的萧邦"]
    pic = Picture()
    with open(cover_path, "rb") as fh:
        pic.data = fh.read()
    pic.type = 3
    pic.mime = "image/png"
    f.add_picture(pic)
    f["lyrics"] = ["[00:01.00]FLAC 内嵌歌词第一行\n[00:02.00]FLAC 内嵌歌词第二行"]
    f.save()


def _tag_wav(path):
    from mutagen.id3 import TALB, TPE1, TIT2
    from mutagen.wave import WAVE
    f = WAVE(path)
    if f.tags is None:
        f.add_tags()
    f.tags.add(TIT2(encoding=3, text="晨间轻音乐"))
    f.tags.add(TPE1(encoding=3, text="测试艺术家"))
    f.tags.add(TALB(encoding=3, text="测试专辑"))
    f.save()


def _tag_ogg(path):
    from mutagen.oggvorbis import OggVorbis
    f = OggVorbis(path)
    f["title"] = ["海浪的声音"]
    f["artist"] = ["自然白噪音"]
    f["album"] = ["放松"]
    f.save()


def ensure_fixtures() -> str:
    """确保夹具存在（幂等）；返回音乐目录路径。

    逐文件校验而非只查 .done 标记：标记可能在文件被外部清理后仍然存在
    （曾因只剩标记导致 read_track 返回 None、测试 setUp 批量报错）。
    """
    expected = [
        "晴天 - 周杰伦.mp3",
        "晴天 - 周杰伦.lrc",
        "夜曲.flac",
        "晨间轻音乐.wav",
        "海浪的声音.ogg",
        "无标签音频.mp3",
    ]
    if all(os.path.isfile(os.path.join(MUSIC_DIR, name)) for name in expected):
        return MUSIC_DIR

    os.makedirs(MUSIC_DIR, exist_ok=True)
    marker = os.path.join(GENERATED, ".done")
    cover = _cover_png()

    # 1. 带 ID3 标签 + 封面 + 内嵌歌词的 MP3 + 同名 LRC
    mp3 = os.path.join(MUSIC_DIR, "晴天 - 周杰伦.mp3")
    _write_mp3(mp3, 440.0)
    _tag_mp3(mp3, cover)
    with open(os.path.join(MUSIC_DIR, "晴天 - 周杰伦.lrc"), "w", encoding="utf-8") as f:
        f.write(LRC_TEXT)

    # 2. FLAC（标签 + 内嵌封面 + 内嵌歌词）
    flac = os.path.join(MUSIC_DIR, "夜曲.flac")
    _write_lossless(flac, "FLAC", 523.0)
    _tag_flac(flac, cover)

    # 3. WAV（INFO 标签）
    wav = os.path.join(MUSIC_DIR, "晨间轻音乐.wav")
    _write_lossless(wav, "WAV", 349.0)
    _tag_wav(wav)

    # 4. OGG Vorbis（标签）
    ogg = os.path.join(MUSIC_DIR, "海浪的声音.ogg")
    _write_lossless(ogg, "OGG", 392.0)
    _tag_ogg(ogg)

    # 5. 无标签 MP3（标题回退为文件名）
    bare = os.path.join(MUSIC_DIR, "无标签音频.mp3")
    _write_mp3(bare, 294.0)

    with open(marker, "w", encoding="utf-8") as f:
        f.write("ok")
    print(f"夹具已生成: {MUSIC_DIR}")
    return MUSIC_DIR


if __name__ == "__main__":
    ensure_fixtures()
    print(f"视频夹具已生成: {ensure_video_fixture()}")
