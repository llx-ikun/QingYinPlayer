# -*- coding: utf-8 -*-
"""联网歌词匹配（v2.2）：URL 构造 / 脏数据解析 / 选曲打分 / 缓存读写 / 后台线程。

设计要点：所有网络请求都通过 `fetch` 参数注入，本文件**完全不联网**。
选曲规则是「宁可没有，也不能配错」——没有身份信号（歌名或艺人或时长对得上）
的候选一律丢弃，避免给用户塞一首别的歌的歌词。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lyrics_online import (
    LyricsFetchWorker,
    build_search_url,
    cache_path,
    clear_cache,
    fetch_lyrics,
    parse_hits,
    pick_best,
    read_cache,
    write_cache,
)


def setUpModule():
    from PySide6.QtWidgets import QApplication
    global _app
    _app = QApplication.instance() or QApplication(sys.argv[:1])


def _payload(**kwargs):
    """构造一条 LRCLIB 风格的记录，字段名与线上一致（camelCase）。"""
    item = {
        "id": 1,
        "trackName": "晴天",
        "artistName": "周杰伦",
        "albumName": "叶惠美",
        "duration": 269,
        "instrumental": False,
        "plainLyrics": "故事的小黄花",
        "syncedLyrics": "[00:01.00]故事的小黄花",
    }
    item.update(kwargs)
    return item


class TestSearchUrl(unittest.TestCase):
    def test_encodes_title_and_artist(self):
        url = build_search_url("晴天", "周杰伦")
        self.assertTrue(url.startswith("https://lrclib.net/api/search?"))
        self.assertIn("track_name=", url)
        self.assertIn("artist_name=", url)
        # 中文要被百分号编码，不能原样拼进 URL
        self.assertNotIn("晴天", url)
        self.assertIn("%E6%99%B4%E5%A4%A9", url)

    def test_empty_inputs_still_build(self):
        url = build_search_url("", "")
        self.assertIn("track_name=", url)
        self.assertIn("artist_name=", url)


class TestParseHits(unittest.TestCase):
    def test_parses_normal_payload(self):
        hits = parse_hits([_payload()])
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit.track_name, "晴天")
        self.assertEqual(hit.artist_name, "周杰伦")
        self.assertEqual(hit.duration, 269)
        self.assertEqual(hit.text, "[00:01.00]故事的小黄花")

    def test_tolerates_garbage(self):
        """非 list / 非 dict 元素 / 字段缺失都不能抛异常。"""
        self.assertEqual(parse_hits(None), [])
        self.assertEqual(parse_hits({"oops": 1}), [])
        self.assertEqual(parse_hits([None, 3, "x"]), [])
        hits = parse_hits([{}])
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].duration, 0)
        self.assertIsNone(hits[0].text)

    def test_duration_type_error_becomes_zero(self):
        hits = parse_hits([_payload(duration="not-a-number")])
        self.assertEqual(hits[0].duration, 0)

    def test_falls_back_to_plain_when_no_synced(self):
        hits = parse_hits([_payload(syncedLyrics=None)])
        self.assertEqual(hits[0].text, "故事的小黄花")


class TestPickBest(unittest.TestCase):
    def test_picks_exact_match_with_close_duration(self):
        hits = parse_hits([
            _payload(trackName="晴天", artistName="周杰伦", duration=269),
            _payload(trackName="晴天", artistName="别人", duration=200),
        ])
        best = pick_best(hits, "晴天", "周杰伦", 269_000)
        self.assertIsNotNone(best)
        self.assertEqual(best.artist_name, "周杰伦")

    def test_rejects_unrelated_song(self):
        """候选和这首歌毫无关系时必须返回 None——配错歌词比没歌词更糟。"""
        hits = parse_hits([_payload(trackName="稻香", artistName="陈奕迅", duration=100)])
        self.assertIsNone(pick_best(hits, "晴天", "周杰伦", 269_000))

    def test_exact_duration_alone_is_enough(self):
        """歌名艺人都不匹配、但时长完全相同（±3s 内）：仍算同一首。

        现实里同名翻唱/纯音乐版本很多，时长严格一致几乎只可能是同一录音。
        """
        hits = parse_hits([_payload(trackName="别的歌", artistName="别人", duration=269)])
        self.assertIsNotNone(pick_best(hits, "晴天", "周杰伦", 269_000))

    def test_skips_instrumental(self):
        hits = parse_hits([_payload(instrumental=True)])
        self.assertIsNone(pick_best(hits, "晴天", "周杰伦", 269_000))

    def test_skips_hit_without_any_lyrics(self):
        hits = parse_hits([_payload(syncedLyrics=None, plainLyrics=None)])
        self.assertIsNone(pick_best(hits, "晴天", "周杰伦", 269_000))

    def test_prefers_synced_over_plain_on_tie(self):
        hits = parse_hits([
            _payload(syncedLyrics=None),
            _payload(syncedLyrics="[00:01.00]故事的小黄花"),
        ])
        best = pick_best(hits, "晴天", "周杰伦", 269_000)
        self.assertIsNotNone(best)
        self.assertTrue(best.synced)

    def test_normalizes_case_and_spaces(self):
        """英文歌名大小写/空格差异不应影响匹配。"""
        hits = parse_hits([_payload(trackName="Let It Be", artistName="The Beatles")])
        best = pick_best(hits, "let it be", "beatles", 0)
        self.assertIsNotNone(best)
        self.assertEqual(best.track_name, "Let It Be")


class TestFetchLyrics(unittest.TestCase):
    def test_uses_injected_fetch(self):
        seen = []

        def fake_fetch(url, timeout):
            seen.append((url, timeout))
            return [_payload()]

        text = fetch_lyrics("晴天", "周杰伦", 269_000, timeout=1.5, fetch=fake_fetch)
        self.assertEqual(text, "[00:01.00]故事的小黄花")
        self.assertEqual(seen[0][1], 1.5)

    def test_returns_none_when_no_match(self):
        text = fetch_lyrics("晴天", "周杰伦", 0, fetch=lambda url, t: [])
        self.assertIsNone(text)

    def test_swallows_network_error(self):
        """断网不该影响播放：任何异常都降级为 None。"""

        def boom(url, timeout):
            raise OSError("network unreachable")

        self.assertIsNone(fetch_lyrics("晴天", "周杰伦", 0, fetch=boom))

    def test_swallows_json_garbage(self):
        self.assertIsNone(fetch_lyrics("晴天", "周杰伦", 0, fetch=lambda url, t: "not-json"))


class TestCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_lyrics_cache_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cache_path_uses_track_id(self):
        path = cache_path("abc123", self.tmp)
        self.assertEqual(os.path.basename(path), "abc123.lrc")
        self.assertTrue(path.startswith(self.tmp))

    def test_roundtrip(self):
        path = write_cache("abc123", "[00:01.00]hi", self.tmp)
        self.assertIsNotNone(path)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(read_cache("abc123", self.tmp), "[00:01.00]hi")

    def test_missing_returns_none(self):
        self.assertIsNone(read_cache("nope", self.tmp))
        self.assertIsNone(read_cache("", self.tmp))

    def test_failure_returns_none_and_leaves_no_part(self):
        """目录不可创建时写缓存必须静默失败，且不留 .part 残片。"""
        blocker = os.path.join(self.tmp, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("x")
        bad_dir = os.path.join(blocker, "sub")     # 父级是文件 → 无法建目录
        self.assertIsNone(write_cache("abc", "text", bad_dir))
        self.assertFalse(os.path.exists(os.path.join(bad_dir, "abc.lrc.part")))

    def test_clear_removes_file(self):
        write_cache("abc123", "text", self.tmp)
        clear_cache("abc123", self.tmp)
        self.assertIsNone(read_cache("abc123", self.tmp))

    def test_clear_missing_is_silent(self):
        clear_cache("nonexistent", self.tmp)      # 不抛即通过


class TestFetchWorker(unittest.TestCase):
    def _run(self, worker, received, timeout_ms=4000):
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        worker.found.connect(lambda tid, text: (received.append((tid, text)), loop.quit()))
        QTimer.singleShot(timeout_ms, loop.quit)
        worker.start()
        loop.exec()
        worker.wait(2000)

    def test_emits_found_with_track_id(self):
        received = []
        worker = LyricsFetchWorker("tid-1", "晴天", "周杰伦", 269_000)
        with mock.patch("app.lyrics_online.fetch_lyrics", return_value="[00:01.00]hi"):
            self._run(worker, received)
        self.assertEqual(received, [("tid-1", "[00:01.00]hi")])

    def test_silent_when_nothing_found(self):
        received = []
        worker = LyricsFetchWorker("tid-2", "晴天", "周杰伦", 0)
        with mock.patch("app.lyrics_online.fetch_lyrics", return_value=None):
            self._run(worker, received, timeout_ms=600)
        self.assertEqual(received, [])


if __name__ == "__main__":
    unittest.main()
