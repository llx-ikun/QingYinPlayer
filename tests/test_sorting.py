# -*- coding: utf-8 -*-
"""列表排序预设与排序执行单测（纯逻辑，不依赖 Qt，可脱离 UI 运行）。

覆盖 v2.1.4 排序改造的验收点：
- 预设覆盖「大小 / 时长 / 导入时间」三种维度，并有独立的「最近导入」条目；
- 每个维度都有升序与降序两条预设，选中即确定方向；
- 旧式纯维度 key（"added"/"title"…）仍可用（归一化到默认预设）；
- 大小未知（文件丢失/读不到）的条目在升降序下都排在最后。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import Track  # noqa: E402
from app.sorting import (  # noqa: E402
    DEFAULT_PLAYLIST_SORT,
    DEFAULT_SORT,
    SORT_PRESETS,
    apply_manual_order,
    default_sort_for,
    preset_by_id,
    sort_tracks,
)


def mk(tid: str, *, title: str = "", artist: str = "", album: str = "",
       duration: int = 0, added: int = 0) -> Track:
    return Track(id=tid, path=f"C:/fake/{tid}.mp3", title=title or tid, artist=artist,
                 album=album, duration_ms=duration, added_at=added, fmt="mp3")


class TestSortPresets(unittest.TestCase):
    def test_ids_unique(self):
        ids = [p.id for p in SORT_PRESETS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_id_encodes_dimension_and_direction(self):
        for p in SORT_PRESETS:
            self.assertEqual(p.id, f"{p.key}:{'desc' if p.desc else 'asc'}", p.id)

    def test_labels_non_empty_and_unique(self):
        labels = [p.label for p in SORT_PRESETS]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertTrue(all(lbl.strip() for lbl in labels))

    def test_required_dimensions_covered(self):
        keys = {p.key for p in SORT_PRESETS}
        for key in ("size", "duration", "added", "custom"):
            self.assertIn(key, keys)

    def test_each_dimension_has_both_directions(self):
        for key in ("size", "duration", "added", "title", "artist", "album"):
            dirs = {p.desc for p in SORT_PRESETS if p.key == key}
            self.assertEqual(dirs, {True, False}, f"{key} 缺少升序或降序预设")

    def test_recent_import_entry_exists(self):
        """「最近导入」是独立可选项，语义 = 导入时间降序。"""
        recent = [p for p in SORT_PRESETS if p.label == "最近导入"]
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].key, "added")
        self.assertTrue(recent[0].desc)
        self.assertEqual(recent[0].id, DEFAULT_SORT)

    def test_default_per_view(self):
        self.assertEqual(default_sort_for(True), DEFAULT_PLAYLIST_SORT)
        self.assertEqual(default_sort_for(False), DEFAULT_SORT)
        self.assertTrue(preset_by_id(DEFAULT_PLAYLIST_SORT).is_custom)

    def test_legacy_keys_normalized(self):
        # 旧版的纯维度 key 不能失效
        self.assertEqual(preset_by_id("added").id, "added:desc")
        self.assertEqual(preset_by_id("title").id, "title:asc")
        self.assertEqual(preset_by_id("custom").id, DEFAULT_PLAYLIST_SORT)
        # 未知 id 回落到默认，不抛异常
        self.assertEqual(preset_by_id("no-such-sort").id, DEFAULT_SORT)


class TestSortTracks(unittest.TestCase):
    def setUp(self):
        self.tracks = [
            mk("a", title="banana", artist="Zed", album="Two", duration=300, added=100),
            mk("b", title="Apple", artist="amy", album="One", duration=100, added=300),
            mk("c", title="cherry", artist="Bob", album="Three", duration=200, added=200),
        ]

    def _ids(self, tracks):
        return [t.id for t in tracks]

    def test_custom_keeps_input_order(self):
        self.assertEqual(self._ids(sort_tracks(self.tracks, DEFAULT_PLAYLIST_SORT)),
                         ["a", "b", "c"])

    def test_duration_both_directions(self):
        self.assertEqual(self._ids(sort_tracks(self.tracks, "duration:asc")), ["b", "c", "a"])
        self.assertEqual(self._ids(sort_tracks(self.tracks, "duration:desc")), ["a", "c", "b"])

    def test_added_both_directions(self):
        self.assertEqual(self._ids(sort_tracks(self.tracks, "added:desc")), ["b", "c", "a"])
        self.assertEqual(self._ids(sort_tracks(self.tracks, "added:asc")), ["a", "c", "b"])

    def test_text_case_insensitive(self):
        asc = self._ids(sort_tracks(self.tracks, "title:asc"))
        self.assertEqual(asc, ["b", "a", "c"])   # Apple < banana < cherry
        self.assertEqual(self._ids(sort_tracks(self.tracks, "title:desc")), ["c", "a", "b"])

    def test_artist_and_album(self):
        self.assertEqual(self._ids(sort_tracks(self.tracks, "artist:asc")), ["b", "c", "a"])
        self.assertEqual(self._ids(sort_tracks(self.tracks, "album:asc")), ["b", "c", "a"])

    def test_size_both_directions(self):
        sizes = {"a": 500, "b": 100, "c": 900}
        get = lambda t: sizes[t.id]  # noqa: E731 - 测试内联最直观
        self.assertEqual(self._ids(sort_tracks(self.tracks, "size:desc", get)), ["c", "a", "b"])
        self.assertEqual(self._ids(sort_tracks(self.tracks, "size:asc", get)), ["b", "a", "c"])

    def test_size_unknown_always_last(self):
        """文件丢失/读不到（大小 0）的条目在升序和降序下都排最后。"""
        sizes = {"a": 500, "b": 0, "c": 900}
        get = lambda t: sizes[t.id]  # noqa: E731
        self.assertEqual(self._ids(sort_tracks(self.tracks, "size:desc", get)), ["c", "a", "b"])
        self.assertEqual(self._ids(sort_tracks(self.tracks, "size:asc", get)), ["a", "c", "b"])

    def test_size_without_getter_keeps_order(self):
        self.assertEqual(self._ids(sort_tracks(self.tracks, "size:desc")), ["a", "b", "c"])

    def test_does_not_mutate_input(self):
        original = list(self.tracks)
        sort_tracks(self.tracks, "duration:desc")
        self.assertEqual(self.tracks, original)


class TestManualOrder(unittest.TestCase):
    """v3.2.0 拖拽排序：按记录下来的 id 顺序重排「自定义顺序」。"""

    def setUp(self):
        self.tracks = [mk("a"), mk("b"), mk("c"), mk("d")]

    def _ids(self, items):
        return [t.id for t in items]

    def test_empty_order_keeps_input(self):
        """没拖过的视图（view_orders 里没有这条键）必须原样返回。"""
        self.assertEqual(self._ids(apply_manual_order(self.tracks, [])),
                         ["a", "b", "c", "d"])

    def test_follows_recorded_order(self):
        self.assertEqual(self._ids(apply_manual_order(self.tracks, ["d", "b", "a", "c"])),
                         ["d", "b", "a", "c"])

    def test_new_tracks_go_last_in_original_relative_order(self):
        """顺序表里没有的曲子（新导入 / 新收藏）接到末尾，且保持原相对次序。

        这条是"新增一首歌就毁掉全部手排顺序"的防线。
        """
        self.assertEqual(self._ids(apply_manual_order(self.tracks, ["c", "a"])),
                         ["c", "a", "b", "d"])

    def test_order_ids_not_in_tracks_are_ignored(self):
        """库里已删掉的歌留在顺序表里（幽灵 id）不该让排序抛异常或错位。"""
        self.assertEqual(self._ids(apply_manual_order(self.tracks, ["zz", "b", "zz2", "a"])),
                         ["b", "a", "c", "d"])

    def test_result_independent_of_input_order(self):
        """同一份记录顺序，输入怎么打乱，输出都一致 —— 排序稳定性的定义。"""
        order = ["d", "a", "c", "b"]
        first = self._ids(apply_manual_order(self.tracks, order))
        second = self._ids(apply_manual_order(list(reversed(self.tracks)), order))
        self.assertEqual(first, second)

    def test_does_not_mutate_input(self):
        original = list(self.tracks)
        apply_manual_order(self.tracks, ["d", "c", "b", "a"])
        self.assertEqual(self.tracks, original)


if __name__ == "__main__":
    unittest.main()
