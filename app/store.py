# -*- coding: utf-8 -*-
"""本地 JSON 持久化：曲库 / 歌单 / 设置。

- 无 Qt 依赖，便于单测（测试传入临时目录路径）；
- 原子写入（tmp + os.replace），避免崩溃写坏数据；
- 数据文件损坏时自动备份并重建，不阻塞启动；
- 资料库 = 全部 tracks；「最近播放」为虚拟视图，均不落盘 track_ids。
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil

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
        self._path = path
        self.tracks: dict[str, Track] = {}
        self.playlists: list[Playlist] = []
        self.settings = Settings()
        if path:
            self.load()

    # ---------- 持久化 ----------

    def load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except Exception:  # noqa: BLE001  数据损坏：备份后重建
            with contextlib.suppress(Exception):
                shutil.copyfile(self._path, self._path + ".bak")
            return
        try:
            for tid, td in (data.get("tracks") or {}).items():
                t = Track.from_dict(td)
                self.tracks[t.id or tid] = t
            for pd in data.get("playlists") or []:
                pl = Playlist.from_dict(pd)
                # v2.0：保留 system 歌单（「我喜欢」需要持久化）；
                # 历史数据中的虚拟 id（library/recent）本就不落盘，出现则跳过
                if pl.id in (PLAYLIST_LIBRARY, PLAYLIST_RECENT):
                    continue
                self.playlists.append(pl)
            self.settings = Settings.from_dict(data.get("settings") or {})
        except Exception:  # noqa: BLE001
            pass

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
        os.makedirs(os.path.dirname(os.path.abspath(self._path)), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self._path)

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

    def view_name(self, view_id: str) -> str:
        if view_id == PLAYLIST_LIBRARY:
            return "资料库"
        if view_id == PLAYLIST_RECENT:
            return "最近播放"
        if view_id == PLAYLIST_FAVORITES:
            return "我喜欢"
        pl = self.get_playlist(view_id)
        return pl.name if pl else "未知视图"
