# -*- coding: utf-8 -*-
"""app.store 单元测试（临时目录 round-trip）。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.metadata import TrackMeta
from app.models import PLAYLIST_FAVORITES, PLAYLIST_LIBRARY, PLAYLIST_RECENT, make_track_id
from app.store import LibraryStore


def _meta(title="测试歌曲", artist="测试艺人", album="测试专辑", dur=2000, fmt="mp3"):
    return TrackMeta(title=title, artist=artist, album=album, duration_ms=dur, fmt=fmt)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_store_")
        self.db = os.path.join(self.tmp, "data.json")
        self.paths = [os.path.join(self.tmp, f"歌曲{i}.mp3") for i in range(3)]

    def _store(self):
        s = LibraryStore(self.db)
        for i, p in enumerate(self.paths):
            s.add_or_update(_meta(title=f"歌曲{i}"), p)
        s.save()
        return s

    def test_add_and_dedupe(self):
        s = self._store()
        self.assertEqual(len(s.all_tracks()), 3)
        # 重复导入同一路径 -> 仍是 3 首，但元数据被刷新
        s.add_or_update(_meta(title="新标题"), self.paths[0])
        self.assertEqual(len(s.all_tracks()), 3)
        self.assertEqual(s.get_track(make_track_id(self.paths[0])).title, "新标题")

    def test_persistence_roundtrip(self):
        self._store()
        s2 = LibraryStore(self.db)
        self.assertEqual(len(s2.all_tracks()), 3)
        self.assertEqual(s2.all_tracks()[0].title, "歌曲0")

    def test_corrupt_file_backed_up(self):
        with open(self.db, "w", encoding="utf-8") as f:
            f.write("{这不是合法JSON")
        s = LibraryStore(self.db)
        self.assertEqual(s.all_tracks(), [])
        self.assertTrue(os.path.exists(self.db + ".bak"))

    def test_playlist_crud(self):
        s = self._store()
        pl = s.create_playlist("跑步歌单")
        tids = [t.id for t in s.all_tracks()]
        self.assertEqual(s.add_to_playlist(pl.id, tids), 3)
        self.assertEqual(len(s.playlist_tracks(pl.id)), 3)
        # 重复添加不叠加
        s.add_to_playlist(pl.id, [tids[0]])
        self.assertEqual(len(s.playlist_tracks(pl.id)), 3)
        # 重命名 / 移动 / 移除
        self.assertTrue(s.rename_playlist(pl.id, "夜跑"))
        self.assertEqual(s.get_playlist(pl.id).name, "夜跑")
        self.assertTrue(s.move_in_playlist(pl.id, tids[2], 0))
        self.assertEqual(s.playlist_tracks(pl.id)[0].id, tids[2])
        s.remove_from_playlist(pl.id, tids[0])
        self.assertEqual(len(s.playlist_tracks(pl.id)), 2)
        self.assertTrue(s.delete_playlist(pl.id))
        self.assertEqual(s.user_playlists(), [])

    def test_remove_track_cleans_playlists(self):
        s = self._store()
        pl = s.create_playlist("歌单")
        tid = s.all_tracks()[0].id
        s.add_to_playlist(pl.id, [tid])
        s.remove_track(tid)
        self.assertEqual(s.playlist_tracks(pl.id), [])

    def test_recent_tracks(self):
        s = self._store()
        tracks = s.all_tracks()
        s.touch_played(tracks[1].id)
        s.touch_played(tracks[2].id)
        s.touch_played(tracks[0].id)
        recent = s.recent_tracks()
        self.assertEqual([t.id for t in recent], [tracks[0].id, tracks[2].id, tracks[1].id])
        self.assertEqual(recent[0].play_count, 1)

    def test_views(self):
        s = self._store()
        self.assertEqual(len(s.view_tracks(PLAYLIST_LIBRARY)), 3)
        self.assertEqual(s.view_name(PLAYLIST_LIBRARY), "资料库")
        self.assertEqual(s.view_name(PLAYLIST_RECENT), "最近播放")
        pl = s.create_playlist("我的歌单")
        self.assertEqual(s.view_name(pl.id), "我的歌单")
        s.touch_played(s.all_tracks()[0].id)
        self.assertEqual(len(s.view_tracks(PLAYLIST_RECENT)), 1)

    def test_settings_roundtrip(self):
        s = self._store()
        s.set_setting("volume", 0.3)
        s.set_setting("play_mode", "shuffle")
        s.save()
        s2 = LibraryStore(self.db)
        self.assertAlmostEqual(s2.settings.volume, 0.3)
        self.assertEqual(s2.settings.play_mode, "shuffle")

    def test_set_setting_rejects_unknown_key(self):
        s = self._store()
        s.set_setting("不存在的字段", 123)  # 不抛异常即可
        self.assertFalse(hasattr(s.settings, "不存在的字段"))

    # ---------- v2.0：我喜欢 ----------

    def test_favorites_toggle_and_count(self):
        s = self._store()
        tids = [t.id for t in s.all_tracks()]
        # 未收藏时不落盘 favorites 歌单
        self.assertFalse(s.is_favorite(tids[0]))
        self.assertEqual(s.favorite_count(), 0)
        self.assertTrue(s.toggle_favorite(tids[0]))
        self.assertTrue(s.is_favorite(tids[0]))
        self.assertEqual(s.favorite_count(), 1)
        self.assertTrue(s.toggle_favorite(tids[2]))
        self.assertEqual(s.favorite_count(), 2)
        # 再点一次 = 取消
        self.assertFalse(s.toggle_favorite(tids[0]))
        self.assertFalse(s.is_favorite(tids[0]))
        self.assertEqual(s.favorite_count(), 1)
        # 收藏不存在的 tid：不入库
        self.assertFalse(s.toggle_favorite("不存在的id"))
        self.assertEqual(s.favorite_count(), 1)

    def test_favorites_persistence_and_view(self):
        s = self._store()
        tid = s.all_tracks()[0].id
        s.toggle_favorite(tid)
        s.save()
        s2 = LibraryStore(self.db)
        self.assertTrue(s2.is_favorite(tid))
        self.assertEqual(len(s2.favorite_tracks()), 1)
        self.assertEqual(s2.view_name(PLAYLIST_FAVORITES), "我喜欢")
        self.assertEqual([t.id for t in s2.view_tracks(PLAYLIST_FAVORITES)], [tid])
        # favorites 是系统歌单：不出现在用户歌单里，不可删改名
        self.assertEqual(s2.user_playlists(), [])
        self.assertFalse(s2.rename_playlist(PLAYLIST_FAVORITES, "x"))
        self.assertFalse(s2.delete_playlist(PLAYLIST_FAVORITES))

    def test_remove_track_cleans_favorites(self):
        s = self._store()
        tids = [t.id for t in s.all_tracks()]
        s.toggle_favorite(tids[0])
        s.toggle_favorite(tids[1])
        s.remove_track(tids[0])
        self.assertEqual([t.id for t in s.favorite_tracks()], [tids[1]])

    def test_settings_theme_nickname_roundtrip(self):
        s = self._store()
        s.set_setting("theme", "light")
        s.set_setting("nickname", "原神启动")
        s.save()
        s2 = LibraryStore(self.db)
        self.assertEqual(s2.settings.theme, "light")
        self.assertEqual(s2.settings.nickname, "原神启动")

    def test_legacy_data_without_new_settings(self):
        """旧 data.json 无 theme/nickname/favorites：无损升级。"""
        self._store()
        s2 = LibraryStore(self.db)
        self.assertEqual(s2.settings.theme, "dark")
        self.assertEqual(s2.settings.nickname, "音乐爱好者")


if __name__ == "__main__":
    unittest.main()
