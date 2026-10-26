# -*- coding: utf-8 -*-
"""元数据读取（mutagen 封装）：标题/艺人/专辑/时长/内嵌封面/内嵌歌词。

设计原则：绝不因单个文件标签异常而抛出——任何一段解析失败都回退到
「文件名 / 空值」，由调用方决定如何处理。
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from mutagen.mp3 import MP3
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

from app.models import VIDEO_FORMATS


@dataclass
class TrackMeta:
    path: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    duration_ms: int = 0
    fmt: str = ""
    picture: bytes | None = None       # 内嵌封面（PNG/JPEG 二进制）
    lyrics_text: str | None = None     # 内嵌歌词原文（LRC 或纯文本）
    is_video: bool = False             # v2.1：是否视频文件


def format_from_path(path: str) -> str:
    return os.path.splitext(path)[1].lower().lstrip(".")


def _id3_text(frame) -> str:
    try:
        return str(frame.text[0]) if frame and getattr(frame, "text", None) else ""
    except Exception:  # noqa: BLE001
        return ""


def _vorbis_first(tags, key: str) -> str:
    try:
        vals = tags.get(key)
        if vals:
            return str(vals[0])
    except Exception:  # noqa: BLE001
        pass
    return ""


def _id3_picture(tags) -> bytes | None:
    try:
        frames = tags.getall("APIC")
        front = [f for f in frames if getattr(f, "type", 3) == 3]
        chosen = front[0] if front else (frames[0] if frames else None)
        if chosen is not None:
            return bytes(chosen.data)
    except Exception:  # noqa: BLE001
        pass
    return None


def _id3_lyrics(tags) -> str | None:
    try:
        frames = tags.getall("USLT") or tags.getall("SYLT")
        for f in frames:
            text = getattr(f, "text", "")
            if isinstance(text, list):
                text = "\n".join(str(t) for t in text)
            if text:
                return str(text)
    except Exception:  # noqa: BLE001
        pass
    return None


def _flac_picture(f: FLAC) -> bytes | None:
    try:
        if f.pictures:
            front = [p for p in f.pictures if getattr(p, "type", 3) == 3]
            pic = front[0] if front else f.pictures[0]
            return bytes(pic.data)
    except Exception:  # noqa: BLE001
        pass
    return None


def _ogg_picture(f: OggVorbis) -> bytes | None:
    try:
        for b64 in f.get("metadata_block_picture", []):
            data = base64.b64decode(b64)
            pic = Picture(data)
            if getattr(pic, "type", 3) == 3:
                return bytes(pic.data)
    except Exception:  # noqa: BLE001
        pass
    return None


def _duration_ms(mf) -> int:
    try:
        info = getattr(mf, "info", None)
        length = getattr(info, "length", None)
        if length and length > 0:
            return int(length * 1000)
    except Exception:  # noqa: BLE001
        pass
    return 0


def read_track(path: str) -> TrackMeta | None:
    """读取单个媒体文件元数据；文件不存在返回 None。

    v2.1：视频文件同样支持。MP4/M4V 走 mutagen 的 MP4 解析（可拿到标题与时长），
    其余容器（mkv/avi/webm…）mutagen 读不出标签时以文件名兜底，
    时长由播放器加载后回填（见 ui.main_window._on_duration）。
    """
    if not path or not os.path.isfile(path):
        return None

    meta = TrackMeta(path=path, fmt=format_from_path(path))
    fallback_title = os.path.splitext(os.path.basename(path))[0]
    meta.is_video = meta.fmt in VIDEO_FORMATS

    try:
        mf = mutagen.File(path)
    except Exception:  # noqa: BLE001
        mf = None

    if mf is None:
        # mutagen.File 失败时按扩展名强读一次（部分裸 mp3 需要显式 MP3）
        try:
            mf = MP3(path) if meta.fmt == "mp3" else None
        except Exception:  # noqa: BLE001
            mf = None

    if mf is not None:
        meta.duration_ms = _duration_ms(mf)
        tags = getattr(mf, "tags", None)
        try:
            if isinstance(mf, (MP3, WAVE)) or isinstance(tags, ID3):
                if tags is not None:
                    meta.title = _id3_text(tags.get("TIT2"))
                    meta.artist = _id3_text(tags.get("TPE1"))
                    meta.album = _id3_text(tags.get("TALB"))
                    meta.picture = _id3_picture(tags)
                    meta.lyrics_text = _id3_lyrics(tags)
            elif isinstance(mf, FLAC):
                if tags is not None:
                    meta.title = _vorbis_first(tags, "title")
                    meta.artist = _vorbis_first(tags, "artist")
                    meta.album = _vorbis_first(tags, "album")
                    meta.picture = _flac_picture(mf)
                    meta.lyrics_text = _vorbis_first(tags, "lyrics") or _vorbis_first(tags, "unsyncedlyrics") or None
            elif isinstance(mf, MP4):
                if tags is not None:
                    meta.title = _vorbis_first(tags, "\xa9nam")
                    meta.artist = _vorbis_first(tags, "\xa9ART")
                    meta.album = _vorbis_first(tags, "\xa9alb")
                    covr = tags.get("covr")
                    if covr:
                        meta.picture = bytes(covr[0])
                    meta.lyrics_text = _vorbis_first(tags, "\xa9lyr") or None
            elif isinstance(mf, OggVorbis) and tags is not None:
                meta.title = _vorbis_first(tags, "title")
                meta.artist = _vorbis_first(tags, "artist")
                meta.album = _vorbis_first(tags, "album")
                meta.picture = _ogg_picture(mf)
                meta.lyrics_text = _vorbis_first(tags, "lyrics") or _vorbis_first(tags, "unsyncedlyrics") or None
        except Exception:  # noqa: BLE001
            pass  # 单段失败不影响其他字段

    if not meta.title:
        meta.title = fallback_title
    if not meta.artist and not meta.is_video:
        meta.artist = "未知艺人"
    if not meta.album and not meta.is_video:
        meta.album = "未知专辑"
    return meta


def extract_picture(path: str) -> bytes | None:
    """仅提取内嵌封面（供封面缓存模块调用）。"""
    meta = read_track(path)
    return meta.picture if meta else None
