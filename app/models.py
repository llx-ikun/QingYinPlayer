# -*- coding: utf-8 -*-
"""数据模型：Track / Playlist / Settings。

设计要点：
- Track.id = 路径归一化后的哈希，作为去重与持久化主键；
- 音乐库是全部 tracks 的集合，用户歌单只存 track_ids 引用；
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

# 支持的视频格式（v2.1：本地视频导入 + 画面播放）
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v")

# 导入扫描用的全部媒体扩展名
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS + VIDEO_EXTENSIONS

# 自定义背景的四种形态（v2.2）
BG_TYPES = ("none", "color", "gradient", "image")

# 视频扩展名（不带点），用于按 fmt 派生 is_video
VIDEO_FORMATS = frozenset(ext.lstrip(".") for ext in VIDEO_EXTENSIONS)

# 播放模式
MODE_SEQUENTIAL = "sequential"   # 顺序播放（播完停止）
MODE_LOOP = "loop"               # 列表循环
MODE_SINGLE = "single"           # 单曲循环
MODE_SHUFFLE = "shuffle"         # 随机播放
PLAY_MODES = (MODE_SEQUENTIAL, MODE_LOOP, MODE_SINGLE, MODE_SHUFFLE)

# 歌词播放动效（v2.6.4）：none 无特效 / zoom 当前行放大 / typewriter 打字机 /
# karaoke 颜色随进度逐渐覆盖。单选，值持久化进 Settings.lyrics_effect。
LYRICS_EFFECTS = ("none", "zoom", "typewriter", "karaoke")

# 虚拟歌单标识
PLAYLIST_LIBRARY = "__library__"   # 音乐库
PLAYLIST_RECENT = "__recent__"     # 最近播放
PLAYLIST_FAVORITES = "__favorites__"  # 我喜欢（v2.0：落盘为 system 歌单，见 store）


def make_track_id(path: str) -> str:
    """路径 -> 稳定 ID（大小写不敏感，供 Windows 去重）。"""
    norm = os.path.normcase(os.path.abspath(path))
    return hashlib.md5(norm.encode("utf-8")).hexdigest()[:16]


def now_ts() -> int:
    return int(time.time())


def new_playlist_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------- v2.7.5：读 json 时的类型收敛 ----------
#
# 背景：data.json 是用户目录里的明文文件，可能被手工编辑、被旧版本写入、
# 被非正常退出截断。原来的 `float(d.get("volume", 0.7))` 一旦遇到 null
# 或 "大声" 这类值就抛异常，而它在 Settings.from_dict 的第一行 —— 整个
# 设置对象构造失败，音量/主题/强调色/背景/昵称全部回默认且无人提示。
#
# 收敛原则：**读到的任何值都不能让加载流程失败**，脏值就退回默认。

MAX_POSITION_MS = 24 * 60 * 60 * 1000      # 单曲进度上限，防止脏值当进度 seek


def _as_float(value, default: float, low: float, high: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result:            # NaN 自己不等于自己
        return default
    return max(low, min(high, result))


def _as_int(value, default: int, low: int, high: int) -> int:
    try:
        result = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(low, min(high, result))


def _as_str(value, default: str, *, allow_empty: bool = False) -> str:
    if isinstance(value, str) and (allow_empty or value.strip()):
        return value
    return default


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
    def is_video(self) -> bool:
        """是否视频文件：按 fmt 派生（旧数据 fmt 为空时回退到路径扩展名）。

        不新增 JSON 字段——视频/音频由文件扩展名唯一确定，旧歌单与设置无需迁移。
        """
        fmt = (self.fmt or "").lower()
        if fmt:
            return fmt in VIDEO_FORMATS
        ext = os.path.splitext(self.path or "")[1].lower()
        return ext in VIDEO_EXTENSIONS

    @property
    def display_artist(self) -> str:
        if self.is_video and not self.artist:
            return "本地视频"
        return self.artist or "未知艺人"

    @property
    def display_album(self) -> str:
        if self.is_video and not self.album:
            return "视频文件"
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
class BackgroundConfig:
    """一页的自定义背景（v2.2）。

    为什么不是「4 个独立设置」而是一个配置对象：背景的四种形态（纯色/渐变/图片）
    各用其中一部分字段，把 type 和它的参数绑在一起才不会出现「选了纯色但还带着
    昨天的图片路径」这种自相矛盾的状态。
    """

    type: str = "none"          # none | color | gradient | image
    color: str = "#3b82f6"      # 纯色 / 渐变起始色
    color2: str = "#8b5cf6"     # 渐变终止色
    image: str = ""             # 图片路径（导入时复制进数据目录 bgs/）
    opacity: float = 1.0        # 背景层不透明度 0.2~1.0
    blur: int = 0               # 高斯模糊半径 px（0 = 不模糊）
    dim: float = 0.0            # 暗化 0~0.7（把背景压暗，保证前景文字可读）
    inherit: bool = True        # True = 跟随「全部页面」的设置（仅分页面时有意义）

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "color": self.color,
            "color2": self.color2,
            "image": self.image,
            "opacity": self.opacity,
            "blur": self.blur,
            "dim": self.dim,
            "inherit": self.inherit,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BackgroundConfig":
        cfg = cls()
        if not isinstance(d, dict):
            return cfg
        bg_type = str(d.get("type") or "none")
        cfg.type = bg_type if bg_type in BG_TYPES else "none"
        for key in ("color", "color2"):
            value = d.get(key)
            if isinstance(value, str) and value:
                setattr(cfg, key, value)
        cfg.image = str(d.get("image") or "")
        try:
            cfg.opacity = max(0.2, min(1.0, float(d.get("opacity", 1.0))))
        except (TypeError, ValueError):
            cfg.opacity = 1.0
        try:
            cfg.blur = max(0, min(60, int(d.get("blur", 0))))
        except (TypeError, ValueError):
            cfg.blur = 0
        try:
            cfg.dim = max(0.0, min(0.7, float(d.get("dim", 0.0))))
        except (TypeError, ValueError):
            cfg.dim = 0.0
        cfg.inherit = bool(d.get("inherit", True))
        return cfg


@dataclass
class Settings:
    volume: float = 0.7
    muted: bool = False
    play_mode: str = MODE_LOOP
    last_track_id: str | None = None
    last_position_ms: int = 0
    last_view: str = PLAYLIST_LIBRARY   # 上次所在视图（library / playlist id）
    theme: str = "light"                # 默认主题（columbina 深色 / light 浅色）
    nickname: str = "音乐爱好者"         # v2.0：侧边栏用户卡片昵称
    online_lyrics: bool = True          # v2.2：本地无歌词时联网补（LRCLIB）
    accent_color: str = ""              # v2.2：自定义强调色（""=跟随主题默认）
    font_scale: float = 1.0             # v2.2：字号缩放（0.85~1.30）
    lyrics_effect: str = "none"         # v2.6.4：歌词播放动效（none/zoom/typewriter/karaoke）
    # v2.2 自定义背景：三个作用域（全部 / 列表页 / 正在播放页）
    bg_all: BackgroundConfig = field(default_factory=BackgroundConfig)
    bg_library: BackgroundConfig = field(default_factory=BackgroundConfig)
    bg_now: BackgroundConfig = field(default_factory=BackgroundConfig)

    def bg_config(self, page: str) -> BackgroundConfig:
        """取某一页实际生效的背景：本页没单独设过就退回「全部页面」。"""
        per_page = {"library": self.bg_library, "now_playing": self.bg_now}
        cfg = per_page.get(page)
        if cfg is not None and not cfg.inherit:
            return cfg
        return self.bg_all

    def set_bg_config(self, scope: str, cfg: BackgroundConfig) -> None:
        if scope == "library":
            self.bg_library = cfg
        elif scope == "now_playing":
            self.bg_now = cfg
        else:
            self.bg_all = cfg

    def to_dict(self) -> dict:
        return {
            "volume": self.volume,
            "muted": self.muted,
            "play_mode": self.play_mode,
            "last_track_id": self.last_track_id,
            "last_position_ms": self.last_position_ms,
            "last_view": self.last_view,
            "theme": self.theme,
            "nickname": self.nickname,
            "online_lyrics": self.online_lyrics,
            "accent_color": self.accent_color,
            "font_scale": self.font_scale,
            "lyrics_effect": self.lyrics_effect,
            "bg": {
                "all": self.bg_all.to_dict(),
                "library": self.bg_library.to_dict(),
                "now_playing": self.bg_now.to_dict(),
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        s = cls()
        if not isinstance(d, dict):         # v2.7.5：settings 是 null / 数组等
            return s
        # v2.7.5：所有字段都过一遍类型收敛。原来 volume 与 last_position_ms
        # 是裸 float()/int()，一个 null 就让整块设置回默认（见文件上方说明）。
        s.volume = _as_float(d.get("volume"), 0.7, 0.0, 1.0)
        s.muted = bool(d.get("muted", False))
        mode = d.get("play_mode")
        s.play_mode = mode if mode in PLAY_MODES else MODE_LOOP
        tid = d.get("last_track_id")
        s.last_track_id = tid if isinstance(tid, str) and tid else None
        s.last_position_ms = _as_int(d.get("last_position_ms"), 0, 0, MAX_POSITION_MS)
        view = d.get("last_view")
        s.last_view = view if isinstance(view, str) and view else PLAYLIST_LIBRARY
        s.theme = d.get("theme") or "light"
        s.nickname = _as_str(d.get("nickname"), "音乐爱好者")
        s.online_lyrics = bool(d.get("online_lyrics", True))
        s.accent_color = _as_str(d.get("accent_color"), "", allow_empty=True)
        s.font_scale = _as_float(d.get("font_scale"), 1.0, 0.5, 3.0)
        effect = d.get("lyrics_effect")
        s.lyrics_effect = effect if effect in LYRICS_EFFECTS else "none"
        bg = d.get("bg") or {}
        if isinstance(bg, dict):
            s.bg_all = BackgroundConfig.from_dict(bg.get("all") or {})
            s.bg_library = BackgroundConfig.from_dict(bg.get("library") or {})
            s.bg_now = BackgroundConfig.from_dict(bg.get("now_playing") or {})
        return s
