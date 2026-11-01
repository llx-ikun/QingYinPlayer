# -*- coding: utf-8 -*-
"""本地 JSON 持久化：曲库 / 歌单 / 设置。

- 无 Qt 依赖，便于单测（测试传入临时目录路径）；
- 原子写入（tmp + os.replace），避免崩溃写坏数据；
- 数据文件损坏时自动备份并重建，不阻塞启动；
- 音乐库 = 全部 tracks；「最近播放」为虚拟视图，均不落盘 track_ids。
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil

from app import crashlog
from app.metadata import TrackMeta
from app.models import (
    PLAYLIST_FAVORITES,
    PLAYLIST_LIBRARY,
    PLAYLIST_RECENT,
    Playlist,
    Settings,
    Track,
    make_track_id,
    new_playlist_id,
    now_ts,
)

DATA_VERSION = 1


class LibraryStore:
    def __init__(self, path: str | None = None):
        """`path=None` 表示**纯内存** store：`load()` / `save()` 都是空操作。

        注意：写库脚本请显式传 `app.paths.data_file()`，否则会得到一个空的内存
        store，`save()` 静默不落盘（曾因此让一次「删除曲目」变成无效操作）。
        """
        self._path = path
        self.tracks: dict[str, Track] = {}
        self.playlists: list[Playlist] = []
        self.settings = Settings()
        # v2.7.5：加载期被跳过的坏数据摘要。非空说明库里有过损坏，
        # 界面要给用户一次交代 —— 静默丢弃用户数据是不可接受的。
        self.load_skipped: list[str] = []
        # v2.7.5：上次 save 的失败原因（空字符串表示成功）。
        # save() 不再向上抛异常，由这里留痕，界面可据此提示。
        self.save_failed: str = ""
        if path:
            self.load()

    # ---------- 持久化 ----------

    def load(self) -> None:
        if not self._path:          # 内存 store：没有可读的文件
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except Exception:  # noqa: BLE001  数据损坏：备份后重建
            self._backup_broken()
            return
        if not isinstance(data, dict):      # v2.7.5：顶层是数组/字符串等，同样按损坏处理
            self._backup_broken()
            return

        # v2.7.5 修复：逐条隔离加载。
        #
        # 改之前是「一个 try 包住 tracks → playlists → settings 三段」，
        # 于是任意一条曲目数据坏掉（例如老版本缺 path 字段），KeyError 会
        # 直接中断整个循环 —— 后面的曲目、**全部歌单**、**全部设置**都不再
        # 加载，然后被 except 静默吃掉。用户看到的是「歌单和设置自己没了」。
        #
        # 现在的原则：一条坏数据只损失它自己，其余照常救回来，并把跳过的
        # 条目记进 load_skipped，让界面能明确告诉用户。
        skipped: list[str] = []

        raw_tracks = data.get("tracks")
        for tid, td in (raw_tracks.items() if isinstance(raw_tracks, dict) else ()):
            try:
                t = Track.from_dict(td)
            except Exception:  # noqa: BLE001  单条坏数据：跳过，不影响其他
                skipped.append(f"曲目 {tid}")
                continue
            self.tracks[t.id or tid] = t

        raw_playlists = data.get("playlists")
        for pd in (raw_playlists if isinstance(raw_playlists, list) else []):
            try:
                pl = Playlist.from_dict(pd)
            except Exception:  # noqa: BLE001
                name = pd.get("name") if isinstance(pd, dict) else str(pd)
                skipped.append(f"歌单 {name}")
                continue
            # v2.0：保留 system 歌单（「我喜欢」需要持久化）；
            # 历史数据中的虚拟 id（library/recent）本就不落盘，出现则跳过
            if pl.id in (PLAYLIST_LIBRARY, PLAYLIST_RECENT):
                continue
            self.playlists.append(pl)

        try:
            self.settings = Settings.from_dict(data.get("settings") or {})
        except Exception:  # noqa: BLE001  设置整块救不回来：回默认，但别拖累上面
            self.settings = Settings()
            skipped.append("设置")

        if skipped:
            self._backup_broken()
            self.load_skipped = skipped
            # 静默丢用户数据是不可接受的：至少要在日志里留下「丢了什么」，
            # 否则用户报「歌单没了」时无从查起。
            with contextlib.suppress(Exception):
                head = ", ".join(skipped[:20])
                more = f" 等 {len(skipped)} 条" if len(skipped) > 20 else ""
                crashlog.log_message(f"加载时跳过损坏记录: {head}{more}")

    def _backup_broken(self) -> None:
        """把损坏的数据文件原样留一份，方便事后排查。备份失败不影响启动。"""
        if not self._path:
            return
        with contextlib.suppress(Exception):
            shutil.copyfile(self._path, self._path + ".bak")

    def save(self) -> None:
        if not self._path:
            return
        data = {
            "version": DATA_VERSION,
            "tracks": {tid: t.to_dict() for tid, t in self.tracks.items()},
            "playlists": [pl.to_dict() for pl in self.playlists],
            "settings": self.settings.to_dict(),
        }
        tmp = self._path + ".tmp"
        # v2.7.5 修复：写盘失败不再向上抛。
        # 磁盘满 / 无写权限 / 文件被占用时，原来的 OSError 会穿透到调用它的
        # Qt 槽里；windowed 打包后没有 stderr，异常既看不见也拦不住，用户只会
        # 觉得「点了没反应」。现在就地记账 + 落日志，由界面决定怎么提示。
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._path)), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path)
        except (OSError, TypeError, ValueError) as exc:
            self.save_failed = f"{type(exc).__name__}: {exc}"
            with contextlib.suppress(OSError):
                os.remove(tmp)
            with contextlib.suppress(Exception):
                crashlog.log_message(f"保存数据失败（{self._path}）: {self.save_failed}")
            return
        self.save_failed = ""

    # ---------- 曲库 ----------

    def add_or_update(self, meta: TrackMeta, path: str) -> Track:
        """新增或刷新一首歌（保留播放统计与手动绑定的歌词）。"""
        tid = make_track_id(path)
        existing = self.tracks.get(tid)
        if existing is not None:
            existing.title = meta.title
            existing.artist = meta.artist
            existing.album = meta.album
            if meta.duration_ms:
                existing.duration_ms = meta.duration_ms
            existing.fmt = meta.fmt
            existing.broken = False
            return existing
        track = Track(
            id=tid,
            path=path,
            title=meta.title,
            artist=meta.artist,
            album=meta.album,
            duration_ms=meta.duration_ms,
            fmt=meta.fmt,
            added_at=now_ts(),
        )
        self.tracks[tid] = track
        return track

    def remove_track(self, tid: str) -> None:
        self.tracks.pop(tid, None)
        for pl in self.playlists:
            if tid in pl.track_ids:
                pl.track_ids = [x for x in pl.track_ids if x != tid]

    def get_track(self, tid: str) -> Track | None:
        return self.tracks.get(tid)

    def all_tracks(self) -> list[Track]:
        return list(self.tracks.values())

    def set_broken(self, tid: str, broken: bool = True) -> None:
        t = self.tracks.get(tid)
        if t is not None:
            t.broken = broken

    def touch_played(self, tid: str) -> None:
        t = self.tracks.get(tid)
        if t is None:
            return
        # 秒级时间戳在同一秒内会并列，导致「最近播放」顺序错乱；
        # 这里保证时间戳单调递增（至少比现有最大值大 1）。
        marker = max([x.last_played_at for x in self.tracks.values()] + [0])
        t.last_played_at = max(now_ts(), marker + 1)
        t.play_count += 1

    def recent_tracks(self, limit: int = 50) -> list[Track]:
        played = [t for t in self.tracks.values() if t.last_played_at > 0]
        played.sort(key=lambda t: t.last_played_at, reverse=True)
        return played[:limit]

    # ---------- 歌单 ----------

    def user_playlists(self) -> list[Playlist]:
        return [pl for pl in self.playlists if not pl.system]

    def create_playlist(self, name: str) -> Playlist:
        name = (name or "").strip() or "未命名歌单"
        pl = Playlist(id=new_playlist_id(), name=name, created_at=now_ts())
        self.playlists.append(pl)
        return pl

    def rename_playlist(self, pid: str, name: str) -> bool:
        pl = self.get_playlist(pid)
        if pl is None or pl.system:
            return False
        name = (name or "").strip()
        if name:
            pl.name = name
        return True

    def delete_playlist(self, pid: str) -> bool:
        pl = self.get_playlist(pid)
        if pl is None or pl.system:
            return False
        self.playlists = [p for p in self.playlists if p.id != pid]
        return True

    def get_playlist(self, pid: str) -> Playlist | None:
        for pl in self.playlists:
            if pl.id == pid:
                return pl
        return None

    def add_to_playlist(self, pid: str, tids: list[str]) -> int:
        pl = self.get_playlist(pid)
        if pl is None:
            return 0
        added = 0
        for tid in tids:
            if tid in self.tracks and tid not in pl.track_ids:
                pl.track_ids.append(tid)
                added += 1
        return added

    def remove_from_playlist(self, pid: str, tid: str) -> None:
        pl = self.get_playlist(pid)
        if pl is not None and tid in pl.track_ids:
            pl.track_ids = [x for x in pl.track_ids if x != tid]

    def move_in_playlist(self, pid: str, tid: str, new_index: int) -> bool:
        pl = self.get_playlist(pid)
        if pl is None or tid not in pl.track_ids:
            return False
        pl.track_ids = [x for x in pl.track_ids if x != tid]
        new_index = max(0, min(new_index, len(pl.track_ids)))
        pl.track_ids.insert(new_index, tid)
        return True

    def playlist_tracks(self, pid: str) -> list[Track]:
        pl = self.get_playlist(pid)
        if pl is None:
            return []
        return [self.tracks[tid] for tid in pl.track_ids if tid in self.tracks]

    # ---------- 我喜欢（v2.0） ----------

    def _ensure_favorites(self) -> Playlist:
        """favorites 系统歌单懒创建：首次收藏时落盘。"""
        pl = self.get_playlist(PLAYLIST_FAVORITES)
        if pl is None:
            pl = Playlist(id=PLAYLIST_FAVORITES, name="我喜欢", created_at=now_ts(), system=True)
            self.playlists.append(pl)
        return pl

    def is_favorite(self, tid: str) -> bool:
        pl = self.get_playlist(PLAYLIST_FAVORITES)
        return pl is not None and tid in pl.track_ids

    def toggle_favorite(self, tid: str) -> bool:
        """切换收藏状态；返回 True=已收藏，False=已取消。tid 不存在时返回当前状态（取消语义为 False）。"""
        pl = self._ensure_favorites()
        if tid in pl.track_ids:
            pl.track_ids = [x for x in pl.track_ids if x != tid]
            return False
        if tid in self.tracks:
            pl.track_ids.append(tid)
            return True
        return False

    def favorite_tracks(self) -> list[Track]:
        return self.playlist_tracks(PLAYLIST_FAVORITES)

    def favorite_count(self) -> int:
        pl = self.get_playlist(PLAYLIST_FAVORITES)
        return len(pl.track_ids) if pl is not None else 0

    # ---------- 设置 ----------

    def set_setting(self, key: str, value) -> None:
        if hasattr(self.settings, key):
            setattr(self.settings, key, value)

    # ---------- 视图辅助 ----------

    def view_tracks(self, view_id: str) -> list[Track]:
        """视图 id -> 曲目列表。library/recent/favorites 为虚拟视图。"""
        if view_id == PLAYLIST_LIBRARY:
            return self.all_tracks()
        if view_id == PLAYLIST_RECENT:
            return self.recent_tracks()
        if view_id == PLAYLIST_FAVORITES:
            return self.favorite_tracks()
        return self.playlist_tracks(view_id)

    def set_view_order(self, view_id: str, ids: list[str]) -> bool:
        """按给定顺序重排一个视图（v3.2.0 拖拽排序落盘）。

        歌单 → 直接改 `Playlist.track_ids`（和 `move_in_playlist` 落到同一处，
        两条路径不会各存一份互相打架）；音乐库 / 我喜欢 → 存
        `settings.view_orders`。返回 False 表示这个视图不支持自定义顺序
        （例如「最近播放」，它按播放时间动态排，存下来的顺序立刻会被重算打乱）。

        防御性过滤：只接受曲库里真有的 id，其余的丢掉 —— 拖拽中途删歌、或外部的
        手改 JSON 都可能带来幽灵 id。
        """
        valid = [tid for tid in ids if tid in self.tracks]
        if view_id in (PLAYLIST_LIBRARY, PLAYLIST_FAVORITES):
            self.settings.view_orders[view_id] = valid
            return True
        pl = self.get_playlist(view_id)
        if pl is None or view_id == PLAYLIST_RECENT:
            return False
        kept = [tid for tid in valid if tid in pl.track_ids]
        rest = [tid for tid in pl.track_ids if tid not in kept]
        # rest 兜住「没出现在显示列表里」的歌单条目，绝不能因为一次拖拽把它们弄丢
        pl.track_ids = kept + rest
        return True

    def view_name(self, view_id: str) -> str:
        if view_id == PLAYLIST_LIBRARY:
            return "音乐库"
        if view_id == PLAYLIST_RECENT:
            return "最近播放"
        if view_id == PLAYLIST_FAVORITES:
            return "我喜欢"
        pl = self.get_playlist(view_id)
        return pl.name if pl else "未知视图"
