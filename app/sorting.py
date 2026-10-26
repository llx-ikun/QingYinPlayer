# -*- coding: utf-8 -*-
"""列表排序：预设定义 + 排序执行（纯逻辑，不依赖 Qt，可脱离 UI 单测）。

v2.1.4 把排序从「只有维度」升级为「维度 + 方向」的预设：
下拉框直接列出「最近导入」「文件大小（大→小）」「时长（短→长）」等条目，
选中即同时确定维度与升降序——单一控件就能清晰表达当前排序方式。

排序 id 形如 `size:desc`；`custom:asc` 表示保持原始顺序（歌单自定义序，可拖拽）。
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.models import Track


@dataclass(frozen=True)
class SortPreset:
    """一条排序预设：维度 + 方向 + 展示文案 + 下拉分组。"""

    id: str
    key: str      # custom/title/artist/album/duration/size/added
    desc: bool    # 是否降序（custom 无方向，固定 False）
    label: str
    group: str    # 同组连续排列，组与组之间在下拉框里插分隔符

    @property
    def is_custom(self) -> bool:
        """是否「自定义顺序」（保持原始顺序，歌单可拖拽）。"""
        return self.key == "custom"


SORT_PRESETS: tuple[SortPreset, ...] = (
    SortPreset("custom:asc", "custom", False, "自定义顺序", "basic"),
    SortPreset("added:desc", "added", True, "最近导入", "time"),
    SortPreset("added:asc", "added", False, "导入时间（早→晚）", "time"),
    SortPreset("size:desc", "size", True, "文件大小（大→小）", "attr"),
    SortPreset("size:asc", "size", False, "文件大小（小→大）", "attr"),
    SortPreset("duration:desc", "duration", True, "时长（长→短）", "attr"),
    SortPreset("duration:asc", "duration", False, "时长（短→长）", "attr"),
    SortPreset("title:asc", "title", False, "标题（A→Z）", "text"),
    SortPreset("title:desc", "title", True, "标题（Z→A）", "text"),
    SortPreset("artist:asc", "artist", False, "艺人（A→Z）", "text"),
    SortPreset("artist:desc", "artist", True, "艺人（Z→A）", "text"),
    SortPreset("album:asc", "album", False, "专辑（A→Z）", "text"),
    SortPreset("album:desc", "album", True, "专辑（Z→A）", "text"),
)

# 资料库/我喜欢/最近添加 的默认排序；歌单默认保持自定义序（可拖拽）
DEFAULT_SORT = "added:desc"
DEFAULT_PLAYLIST_SORT = "custom:asc"

_BY_ID: dict[str, SortPreset] = {p.id: p for p in SORT_PRESETS}

# 兼容 v2.1.3 及更早的纯维度 key（"added"/"title"/…）——旧代码或旧设置传入时不至于失效
_LEGACY: dict[str, str] = {p.key: p.id for p in SORT_PRESETS if not p.desc}
_LEGACY["added"] = DEFAULT_SORT          # 旧语义「添加时间」= 最新在前
_LEGACY["custom"] = DEFAULT_PLAYLIST_SORT

_KEY_FUNCS: dict[str, Callable[[Track], object]] = {
    "title": lambda t: t.display_title.casefold(),
    "artist": lambda t: t.display_artist.casefold(),
    "album": lambda t: t.display_album.casefold(),
    "duration": lambda t: t.duration_ms,
    "added": lambda t: t.added_at,
}


def default_sort_for(is_playlist: bool) -> str:
    """视图默认排序：歌单用自定义序，其余按最近导入。"""
    return DEFAULT_PLAYLIST_SORT if is_playlist else DEFAULT_SORT


def preset_by_id(sort_id: str) -> SortPreset:
    """按 id 取预设；未知/旧式 key 归一化到默认预设，绝不抛异常。"""
    sid = _LEGACY.get(sort_id, sort_id)
    return _BY_ID.get(sid, _BY_ID[DEFAULT_SORT])


def sort_tracks(tracks: Sequence[Track], sort_id: str,
                size_getter: Callable[[Track], int] | None = None) -> list[Track]:
    """按预设排序；`custom` 原样返回（保持歌单自定义顺序）。

    size_getter: callable(track) -> 字节数，仅 size 维度用到。
    """
    items = list(tracks)
    preset = preset_by_id(sort_id)
    if preset.is_custom:
        return items
    if preset.key == "size":
        return _sort_by_size(items, preset.desc, size_getter)
    return sorted(items, key=_KEY_FUNCS[preset.key], reverse=preset.desc)


def _sort_by_size(items: list[Track], desc: bool,
                  size_getter: Callable[[Track], int] | None) -> list[Track]:
    """按文件大小排序；大小未知（文件丢失/读不到）的条目固定排在最后。"""
    getter = size_getter or (lambda _t: 0)
    known: list[Track] = []
    unknown: list[Track] = []
    for track in items:
        (known if getter(track) > 0 else unknown).append(track)
    known.sort(key=getter, reverse=desc)
    return known + unknown
