# -*- coding: utf-8 -*-
"""app.store 单元测试（临时目录 round-trip）。"""
import json
import os
import shutil
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
        self.assertEqual(s.view_name(PLAYLIST_LIBRARY), "音乐库")
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
        self.assertEqual(s2.settings.theme, "light")
        self.assertEqual(s2.settings.nickname, "音乐爱好者")

    def test_appearance_settings_roundtrip(self):
        """v2.2 外观：强调色 + 字号缩放要能存能读。"""
        s = self._store()
        s.set_setting("accent_color", "#ff7a45")
        s.set_setting("font_scale", 1.15)
        s.save()
        s2 = LibraryStore(self.db)
        self.assertEqual(s2.settings.accent_color, "#ff7a45")
        self.assertAlmostEqual(s2.settings.font_scale, 1.15)

    def test_legacy_data_gets_default_appearance(self):
        """老 data.json 没有外观字段：跟随主题默认（空强调色 + 100% 字号）。"""
        s = self._store()
        s.save()
        s2 = LibraryStore(self.db)
        self.assertEqual(s2.settings.accent_color, "")
        self.assertAlmostEqual(s2.settings.font_scale, 1.0)

    def test_bad_font_scale_in_json_falls_back(self):
        """脏数据（字符串/None）不能让整个设置炸掉。"""
        import json

        s = self._store()
        s.save()
        with open(self.db, encoding="utf-8") as f:
            data = json.load(f)
        data["settings"]["font_scale"] = "很大"
        with open(self.db, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        self.assertAlmostEqual(LibraryStore(self.db).settings.font_scale, 1.0)

    def test_lyrics_effect_roundtrip(self):
        """v2.6.4 歌词动效要能存能读，默认 none。"""
        s = self._store()
        self.assertEqual(s.settings.lyrics_effect, "none")
        s.set_setting("lyrics_effect", "karaoke")
        s.save()
        self.assertEqual(LibraryStore(self.db).settings.lyrics_effect, "karaoke")

    def test_bad_lyrics_effect_in_json_falls_back(self):
        import json

        s = self._store()
        s.save()
        with open(self.db, encoding="utf-8") as f:
            data = json.load(f)
        data["settings"]["lyrics_effect"] = "flashy"
        with open(self.db, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        self.assertEqual(LibraryStore(self.db).settings.lyrics_effect, "none")


class TestDamagedData(unittest.TestCase):
    """v2.7.5：一条坏数据只该损失它自己。

    改动前 store.load() 用一个 try 包住 tracks → playlists → settings 三段，
    任意一条曲目数据坏掉就中断整个流程 —— 后面的歌、**全部歌单**、
    **全部设置**都不再加载，然后被 except 静默吃掉。用户看到的是
    「歌单和设置自己没了」。这组用例锁死修好之后的行为。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_damaged_")
        self.db = os.path.join(self.tmp, "data.json")
        # 隔离数据根：加载期会写诊断日志到 paths.current_root()/logs，
        # 不隔离就会污染用户真实目录（crashlog 每次调用都重新解析路径）。
        self._old_env = os.environ.get("QY_DATA_DIR")
        os.environ["QY_DATA_DIR"] = self.tmp

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("QY_DATA_DIR", None)
        else:
            os.environ["QY_DATA_DIR"] = self._old_env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, data) -> None:
        with open(self.db, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def test_one_broken_track_keeps_others_and_playlists(self):
        """缺 path 的曲目只丢它自己，其余歌 + 歌单 + 设置全部存活。"""
        self._write({
            "version": 1,
            "tracks": {
                "a": {"id": "a", "path": "C:/m/a.mp3", "title": "歌A"},
                "b": {"id": "b", "title": "缺 path 的坏数据"},
                "c": {"id": "c", "path": "C:/m/c.mp3", "title": "歌C"},
            },
            "playlists": [
                {"id": "pl1", "name": "跑步歌单", "track_ids": ["a", "c"], "created_at": 1},
            ],
            "settings": {"volume": 0.25, "theme": "columbina", "nickname": "阿坤"},
        })
        s = LibraryStore(self.db)
        self.assertEqual(sorted(t.title for t in s.all_tracks()), ["歌A", "歌C"])
        self.assertEqual(len(s.playlists), 1)
        self.assertAlmostEqual(s.settings.volume, 0.25)
        self.assertEqual(s.settings.nickname, "阿坤")
        self.assertEqual(len(s.load_skipped), 1)

    def test_broken_playlist_keeps_others(self):
        """歌单里的坏条目只跳过它自己。"""
        self._write({
            "version": 1,
            "tracks": {"a": {"id": "a", "path": "C:/m/a.mp3", "title": "歌A"}},
            "playlists": [
                123,                                               # 根本不是字典
                {"id": "pl2", "name": "好歌单", "track_ids": ["a"], "created_at": 1},
            ],
            "settings": {"volume": 0.3},
        })
        s = LibraryStore(self.db)
        self.assertEqual([pl.name for pl in s.playlists], ["好歌单"])
        self.assertEqual(len(s.load_skipped), 1)
        self.assertIn("歌单", s.load_skipped[0])

    def test_null_volume_keeps_other_settings(self):
        """volume 为 null 只让音量回默认，不能带走主题/昵称/强调色。"""
        self._write({
            "version": 1,
            "tracks": {},
            "playlists": [],
            "settings": {
                "volume": None,
                "theme": "columbina",
                "nickname": "阿坤",
                "accent_color": "#ff7a45",
                "font_scale": 1.15,
            },
        })
        s = LibraryStore(self.db)
        self.assertAlmostEqual(s.settings.volume, 0.7)          # 回默认
        self.assertEqual(s.settings.theme, "columbina")         # 其余保留
        self.assertEqual(s.settings.nickname, "阿坤")
        self.assertEqual(s.settings.accent_color, "#ff7a45")
        self.assertAlmostEqual(s.settings.font_scale, 1.15)
        self.assertEqual(s.load_skipped, [])                    # 能救回来就不算损坏

    def test_out_of_range_values_are_clamped(self):
        """超范围数值夹到合法区间，非法枚举回默认，全程不抛异常。"""
        self._write({
            "version": 1,
            "tracks": {},
            "playlists": [],
            "settings": {
                "volume": 99,                    # > 1
                "last_position_ms": -5,          # < 0
                "play_mode": "乱来",              # 不在 PLAY_MODES
                "lyrics_effect": "flashy",       # 不在 LYRICS_EFFECTS
                "font_scale": "很大",
                "nickname": ["不是字符串"],
                "accent_color": {"hex": "#fff"},
            },
        })
        s = LibraryStore(self.db)
        self.assertAlmostEqual(s.settings.volume, 1.0)
        self.assertEqual(s.settings.last_position_ms, 0)
        self.assertEqual(s.settings.play_mode, "loop")
        self.assertEqual(s.settings.lyrics_effect, "none")
        self.assertAlmostEqual(s.settings.font_scale, 1.0)
        self.assertEqual(s.settings.nickname, "音乐爱好者")
        self.assertEqual(s.settings.accent_color, "")

    def test_non_dict_root_treated_as_corrupt(self):
        """顶层是数组等非法结构：按损坏处理，备份重建，不崩。"""
        with open(self.db, "w", encoding="utf-8") as f:
            f.write("[1, 2, 3]")
        s = LibraryStore(self.db)
        self.assertEqual(s.all_tracks(), [])
        self.assertTrue(os.path.exists(self.db + ".bak"))

    def test_skip_is_logged_to_crash_log(self):
        """跳过了就得留痕：日志里要能查到丢了什么。"""
        self._write({
            "version": 1,
            "tracks": {"b": {"id": "b", "title": "缺 path"}},
            "playlists": [],
            "settings": {},
        })
        LibraryStore(self.db)
        log = os.path.join(self.tmp, "logs", "app.log")
        self.assertTrue(os.path.exists(log), "损坏数据必须写进诊断日志")
        with open(log, encoding="utf-8") as f:
            self.assertIn("跳过损坏记录", f.read())

    def test_save_failure_is_recorded_not_raised(self):
        """写盘失败不许向上抛：异常穿透到 Qt 槽里就再也看不见了。"""
        s = LibraryStore(self.db)
        s.settings.nickname = object()          # 无法 JSON 序列化
        s.save()                                # 不应抛异常
        self.assertTrue(s.save_failed)
        self.assertFalse(os.path.exists(self.db + ".tmp"), "失败后不能留半截临时文件")

    def test_save_success_clears_failure_flag(self):
        s = LibraryStore(self.db)
        s.settings.nickname = object()
        s.save()
        self.assertTrue(s.save_failed)
        s.settings.nickname = "阿坤"
        s.save()
        self.assertEqual(s.save_failed, "")
        self.assertTrue(os.path.exists(self.db))


if __name__ == "__main__":
    unittest.main()
