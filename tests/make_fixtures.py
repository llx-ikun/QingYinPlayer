# -*- coding: utf-8 -*-
"""生成测试夹具：多格式合成音频（含中文文件名、ID3/FLAC/WAVE/Vorbis 标签、内嵌封面、歌词）。

运行：python tests/make_fixtures.py
产物写入 tests/fixtures/（已被 .gitignore 忽略，可随时重新生成）。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

FIXTURES = os.path.join(HERE, "fixtures")
MUSIC_DIR = os.path.join(FIXTURES, "我的音乐")   # 中文路径，验证全链路编码


def _tone_bytes(freq=440.0, seconds=2.0, rate=44100):
    """合成单声道 16bit 正弦波 PCM bytes。"""
    import array
    import math
    n = int(seconds * rate)
    buf = array.array("h", [int(0.3 * 32767 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)])
    return buf.tobytes(), rate


def _cover_png(size=64):
    """用 QImage 画一张封面图（渐变 + ♫），无需 PIL。

    注意：Qt 的 QFont/QPainter 在没有 QGuiApplication 实例时会直接崩溃
    （进程退出码 127 且无 traceback），因此这里先确保应用实例存在。
    """
    from PySide6.QtGui import QGuiApplication, QImage, QPainter, QLinearGradient, QColor, QFont
    from PySide6.QtCore import QPointF, Qt

    if QGuiApplication.instance() is None:
        QGuiApplication(sys.argv[:1])
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    grad = QLinearGradient(QPointF(0, 0), QPointF(size, size))
    grad.setColorAt(0.0, QColor("#5b8cff"))
    grad.setColorAt(1.0, QColor("#a45bff"))
    p = QPainter(img)
    p.fillRect(0, 0, size, size, grad)
    p.setPen(QColor("#ffffff"))
    f = QFont()
    f.setPixelSize(int(size * 0.6))
    f.setBold(True)
    p.setFont(f)
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, "♫")
    p.end()
    path = os.path.join(FIXTURES, "_cover.png")
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
    """确保夹具存在（幂等）；返回音乐目录路径。"""
    marker = os.path.join(FIXTURES, ".done")
    if os.path.isdir(MUSIC_DIR) and os.path.exists(marker):
        return MUSIC_DIR

    os.makedirs(MUSIC_DIR, exist_ok=True)
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
