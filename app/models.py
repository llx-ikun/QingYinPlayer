# -*- coding: utf-8 -*-
"""数据模型：Track / Playlist / Settings。

设计要点：
- Track.id = 路径归一化后的哈希，作为去重与持久化主键；
- 资料库是全部 tracks 的集合，用户歌单只存 track_ids 引用；
- 「最近播放」为虚拟歌单，按 last_played_at 动态生成，不落盘 track_ids。
"""
from __future__ import annotations

import hashlib
import os
import time
import uuid
from dataclasses import dataclass, field

# 支持的音频格式（导入扫描用；实际可播性由播放引擎决定）
AUDIO_EXTENSIONS = (".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wma")

# 播放模式
MODE_SEQUENTIAL = "sequential"   # 顺序播放（播完停止）
MODE_LOOP = "loop"               # 列表循环
MODE_SINGLE = "single"           # 单曲循环
MODE_SHUFFLE = "shuffle"         # 随机播放
PLAY_MODES = (MODE_SEQUENTIAL, MODE_LOOP, MODE_SINGLE, MODE_SHUFFLE)

# 虚拟歌单标识
PLAYLIST_LIBRARY = "__library__"   # 资料库
PLAYLIST_RECENT = "__recent__"     # 最近播放


def make_track_id(path: str) -> str:
    """路径 -> 稳定 ID（大小写不敏感，供 Windows 去重）。"""
    norm = os.path.normcase(os.path.abspath(path))
    return hashlib.md5(norm.encode("utf-8")).hexdigest()[:16]


def now_ts() -> int:
    return int(time.time())


def new_playlist_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Track:
    id: str
    path: str
    title: str = ""
    artist: str = ""
    album: str = ""
    duration_ms: int = 0
    fmt: str = ""
    added_at: int = 0
    last_played_at: int = 0
    play_count: int = 0
    lrc_path: str | None = None      # 手动绑定的歌词文件
    broken: bool = False             # 文件丢失/不可播

    @property
    def display_title(self) -> str:
        return self.title or os.path.splitext(os.path.basename(self.path))[0]

    @property
    def display_artist(self) -> str:
        return self.artist or "未知艺人"

    @property
    def display_album(self) -> str:
        return self.album or "未知专辑"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "duration_ms": self.duration_ms,
            "fmt": self.fmt,
            "added_at": self.added_at,
            "last_played_at": self.last_played_at,
            "play_count": self.play_count,
            "lrc_path": self.lrc_path,
            "broken": self.broken,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Track":
        return cls(
            id=d["id"],
            path=d["path"],
            title=d.get("title", ""),
            artist=d.get("artist", ""),
            album=d.get("album", ""),
            duration_ms=int(d.get("duration_ms", 0)),
            fmt=d.get("fmt", ""),
            added_at=int(d.get("added_at", 0)),
            last_played_at=int(d.get("last_played_at", 0)),
            play_count=int(d.get("play_count", 0)),
            lrc_path=d.get("lrc_path"),
            broken=bool(d.get("broken", False)),
        )


@dataclass
class Playlist:
    id: str
    name: str
    track_ids: list[str] = field(default_factory=list)
    created_at: int = 0
    system: bool = False   # True = 系统虚拟歌单（不可删改名）

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "track_ids": list(self.track_ids),
            "created_at": self.created_at,
            "system": self.system,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Playlist":
        return cls(
            id=d["id"],
            name=d.get("name", "未命名歌单"),
            track_ids=list(d.get("track_ids", [])),
            created_at=int(d.get("created_at", 0)),
            system=bool(d.get("system", False)),
        )


@dataclass
class Settings:
    volume: float = 0.7
    muted: bool = False
    play_mode: str = MODE_LOOP
    last_track_id: str | None = None
    last_position_ms: int = 0
    last_view: str = PLAYLIST_LIBRARY   # 上次所在视图（library / playlist id）

    def to_dict(self) -> dict:
        return {
            "volume": self.volume,
            "muted": self.muted,
            "play_mode": self.play_mode,
            "last_track_id": self.last_track_id,
            "last_position_ms": self.last_position_ms,
            "last_view": self.last_view,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        s = cls()
        s.volume = float(d.get("volume", 0.7))
        s.muted = bool(d.get("muted", False))
        s.play_mode = d.get("play_mode", MODE_LOOP)
        s.last_track_id = d.get("last_track_id")
        s.last_position_ms = int(d.get("last_position_ms", 0))
        s.last_view = d.get("last_view", PLAYLIST_LIBRARY)
        return s
