# -*- coding: utf-8 -*-
"""v2.1 后端单测：视频识别、混合媒体扫描、旧数据兼容、视频元数据兜底。

不涉及 Qt 窗口逻辑（那部分在 tests/test_e2e_video.py）。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.make_fixtures import ensure_fixtures, ensure_video_fixture

MUSIC_DIR = ensure_fixtures()
VIDEO_PATH = ensure_video_fixture()


class TestMediaExtensions(unittest.TestCase):
    def test_video_extensions_defined(self):
        from app.models import MEDIA_EXTENSIONS, VIDEO_EXTENSIONS
        for ext in (".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v"):
            self.assertIn(ext, VIDEO_EXTENSIONS)
            self.assertIn(ext, MEDIA_EXTENSIONS)

    def test_media_extensions_include_audio(self):
        from app.models import AUDIO_EXTENSIONS, MEDIA_EXTENSIONS
        for ext in AUDIO_EXTENSIONS:
            self.assertIn(ext, MEDIA_EXTENSIONS)

    def test_m4a_is_audio_m4v_is_video(self):
        """两个扩展名只差一个字母，必须区分清楚。"""
        from app.models import VIDEO_FORMATS
        self.assertNotIn("m4a", VIDEO_FORMATS)
        self.assertIn("m4v", VIDEO_FORMATS)


class TestTrackIsVideo(unittest.TestCase):
    def _track(self, path, fmt):
        from app.models import Track
        return Track(id="x", path=path, fmt=fmt)

    def test_video_fmt_detected(self):
        for fmt in ("mp4", "MKV", "avi", "webm", "m4v"):
            self.assertTrue(self._track(f"a.{fmt}", fmt.lower()).is_video, fmt)

    def test_audio_fmt_not_video(self):
        for fmt in ("mp3", "flac", "wav", "m4a", "aac", "ogg", "opus", "wma"):
            self.assertFalse(self._track(f"a.{fmt}", fmt).is_video, fmt)

    def test_empty_fmt_falls_back_to_path(self):
        """旧数据可能没有 fmt：按路径扩展名兜底判定。"""
        self.assertTrue(self._track("D:/x/clip.mp4", "").is_video)
        self.assertFalse(self._track("D:/x/song.mp3", "").is_video)

    def test_is_video_is_derived_not_stored(self):
        """is_video 不进 JSON：旧歌单与设置无需迁移。"""
        from app.models import Track
        t = self._track("a.mp4", "mp4")
        self.assertNotIn("is_video", t.to_dict())
        restored = Track.from_dict(t.to_dict())
        self.assertTrue(restored.is_video)


class TestMediaScan(unittest.TestCase):
    def test_collects_audio_and_video(self):
        from app.scanner import collect_media_files
        files = collect_media_files([MUSIC_DIR, os.path.dirname(VIDEO_PATH)])
        exts = {os.path.splitext(f)[1].lower() for f in files}
        self.assertIn(".mp3", exts)
        self.assertIn(".avi", exts)

    def test_video_file_collected(self):
        from app.scanner import collect_media_files
        files = collect_media_files([VIDEO_PATH])
        self.assertEqual(files, [os.path.abspath(VIDEO_PATH)])

    def test_old_alias_still_works(self):
        """v1.0 起的公开入口保留，避免外部脚本失效。"""
        from app.scanner import collect_audio_files, collect_media_files
        self.assertIs(collect_audio_files, collect_media_files)

    def test_non_media_ignored(self):
        from app.scanner import collect_media_files
        tmp = tempfile.mkdtemp(prefix="qy_scan_")
        path = os.path.join(tmp, "note.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("x")
        self.assertEqual(collect_media_files([path]), [])

    def test_uppercase_extension_collected(self):
        """Windows 上扩展名大小写混用常见。"""
        from app.scanner import collect_media_files
        tmp = tempfile.mkdtemp(prefix="qy_scan_")
        path = os.path.join(tmp, "CLIP.MP4")
        with open(path, "wb") as f:
            f.write(b"0")
        self.assertEqual(collect_media_files([path]), [os.path.abspath(path)])


class TestVideoMetadata(unittest.TestCase):
    def test_video_meta_fallback_to_filename(self):
        """mutagen 读不出 AVI 标签时，标题回退为文件名且不报错。"""
        from app.metadata import read_track
        meta = read_track(VIDEO_PATH)
        self.assertIsNotNone(meta)
        self.assertTrue(meta.is_video)
        self.assertEqual(meta.fmt, "avi")
        self.assertEqual(meta.title, os.path.splitext(os.path.basename(VIDEO_PATH))[0])
        self.assertEqual(meta.artist, "")
        self.assertEqual(meta.album, "")

    def test_video_display_fallbacks(self):
        from app.models import Track
        t = Track(id="v", path=VIDEO_PATH, fmt="avi", title="测试短片")
        self.assertEqual(t.display_artist, "本地视频")
        self.assertEqual(t.display_album, "视频文件")

    def test_missing_file_returns_none(self):
        from app.metadata import read_track
        self.assertIsNone(read_track("D:/绝对不存在的文件.xyz"))

    def test_audio_meta_unchanged(self):
        """音频的既有兜底语义不受视频改动影响。"""
        from app.metadata import read_track
        meta = read_track(os.path.join(MUSIC_DIR, "无标签音频.mp3"))
        self.assertIsNotNone(meta)
        self.assertFalse(meta.is_video)
        self.assertEqual(meta.artist, "未知艺人")
        self.assertEqual(meta.album, "未知专辑")


class TestStoreCompatibility(unittest.TestCase):
    def test_old_json_without_new_fields_loads(self):
        """旧 data.json（无任何 v2.1 字段）可无损加载。"""
        import json
        from app.store import LibraryStore
        tmp = tempfile.mkdtemp(prefix="qy_store_")
        path = os.path.join(tmp, "data.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "tracks": {"abc": {"id": "abc", "path": "D:/x/old.mp3",
                                   "title": "老歌", "fmt": "mp3"}},
                "playlists": [],
                "settings": {"volume": 0.5},
            }, f)
        store = LibraryStore(path)
        track = store.get_track("abc")
        self.assertIsNotNone(track)
        self.assertFalse(track.is_video)
        self.assertEqual(store.settings.theme, "dark")
        self.assertEqual(store.settings.nickname, "音乐爱好者")

    def test_video_track_roundtrip(self):
        from app.metadata import read_track
        from app.store import LibraryStore
        tmp = tempfile.mkdtemp(prefix="qy_store_")
        store = LibraryStore(os.path.join(tmp, "data.json"))
        track = store.add_or_update(read_track(VIDEO_PATH), VIDEO_PATH)
        self.assertTrue(track.is_video)
        store.save()
        reloaded = LibraryStore(os.path.join(tmp, "data.json"))
        self.assertTrue(reloaded.get_track(track.id).is_video)


class TestBadge(unittest.TestCase):
    def test_video_badge(self):
        from ui.track_list import format_badge
        for fmt in ("mp4", "mkv", "avi", "webm", "m4v"):
            text, tier = format_badge(fmt)
            self.assertEqual(text, "视频", fmt)
            self.assertEqual(tier, "video", fmt)

    def test_audio_badge_unchanged(self):
        from ui.track_list import format_badge
        self.assertEqual(format_badge("flac"), ("无损", "lossless"))
        self.assertEqual(format_badge("mp3"), ("MP3", ""))
        self.assertEqual(format_badge("m4a"), ("AAC", ""))


if __name__ == "__main__":
    unittest.main()
