# -*- coding: utf-8 -*-
"""多源联网歌词：URL 构造 / 平台解析 / 候选挑选 / 多源协调 / 后台线程。

设计要点：所有网络请求都通过 `fetch` 参数注入，本文件**完全不联网**。
三源（LRCLIB / 网易云 / QQ音乐）并行取最优——哪个源最可信取哪个，某一路
挂掉自动被其它源兜住。身份门槛沿用 `lyrics_online.pick_best`（标题对上或
时长差 ≤2s），配错词比没词更糟。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lyrics_multi import (
    MultiSourceWorker,
    build_netease_lyric_url,
    build_netease_search_url,
    build_qq_lyric_url,
    build_qq_search_url,
    consensus_sources,
    fetch_netease,
    fetch_outcome_multi,
    fetch_qq,
    parse_netease_lyric,
    parse_netease_search,
    parse_qq_lyric,
    parse_qq_search,
    pick_with_consensus,
)
from app.lyrics_online import LyricHit


def setUpModule():
    from PySide6.QtWidgets import QApplication
    global _app
    _app = QApplication.instance() or QApplication(sys.argv[:1])


# ---------- 平台 payload 夹具 ----------

def _netease_search(song_id=123, title="晴天", artist="周杰伦", duration_ms=269_000):
    return {
        "result": {
            "songs": [
                {"id": song_id, "name": title,
                 "artists": [{"name": artist}],
                 "album": {"name": "叶惠美"}, "duration": duration_ms},
            ]
        }
    }


def _netease_lyric(lrc="[00:01.00]故事的小黄花"):
    return {"lrc": {"lyric": lrc}, "code": 200}


def _qq_search(mid="mid123", title="晴天", artist="周杰伦", interval=269):
    return {"code": 0, "data": {"song": {"list": [
        {"songmid": mid, "songname": title,
         "singer": [{"name": artist}],
         "albumname": "叶惠美", "interval": interval},
    ]}}}


def _qq_lyric(lrc="[00:01.00]故事的小黄花"):
    return {"retcode": 0, "lyric": lrc}


def _netease_fetch(search=None, lyric=None):
    """按 URL 分发的网易云 fake fetch：搜索走 search，歌词走 lyric。"""
    def fetch(url, timeout):
        if "/search/get" in url:
            return search if search is not None else _netease_search()
        if "/song/lyric" in url:
            return lyric if lyric is not None else _netease_lyric()
        return None
    return fetch


def _qq_fetch(search=None, lyric=None):
    def fetch(url, timeout):
        if "client_search_cp" in url:
            return search if search is not None else _qq_search()
        if "fcg_query_lyric_new" in url:
            return lyric if lyric is not None else _qq_lyric()
        return None
    return fetch


class TestSearchUrl(unittest.TestCase):
    def test_netease_search_encodes_keyword(self):
        url = build_netease_search_url("晴天")
        self.assertTrue(url.startswith("https://music.163.com/api/search/get?"))
        self.assertIn("type=1", url)
        self.assertNotIn("晴天", url)                     # 中文要百分号编码
        self.assertIn("%E6%99%B4%E5%A4%A9", url)

    def test_netease_lyric_url_carries_id(self):
        url = build_netease_lyric_url(123)
        self.assertIn("id=123", url)
        self.assertIn("lv=1", url)
        self.assertIn("tv=-1", url)

    def test_qq_search_encodes_keyword(self):
        url = build_qq_search_url("晴天")
        self.assertTrue(url.startswith("https://c.y.qq.com/soso/fcgi-bin/client_search_cp?"))
        self.assertIn("format=json", url)
        self.assertNotIn("晴天", url)

    def test_qq_lyric_url_uses_nobase64(self):
        url = build_qq_lyric_url("mid123")
        self.assertIn("songmid=mid123", url)
        self.assertIn("nobase64=1", url)                  # 1 才返回明文 LRC


class TestParseNetease(unittest.TestCase):
    def test_parses_normal_search(self):
        cands = parse_netease_search(_netease_search())
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertEqual(c["id"], 123)
        self.assertEqual(c["title"], "晴天")
        self.assertEqual(c["artist"], "周杰伦")
        self.assertEqual(c["album"], "叶惠美")
        self.assertEqual(c["duration_sec"], 269)          # 毫秒 → 秒

    def test_tolerates_garbage(self):
        self.assertEqual(parse_netease_search(None), [])
        self.assertEqual(parse_netease_search({"result": "x"}), [])
        self.assertEqual(parse_netease_search({"result": {"songs": [None, 3]}}), [])
        self.assertEqual(parse_netease_search({"result": {"songs": [{}]}}), [])

    def test_lyric_returns_lrc_text(self):
        self.assertEqual(parse_netease_lyric(_netease_lyric()), "[00:01.00]故事的小黄花")

    def test_lyric_missing_or_empty_is_none(self):
        self.assertIsNone(parse_netease_lyric(None))
        self.assertIsNone(parse_netease_lyric({"code": 200}))
        self.assertIsNone(parse_netease_lyric({"lrc": {"lyric": "  \n"}}))


class TestParseQQ(unittest.TestCase):
    def test_parses_normal_search(self):
        cands = parse_qq_search(_qq_search())
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertEqual(c["mid"], "mid123")
        self.assertEqual(c["title"], "晴天")
        self.assertEqual(c["artist"], "周杰伦")
        self.assertEqual(c["duration_sec"], 269)          # interval 本来就是秒

    def test_tolerates_garbage(self):
        self.assertEqual(parse_qq_search(None), [])
        self.assertEqual(parse_qq_search({"data": "x"}), [])
        self.assertEqual(parse_qq_search({"data": {"song": {"list": [None]}}}), [])
        self.assertEqual(parse_qq_search({"data": {"song": {"list": [{}]}}}), [])

    def test_lyric_returns_lrc_text(self):
        self.assertEqual(parse_qq_lyric(_qq_lyric()), "[00:01.00]故事的小黄花")

    def test_lyric_rejects_nonzero_code(self):
        self.assertIsNone(parse_qq_lyric({"retcode": -1310, "lyric": "x"}))
        self.assertIsNone(parse_qq_lyric({"code": 1, "lyric": "x"}))

    def test_lyric_missing_is_none(self):
        self.assertIsNone(parse_qq_lyric(None))
        self.assertIsNone(parse_qq_lyric({"retcode": 0}))


class TestFetchNetease(unittest.TestCase):
    def test_happy_path_returns_hit(self):
        hit, aborted = fetch_netease("晴天", "周杰伦", 269_000, timeout=1.5,
                                     fetch=_netease_fetch())
        self.assertFalse(aborted)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.text, "[00:01.00]故事的小黄花")

    def test_empty_search_returns_none(self):
        hit, aborted = fetch_netease("晴天", "周杰伦", 0,
                                     fetch=_netease_fetch(search={}))
        self.assertIsNone(hit)
        self.assertFalse(aborted)

    def test_network_error_degrades_to_none(self):
        def boom(url, timeout):
            raise OSError("unreachable")

        hit, aborted = fetch_netease("晴天", "周杰伦", 0, fetch=boom)
        self.assertIsNone(hit)
        self.assertFalse(aborted)

    def test_skips_candidate_without_lyrics(self):
        """伴奏版排第一且无歌词：要遍历候选，找到后面那个有歌词的正版。"""
        def fetch(url, timeout):
            if "/search/get" in url:
                return {"result": {"songs": [
                    {"id": 1, "name": "晴天", "artists": [{"name": "伴奏"}],
                     "album": {"name": "x"}, "duration": 269_000},
                    {"id": 2, "name": "晴天", "artists": [{"name": "周杰伦"}],
                     "album": {"name": "叶惠美"}, "duration": 269_000},
                ]}}
            if "id=1" in url:
                return {"lrc": {"lyric": ""}}             # 伴奏版无歌词
            return _netease_lyric()

        hit, _ = fetch_netease("晴天", "周杰伦", 269_000, fetch=fetch)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.artist_name, "周杰伦")


class TestFetchQQ(unittest.TestCase):
    def test_happy_path_returns_hit(self):
        hit, aborted = fetch_qq("晴天", "周杰伦", 269_000, timeout=1.5,
                                fetch=_qq_fetch())
        self.assertFalse(aborted)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.text, "[00:01.00]故事的小黄花")

    def test_empty_search_returns_none(self):
        hit, _ = fetch_qq("晴天", "周杰伦", 0, fetch=_qq_fetch(search={"code": 0, "data": {}}))
        self.assertIsNone(hit)

    def test_network_error_degrades_to_none(self):
        def boom(url, timeout):
            raise OSError("unreachable")

        self.assertIsNone(fetch_qq("晴天", "周杰伦", 0, fetch=boom)[0])


class TestFetchOutcomeMulti(unittest.TestCase):
    def _lrclib_payload(self, track_name="晴天", artist_name="周杰伦",
                        duration=269, synced="[00:01.00]故事的小黄花"):
        return [{"trackName": track_name, "artistName": artist_name,
                 "albumName": "叶惠美", "duration": duration,
                 "instrumental": False, "syncedLyrics": synced,
                 "plainLyrics": None}]

    def _fetches(self, lrclib=False, netease=False, qq=False, lrclib_fetch=None):
        """三源注入。lrclib 参数：False/None=空结果、True=默认命中夹具、
        或直接传 payload（list/dict）。netease/qq：True=命中默认夹具、否则空结果。"""
        def lrclib_fetcher(url, timeout):
            if lrclib_fetch is not None:
                return lrclib_fetch(url, timeout)
            if lrclib is True:
                return self._lrclib_payload()
            if lrclib:                                 # 传入的 payload 直接用
                return lrclib
            return []

        return {
            "LRCLIB": lrclib_fetcher,
            "网易云": _netease_fetch(search=_netease_search() if netease else {}),
            "QQ音乐": _qq_fetch(search=_qq_search() if qq else {}),
        }

    def test_lrclib_hit_wins_when_best(self):
        text, source, aborted = fetch_outcome_multi(
            "晴天", "周杰伦", 269_000, parallel=False,
            fetches=self._fetches(lrclib=True, netease=False, qq=False))
        self.assertEqual(source, "LRCLIB")
        self.assertEqual(text, "[00:01.00]故事的小黄花")
        self.assertFalse(aborted)

    def test_netease_only_hit(self):
        text, source, _ = fetch_outcome_multi(
            "晴天", "周杰伦", 269_000, parallel=False,
            fetches=self._fetches(lrclib=False, netease=True, qq=False))
        self.assertEqual(source, "网易云")
        self.assertEqual(text, "[00:01.00]故事的小黄花")

    def test_qq_only_hit(self):
        text, source, _ = fetch_outcome_multi(
            "晴天", "周杰伦", 269_000, parallel=False,
            fetches=self._fetches(lrclib=False, netease=False, qq=True))
        self.assertEqual(source, "QQ音乐")
        self.assertEqual(text, "[00:01.00]故事的小黄花")

    def test_picks_most_trustworthy_across_sources(self):
        """LRCLIB 命中同名翻唱（艺人错），网易云命中正版：跨源取网易云。"""
        lrclib = self._lrclib_payload(artist_name="翻唱歌手", duration=200)
        _text, source, _ = fetch_outcome_multi(
            "晴天", "周杰伦", 269_000, parallel=False,
            fetches=self._fetches(lrclib=lrclib, netease=True, qq=False))
        self.assertEqual(source, "网易云")

    def test_all_miss_is_not_aborted(self):
        text, source, aborted = fetch_outcome_multi(
            "晴天", "周杰伦", 269_000, parallel=False,
            fetches=self._fetches(lrclib=False, netease=False, qq=False))
        self.assertIsNone(text)
        self.assertEqual(source, "")
        self.assertFalse(aborted)               # 干净地没找到 → 可写负缓存

    def test_aborted_when_a_source_is_rate_limited_and_none_hit(self):
        def lrclib(url, timeout):
            from app.lyrics_online import RateLimited
            raise RateLimited("HTTP 429")

        text, _source, aborted = fetch_outcome_multi(
            "晴天", "周杰伦", 0, parallel=False,
            fetches=self._fetches(lrclib_fetch=lrclib, netease=False, qq=False))
        self.assertIsNone(text)
        self.assertTrue(aborted)                # 限流中止 ≠ 没歌词，不写负缓存

    def test_album_bridges_language_mismatch_across_sources(self):
        """中文标题 ↔ 英文 trackName：LRCLIB 命中靠专辑桥接（v2.8.2）。

        本地《痴人说梦》对 LRCLIB 的 `Ravings`，标题零交集；专辑名同时含两种写法
        是唯一桥梁。多源统一打分也要把 album 传下去，否则这条会漏。
        """
        lrclib = [{
            "trackName": "Ravings", "artistName": "HOYO-MiX",
            "albumName": "崩坏星穹铁道-痴人说梦 Ravings", "duration": 115,
            "instrumental": False,
            "syncedLyrics": "[00:06.58] She got candy", "plainLyrics": None,
        }]
        text, source, aborted = fetch_outcome_multi(
            "痴人说梦", "HOYO-MiX", 115_000, parallel=False,
            album="崩坏星穹铁道-痴人说梦 Ravings",
            fetches=self._fetches(lrclib=lrclib, netease=False, qq=False))
        self.assertEqual(source, "LRCLIB")
        self.assertEqual(text, "[00:06.58] She got candy")
        self.assertFalse(aborted)

    def test_empty_input_returns_nothing(self):
        text, _source, aborted = fetch_outcome_multi("", "", 0, parallel=False,
                                                    fetches=self._fetches())
        self.assertIsNone(text)
        self.assertFalse(aborted)

    def test_progress_reports_each_source(self):
        """v2.7.7：进度除了数字，还要带上「刚返回的是哪个平台」。"""
        seen = []
        fetch_outcome_multi("晴天", "周杰伦", 269_000, parallel=False,
                            fetches=self._fetches(lrclib=False, netease=False, qq=False),
                            progress=lambda done, total, name: seen.append((done, total, name)))
        self.assertEqual([d for d, _, _ in seen], [1, 2, 3])
        self.assertTrue(all(t == 3 for _, t, _ in seen))
        # 串行执行，顺序就是 DEFAULT_SOURCES 的顺序
        self.assertEqual([n for _, _, n in seen], ["LRCLIB", "网易云", "QQ音乐"])

    def test_progress_source_name_is_never_empty(self):
        """源名不能为空：并行时每个完成的 future 都必须带上自己的名字。"""
        seen = []
        fetch_outcome_multi("晴天", "周杰伦", 269_000, parallel=True,
                            fetches=self._fetches(lrclib=False, netease=False, qq=False),
                            progress=lambda done, total, name: seen.append(name))
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(name for name in seen), f"出现了空源名: {seen}")
        self.assertEqual(sorted(seen), sorted(["LRCLIB", "网易云", "QQ音乐"]))


class TestMultiSourceWorker(unittest.TestCase):
    def _run(self, worker, found=None, missed=None, aborted=None, timeout_ms=4000):
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        if found is not None:
            worker.found.connect(lambda *args: (found.append(args), loop.quit()))
        if missed is not None:
            worker.missed.connect(lambda tid: (missed.append(tid), loop.quit()))
        if aborted is not None:
            worker.aborted.connect(lambda tid: (aborted.append(tid), loop.quit()))
        QTimer.singleShot(timeout_ms, loop.quit)
        worker.start()
        loop.exec()
        worker.wait(2000)

    def test_emits_found_with_source(self):
        found = []
        worker = MultiSourceWorker("tid-1", "晴天", "周杰伦", 269_000)
        with mock.patch("app.lyrics_multi.fetch_outcome_multi",
                        return_value=("[00:01.00]hi", "网易云", False)):
            self._run(worker, found=found)
        self.assertEqual(found, [("tid-1", "[00:01.00]hi", "网易云")])

    def test_emits_missed_when_really_not_found(self):
        missed = []
        worker = MultiSourceWorker("tid-2", "晴天", "周杰伦", 0)
        with mock.patch("app.lyrics_multi.fetch_outcome_multi",
                        return_value=(None, "", False)):
            self._run(worker, missed=missed, timeout_ms=600)
        self.assertEqual(missed, ["tid-2"])

    def test_emits_aborted_not_missed_when_interrupted(self):
        missed, aborted = [], []
        worker = MultiSourceWorker("tid-3", "晴天", "周杰伦", 0)
        with mock.patch("app.lyrics_multi.fetch_outcome_multi",
                        return_value=(None, "", True)):
            self._run(worker, missed=missed, aborted=aborted, timeout_ms=600)
        self.assertEqual(missed, [])
        self.assertEqual(aborted, ["tid-3"])


class TestConsensusVoting(unittest.TestCase):
    """v3.0.5 跨源投票：多个源给出逐字相同的正文时，「就是这一版」更可信。

    这不是拍脑袋——单源命中的固有风险是某平台把同名不同曲排在第一，而它的
    身份信号恰好勉强过关。三个源说同一件事，和一个源说一件事，可信度不同。
    """

    LYRICS_A = "[00:01.00]故事的小黄花\n[00:05.00]从出生那年就飘着"
    LYRICS_B = "[00:02.00]故事的小黄花\n[00:06.00]从出生那年就飘着"   # 时间轴不同、正文一致
    LYRICS_OTHER = "[00:01.00]孤勇者\n[00:05.00]都是勇敢的"

    def _hit(self, track: str, artist: str, duration: int, text: str):
        return LyricHit(track_name=track, artist_name=artist, album_name="",
                        duration=duration, synced=text, plain=None,
                        instrumental=False)

    def test_identical_bodies_count_as_agreement(self):
        pairs = [
            ("LRCLIB", self._hit("晴天", "周杰伦", 269, self.LYRICS_A)),
            ("网易云", self._hit("晴天", "周杰伦", 270, self.LYRICS_B)),
        ]
        self.assertEqual(consensus_sources(pairs, 0), ["LRCLIB", "网易云"])

    def test_different_bodies_do_not_agree(self):
        pairs = [
            ("LRCLIB", self._hit("晴天", "周杰伦", 269, self.LYRICS_A)),
            ("网易云", self._hit("晴天", "周杰伦", 269, self.LYRICS_OTHER)),
        ]
        self.assertEqual(consensus_sources(pairs, 0), ["LRCLIB"])

    def test_single_source_has_no_consensus(self):
        pairs = [("LRCLIB", self._hit("晴天", "周杰伦", 269, self.LYRICS_A))]
        self.assertEqual(consensus_sources(pairs, 0), ["LRCLIB"])

    def test_out_of_range_index_is_safe(self):
        pairs = [("LRCLIB", self._hit("晴天", "周杰伦", 269, self.LYRICS_A))]
        self.assertEqual(consensus_sources(pairs, 5), [])
        self.assertEqual(consensus_sources([], 0), [])

    def test_empty_lyrics_never_vote(self):
        """空正文不能互相投票——否则两个「查到了但没词」的源会伪造共识。"""
        pairs = [
            ("LRCLIB", self._hit("晴天", "周杰伦", 269, "")),
            ("网易云", self._hit("晴天", "周杰伦", 269, "")),
        ]
        self.assertEqual(consensus_sources(pairs, 0), [])

    def test_consensus_breaks_tie_between_sources(self):
        """身份信号打平时，两个源一致的那条应当胜出。"""
        pairs = [
            ("LRCLIB", self._hit("晴天", "周杰伦", 269, self.LYRICS_A)),
            ("网易云", self._hit("晴天", "周杰伦", 269, self.LYRICS_A)),
            ("QQ音乐", self._hit("晴天", "周杰伦", 269, self.LYRICS_OTHER)),
        ]
        best, source, detail, agreed = pick_with_consensus(pairs, "晴天", "周杰伦", 269_000)
        self.assertIsNotNone(best)
        self.assertEqual(source, "LRCLIB")
        self.assertEqual(sorted(agreed), ["LRCLIB", "网易云"])
        # 详情里给的是**身份分**，共识加分只影响排序，不写进 detail.score
        self.assertGreater(detail.score, 0)
        self.assertEqual(best.synced, self.LYRICS_A)

    def test_consensus_does_not_override_identity_signal(self):
        """投票只用来打破平局：标题精确仍要压过「三个源一致的错歌」。"""
        pairs = [
            ("LRCLIB", self._hit("晴天", "周杰伦", 269, self.LYRICS_A)),
            ("网易云", self._hit("孤勇者", "陈奕迅", 250, self.LYRICS_OTHER)),
            ("QQ音乐", self._hit("孤勇者", "陈奕迅", 250, self.LYRICS_OTHER)),
        ]
        best, source, _detail, _agreed = pick_with_consensus(
            pairs, "晴天", "周杰伦", 269_000)
        self.assertIsNotNone(best)
        self.assertEqual(source, "LRCLIB")

    def test_detail_sink_is_filled_on_hit(self):
        pairs_hit = self._hit("晴天", "周杰伦", 269, self.LYRICS_A)

        def fake_source(name):
            def run(title, artist, duration_ms, timeout, fetch, album):
                return pairs_hit, False
            return run

        sink = {}
        text, _source, aborted = fetch_outcome_multi(
            "晴天", "周杰伦", 269_000, parallel=False,
            sources=[("LRCLIB", fake_source("LRCLIB"))], detail_sink=sink)
        self.assertIsNotNone(text)
        self.assertFalse(aborted)
        self.assertEqual(sink["confidence"], "high")
        self.assertGreaterEqual(sink["title_sim"], 0.99)
        self.assertIn("LRCLIB", sink["consensus"])

    def test_detail_sink_stays_empty_on_miss(self):
        def fake_source(title, artist, duration_ms, timeout, fetch, album):
            return None, False

        sink = {}
        fetch_outcome_multi("晴天", "周杰伦", 269_000, parallel=False,
                            sources=[("LRCLIB", fake_source)], detail_sink=sink)
        self.assertEqual(sink, {})


if __name__ == "__main__":
    unittest.main()
