# -*- coding: utf-8 -*-
"""联网歌词匹配：URL 构造 / 脏数据解析 / 选曲打分 / 缓存读写 / 后台线程。

设计要点：所有网络请求都通过 `fetch` 参数注入，本文件**完全不联网**。
选曲规则是「宁可没有，也不能配错」——没有身份信号（歌名对得上或时长差 ≤2s）
的候选一律丢弃，避免给用户塞一首别的歌的歌词。

v2.4 追加：标签清洗、多轮查询计划、打分收紧、负缓存、预算与限流。
"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lyrics_online import (
    FetchOutcome,
    LyricsFetchWorker,
    RateLimited,
    ServerBusy,
    as_hits,
    build_get_url,
    build_keyword_url,
    build_search_url,
    build_web_search_url,
    cache_path,
    clean_artist,
    clean_title,
    clear_cache,
    clear_miss,
    fetch_lyrics,
    fetch_outcome,
    lookup_plan,
    miss_path,
    parse_hits,
    pick_best,
    read_cache,
    read_miss,
    score_hit,
    to_halfwidth,
    usable_text,
    write_cache,
    write_miss,
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
    def _run(self, worker, received, timeout_ms=4000, missed=None, aborted=None):
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop()
        worker.found.connect(lambda tid, text: (received.append((tid, text)), loop.quit()))
        if missed is not None:
            worker.missed.connect(lambda tid: (missed.append(tid), loop.quit()))
        if aborted is not None:
            worker.aborted.connect(lambda tid: (aborted.append(tid), loop.quit()))
        QTimer.singleShot(timeout_ms, loop.quit)
        worker.start()
        loop.exec()
        worker.wait(2000)

    def test_emits_found_with_track_id(self):
        received = []
        worker = LyricsFetchWorker("tid-1", "晴天", "周杰伦", 269_000)
        with mock.patch("app.lyrics_online.fetch_outcome",
                        return_value=FetchOutcome("[00:01.00]hi")):
            self._run(worker, received)
        self.assertEqual(received, [("tid-1", "[00:01.00]hi")])

    def test_emits_missed_when_really_not_found(self):
        received, missed = [], []
        worker = LyricsFetchWorker("tid-2", "晴天", "周杰伦", 0)
        with mock.patch("app.lyrics_online.fetch_outcome",
                        return_value=FetchOutcome(None, aborted=False)):
            self._run(worker, received, timeout_ms=600, missed=missed)
        self.assertEqual(received, [])
        self.assertEqual(missed, ["tid-2"])

    def test_emits_aborted_not_missed_when_rate_limited(self):
        """限流中止 ≠ 没歌词：绝不能发 missed（会误记负缓存 7 天），但要发 aborted
        让界面把「正在找」换成「失败可重试」，否则歌词区会一直卡在加载提示。"""
        received, missed, aborted = [], [], []
        worker = LyricsFetchWorker("tid-3", "晴天", "周杰伦", 0)
        with mock.patch("app.lyrics_online.fetch_outcome",
                        return_value=FetchOutcome(None, aborted=True)):
            self._run(worker, received, timeout_ms=600, missed=missed, aborted=aborted)
        self.assertEqual(received, [])
        self.assertEqual(missed, [])
        self.assertEqual(aborted, ["tid-3"])


class TestCleanTitle(unittest.TestCase):
    """真实曲库的脏标签是匹配失败的头号原因，清洗规则必须逐条钉住。"""

    def test_strips_noise_brackets(self):
        self.assertEqual(clean_title("晴天 (Live)"), "晴天")
        self.assertEqual(clean_title("晴天 [Explicit]"), "晴天")
        self.assertEqual(clean_title("晴天 (Remastered 2011)"), "晴天")
        self.assertEqual(clean_title("晴天 (Acoustic Version)"), "晴天")

    def test_strips_chinese_noise_brackets(self):
        """全角括号要先转半角，否则括号组根本匹配不到。"""
        self.assertEqual(clean_title("晴天（现场版）"), "晴天")
        self.assertEqual(clean_title("歌名（电视剧《长安十二时辰》主题曲）"), "歌名")

    def test_keeps_brackets_without_noise_word(self):
        """不含噪声词的括号是歌名的一部分，不能一起删掉。"""
        self.assertEqual(clean_title("Song (Part 2)"), "Song (Part 2)")
        self.assertEqual(clean_title("梦想 (Live) 归来"), "梦想 归来")

    def test_strips_leading_track_number(self):
        self.assertEqual(clean_title("01. 晴天"), "晴天")
        self.assertEqual(clean_title("03 - 晴天"), "晴天")
        self.assertEqual(clean_title("[07] 晴天"), "晴天")

    def test_numeric_title_is_not_a_track_number(self):
        """Taylor Swift 的《22》就是歌名，没有分隔符就不能当音轨号砍掉。"""
        self.assertEqual(clean_title("22"), "22")

    def test_strips_feat_tail(self):
        self.assertEqual(clean_title("Song feat. Someone"), "Song")
        self.assertEqual(clean_title("Song ft. Someone"), "Song")

    def test_strips_dash_noise_suffix(self):
        self.assertEqual(clean_title("晴天 - Remastered 2011"), "晴天")

    def test_keeps_dash_that_is_part_of_title(self):
        self.assertEqual(clean_title("Jay-Z - 99 Problems"), "Jay-Z - 99 Problems")

    def test_halfwidth(self):
        self.assertEqual(to_halfwidth("（ＡＢ）"), "(AB)")
        self.assertEqual(clean_title("晴天（Live）"), "晴天")

    def test_empty_and_all_noise(self):
        self.assertEqual(clean_title(""), "")
        # 洗空了要退回原文，不能返回空串（空串会被 lookup_plan 直接判成「没歌名」）
        self.assertEqual(clean_title("(纯音乐)"), "(纯音乐)")

    def test_idempotent(self):
        once = clean_title("01. 晴天 (Live)")
        self.assertEqual(clean_title(once), once)

    def test_strips_language_and_mv_noise(self):
        """v2.6.2 新增噪声词：国语版 / 粤语版 / MV / live at。"""
        self.assertEqual(clean_title("晴天 (国语版)"), "晴天")
        self.assertEqual(clean_title("海阔天空 (粤语)"), "海阔天空")
        self.assertEqual(clean_title("Song (MV)"), "Song")
        self.assertEqual(clean_title("Song (Live At Tokyo)"), "Song")
        # 「国语」不是括号噪声时不误伤正常歌名
        self.assertEqual(clean_title("中国话"), "中国话")


class TestCleanArtist(unittest.TestCase):
    def test_splits_multi_artist(self):
        self.assertEqual(clean_artist("周杰伦/费玉清"), "周杰伦")
        self.assertEqual(clean_artist("周杰伦; 费玉清"), "周杰伦")
        self.assertEqual(clean_artist("周杰伦、费玉清"), "周杰伦")
        self.assertEqual(clean_artist("周杰伦|费玉清"), "周杰伦")

    def test_splits_feat(self):
        self.assertEqual(clean_artist("Jay Chou feat. Someone"), "Jay Chou")
        self.assertEqual(clean_artist("Jay Chou ft. Someone"), "Jay Chou")

    def test_keeps_ampersand_and_comma(self):
        """`Simon & Garfunkel`、`Earth, Wind & Fire` 是单一艺人名，切了就搜不到。"""
        self.assertEqual(clean_artist("Simon & Garfunkel"), "Simon & Garfunkel")
        self.assertEqual(clean_artist("Earth, Wind & Fire"), "Earth, Wind & Fire")

    def test_empty(self):
        self.assertEqual(clean_artist(""), "")


class TestLookupPlan(unittest.TestCase):
    def test_get_comes_first_with_duration(self):
        plan = lookup_plan("晴天", "周杰伦", "叶惠美", 269_000)
        self.assertEqual(plan[0].kind, "get")
        self.assertIn("/api/get?", plan[0].url)
        self.assertIn("duration=269", plan[0].url)
        self.assertIn("album_name=", plan[0].url)

    def test_falls_back_to_search_then_keyword(self):
        plan = lookup_plan("晴天", "周杰伦", "", 269_000)
        kinds = [q.kind for q in plan]
        # get → search(原始艺人) → keyword(标题) → keyword(标题+主艺人)
        self.assertEqual(kinds, ["get", "search", "keyword", "keyword"])
        # 最后一个兜底是「标题 + 主艺人」全文搜
        self.assertIn("q=", plan[-1].url)
        self.assertIn("周杰伦", parse_qs(urlparse(plan[-1].url).query)["q"][0])

    def test_multi_artist_adds_primary_artist_query(self):
        plan = lookup_plan("晴天", "周杰伦/费玉清", "", 0)
        self.assertEqual([q.kind for q in plan],
                         ["get", "search", "search", "keyword", "keyword"])
        raw_artist = parse_qs(urlparse(plan[1].url).query)["artist_name"][0]
        primary_artist = parse_qs(urlparse(plan[2].url).query)["artist_name"][0]
        self.assertEqual(raw_artist, "周杰伦/费玉清")
        self.assertEqual(primary_artist, "周杰伦")

    def test_no_artist_means_keyword_only(self):
        plan = lookup_plan("晴天", "", "", 0)
        self.assertEqual([q.kind for q in plan], ["keyword"])

    def test_empty_title_means_no_plan(self):
        self.assertEqual(lookup_plan("", "周杰伦"), [])
        self.assertEqual(lookup_plan("   ", "周杰伦"), [])

    def test_deduplicates_urls(self):
        plan = lookup_plan("晴天", "周杰伦", "", 0)
        self.assertEqual(len(plan), len({q.url for q in plan}))

    def test_duration_out_of_range_is_dropped(self):
        """LRCLIB 的 duration 只接受 1..3600 秒，越界会被 400 拒绝。"""
        self.assertNotIn("duration=", lookup_plan("晴天", "周杰伦", "", 0)[0].url)
        self.assertNotIn("duration=", build_get_url("晴天", "周杰伦", "", 5_000_000))
        self.assertIn("duration=3600", build_get_url("晴天", "周杰伦", "", 3_600_000))

    def test_keyword_url_uses_q(self):
        self.assertIn("q=", build_keyword_url("晴天"))
        self.assertNotIn("track_name", build_keyword_url("晴天"))

    def test_web_search_url_targets_human_page(self):
        """「在线搜索歌词」拼的是给人看的网页，不是 JSON API。"""
        url = build_web_search_url("晴天", "周杰伦")
        self.assertTrue(url.startswith("https://lrclib.net/search?"))
        self.assertNotIn("/api/", url)
        self.assertIn("q=", url)

    def test_web_search_url_includes_title_and_artist(self):
        from urllib.parse import unquote

        url = unquote(build_web_search_url("晴天", "周杰伦"))
        self.assertIn("晴天", url)
        self.assertIn("周杰伦", url)

    def test_web_search_url_skips_missing_artist(self):
        self.assertNotIn("None", build_web_search_url("晴天", ""))


class TestAsHits(unittest.TestCase):
    def test_single_object_from_get_endpoint(self):
        hits = as_hits(_payload())
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].track_name, "晴天")

    def test_not_found_body_yields_unusable_hit(self):
        """`/api/get` 404 的响应体是 {message,name,statusCode}，不能当歌词用。"""
        hits = as_hits({"message": "Failed", "name": "TrackNotFound", "statusCode": 404})
        self.assertFalse(usable_text(hits[0].text))


class TestUsableText(unittest.TestCase):
    def test_rejects_blank_and_tag_only(self):
        self.assertFalse(usable_text(None))
        self.assertFalse(usable_text(""))
        self.assertFalse(usable_text("  \n\t "))
        self.assertFalse(usable_text("[00:01.00]"))
        self.assertFalse(usable_text("[Chorus][00:12.00]"))

    def test_accepts_real_lyrics(self):
        self.assertTrue(usable_text("[00:01.00]故事的小黄花"))
        self.assertTrue(usable_text("故事的小黄花"))


class TestScoringStricter(unittest.TestCase):
    """v2.4 收紧：去掉「只有艺人对得上也算」这一条。"""

    def test_artist_only_match_is_rejected(self):
        hits = parse_hits([_payload(trackName="别的歌", artistName="周杰伦", duration=200)])
        self.assertIsNone(pick_best(hits, "晴天", "周杰伦", 269_000))

    def test_title_only_match_without_duration_still_accepted(self):
        """没有时长信息时，歌名对上就是唯一信号，仍要能用。"""
        hits = parse_hits([_payload(trackName="晴天", artistName="别的歌手", duration=0)])
        self.assertIsNotNone(pick_best(hits, "晴天", "周杰伦", 0))

    def test_cover_version_is_penalized(self):
        """同名翻唱：歌名对上但艺人和时长都不符，必须让位给真正的原唱。"""
        hits = parse_hits([
            _payload(trackName="晴天", artistName="翻唱歌手", duration=180,
                     syncedLyrics="[00:01.00]cover"),
            _payload(trackName="晴天", artistName="周杰伦", duration=269,
                     syncedLyrics="[00:01.00]original"),
        ])
        best = pick_best(hits, "晴天", "周杰伦", 269_000)
        self.assertEqual(best.artist_name, "周杰伦")

    def test_synced_wins_over_higher_scoring_plain(self):
        """能滚动的同步稿严格优于纯文本稿，即使纯文本的时长更准。"""
        hits = parse_hits([
            _payload(trackName="晴天", artistName="周杰伦", duration=269,
                     syncedLyrics=None, plainLyrics="纯文本"),
            _payload(trackName="晴天", artistName="周杰伦", duration=0,
                     syncedLyrics="[00:01.00]同步", plainLyrics=None),
        ])
        best = pick_best(hits, "晴天", "周杰伦", 269_000)
        self.assertIsNotNone(best)
        self.assertEqual(best.synced, "[00:01.00]同步")

    def test_short_title_does_not_match_longer_song(self):
        """单字歌名不能靠「包含」匹配到别的歌——这是配错词的典型来源。"""
        hits = parse_hits([_payload(trackName="下雨天", artistName="别人", duration=0)])
        self.assertIsNone(pick_best(hits, "雨", "", 0))

    def test_score_hit_reports_gate(self):
        hit = parse_hits([_payload()])[0]
        score, gate = score_hit(hit, "晴天".lower(), "周杰伦", 269.0)
        self.assertTrue(gate)
        self.assertGreaterEqual(score, 6.5)


class TestAlbumBridge(unittest.TestCase):
    """v2.8.2：本地中文标题 ↔ LRCLIB 英文 trackName 语言不一致时，专辑名是唯一桥梁。

    真实案例：本地《痴人说梦》（HOYO-MiX），LRCLIB id=34711120 的 trackName 是英文
    `Ravings`，中文只出现在专辑名「崩坏星穹铁道-痴人说梦 Ravings」里。标题零交集、
    时长又拿不到时，专辑相等 + 艺人相符就是唯一能把两者对上号的信号。
    """

    ALBUM = "崩坏星穹铁道-痴人说梦 Ravings"

    def _ravings(self, **kwargs):
        item = {
            "trackName": "Ravings",
            "artistName": "HOYO-MiX",
            "albumName": self.ALBUM,
            "duration": 115,
            "instrumental": False,
            "syncedLyrics": "[00:06.58] She got candy",
        }
        item.update(kwargs)
        return [item]

    def test_chinese_title_matches_english_trackname_via_album(self):
        hits = parse_hits(self._ravings())
        best = pick_best(hits, "痴人说梦", "HOYO-MiX", 115_000, self.ALBUM)
        self.assertIsNotNone(best)
        self.assertEqual(best.track_name, "Ravings")

    def test_album_plus_artist_matches_without_duration(self):
        """没有时长信息时，专辑相等 + 艺人相符仍要能用。"""
        best = pick_best(parse_hits(self._ravings()), "痴人说梦", "HOYO-MiX", 0, self.ALBUM)
        self.assertIsNotNone(best)

    def test_album_match_without_artist_is_rejected(self):
        """专辑相同但艺人不同：不能靠专辑一条就配词（同一张多曲专辑会配错）。"""
        hits = parse_hits(self._ravings(artistName="别的艺人"))
        self.assertIsNone(pick_best(hits, "痴人说梦", "HOYO-MiX", 0, self.ALBUM))


class TestFetchStrategy(unittest.TestCase):
    def test_stops_after_good_hit(self):
        """高信任度命中后不再往下打查询——LRCLIB 有速率限制。"""
        calls = []

        def fake_fetch(url, timeout):
            calls.append(url)
            return [_payload()]

        fetch_lyrics("晴天", "周杰伦", 269_000, fetch=fake_fetch)
        self.assertEqual(len(calls), 1)

    def test_continues_to_next_query_on_empty_result(self):
        calls = []

        def fake_fetch(url, timeout):
            calls.append(url)
            return [] if "api/get" in url else [_payload()]

        text = fetch_lyrics("晴天", "周杰伦", 269_000, fetch=fake_fetch)
        self.assertEqual(len(calls), 2)
        self.assertEqual(text, "[00:01.00]故事的小黄花")

    def test_rate_limit_stops_immediately(self):
        calls = []

        def fake_fetch(url, timeout):
            calls.append(url)
            raise RateLimited("HTTP 429")

        outcome = fetch_outcome("晴天", "周杰伦", 269_000, fetch=fake_fetch)
        self.assertIsNone(outcome.text)
        self.assertTrue(outcome.aborted, "限流必须标记为中止，不能当成「没有歌词」")
        self.assertEqual(len(calls), 1)

    def test_server_busy_skips_to_next_query_and_finds_hit(self):
        """503 是瞬时过载而非限流：跳过这条，让后面的查询命中（v2.8.2）。

        真实案例：`痴人说梦` 的 get 端点间歇 503，但 `q=痴人说梦` 稳定返回命中。
        以前 503 被当成限流立即中止，整首歌就判死了。
        """
        calls = []

        def fake_fetch(url, timeout):
            calls.append(url)
            if "api/get" in url:
                raise ServerBusy("HTTP 503")
            # keyword 查询返回命中（靠专辑桥接：标题中文 vs trackName 英文）
            if "q=" in url:
                return [{
                    "trackName": "Ravings", "artistName": "HOYO-MiX",
                    "albumName": "崩坏星穹铁道-痴人说梦 Ravings",
                    "duration": 115, "instrumental": False,
                    "syncedLyrics": "[00:06.58] She got candy",
                }]
            return []

        outcome = fetch_outcome("痴人说梦", "HOYO-MiX", 115_000,
                                fetch=fake_fetch, album="崩坏星穹铁道-痴人说梦 Ravings")
        self.assertIsNotNone(outcome.text)
        self.assertFalse(outcome.aborted)
        self.assertGreater(len(calls), 1, "503 后应继续发下一条查询")

    def test_server_busy_all_aborted_not_missed(self):
        """每条都 503：报 aborted 而不是 missed，绝不写负缓存（v2.8.2）。"""
        def fake_fetch(url, timeout):
            raise ServerBusy("HTTP 503")

        outcome = fetch_outcome("晴天", "周杰伦", 269_000, fetch=fake_fetch)
        self.assertIsNone(outcome.text)
        self.assertTrue(outcome.aborted)

    def test_exhausted_search_is_not_aborted(self):
        """把查询跑完仍然没命中 = 真的没有这首歌的歌词，可以记负缓存。"""
        outcome = fetch_outcome("晴天", "周杰伦", 269_000,
                                fetch=lambda url, t: [])
        self.assertIsNone(outcome.text)
        self.assertFalse(outcome.aborted)

    def test_rate_limit_keeps_best_effort_result(self):
        """如果限流前已经拿到候选，就返回它，别白白丢掉。"""
        calls = []

        def fake_fetch(url, timeout):
            calls.append(url)
            if len(calls) == 1:
                return [_payload(trackName="晴天", artistName="周杰伦", duration=100)]
            raise RateLimited("HTTP 429")

        outcome = fetch_outcome("晴天", "周杰伦", 269_000, fetch=fake_fetch)
        self.assertIsNotNone(outcome.text)
        self.assertTrue(outcome.aborted)

    def test_single_query_error_does_not_abort_the_rest(self):
        calls = []

        def fake_fetch(url, timeout):
            calls.append(url)
            if len(calls) == 1:
                raise OSError("connection reset")
            return [_payload()]

        text = fetch_lyrics("晴天", "周杰伦", 269_000, fetch=fake_fetch)
        self.assertEqual(len(calls), 2)
        self.assertIsNotNone(text)

    def test_progress_reports_each_query(self):
        """progress 回调按 1..N 逐步上报，总数全程一致（供界面显示「匹配 2/4」）。"""
        seen = []

        def fake_fetch(url, timeout):
            return []          # 全部无结果 → 走完整个查询计划

        fetch_outcome("晴天", "周杰伦", 269_000, fetch=fake_fetch,
                      progress=lambda cur, total: seen.append((cur, total)))
        self.assertGreaterEqual(len(seen), 1)
        total = seen[0][1]
        self.assertEqual([c for c, _ in seen], list(range(1, len(seen) + 1)),
                         "progress 的 cur 必须从 1 递增且不跳步")
        self.assertTrue(all(t == total for _, t in seen), "total 全程一致")

    def test_progress_stops_at_early_hit(self):
        """第一条查询就高信任命中时，progress 只报第一步。"""
        seen = []

        def fake_fetch(url, timeout):
            return [_payload()]

        outcome = fetch_outcome("晴天", "周杰伦", 269_000, fetch=fake_fetch,
                                progress=lambda cur, total: seen.append((cur, total)))
        self.assertIsNotNone(outcome.text)
        self.assertEqual(seen, [(1, seen[0][1])], "早停时只应报 1 步")

    def test_dirty_title_still_finds_lyrics(self):
        """带 `(Live)` 的脏标题：清洗后的 URL 里不能出现噪声词。"""
        seen = []

        def fake_fetch(url, timeout):
            seen.append(url)
            return [_payload()] if "live" not in url.lower() else []

        text = fetch_lyrics("晴天 (Live)", "周杰伦", 269_000, fetch=fake_fetch)
        self.assertIsNotNone(text)
        self.assertNotIn("live", seen[0].lower())


class TestMissCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qy_lyrics_miss_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip(self):
        self.assertFalse(read_miss("abc", self.tmp))
        write_miss("abc", self.tmp)
        self.assertTrue(read_miss("abc", self.tmp))
        self.assertTrue(os.path.isfile(miss_path("abc", self.tmp)))

    def test_clear(self):
        write_miss("abc", self.tmp)
        clear_miss("abc", self.tmp)
        self.assertFalse(read_miss("abc", self.tmp))

    def test_expired_entry_is_ignored(self):
        """7 天前的未命中记录应该失效，让冷门歌有机会被重新找到。"""
        write_miss("abc", self.tmp)
        old = time.time() - 8 * 86400
        with open(miss_path("abc", self.tmp), "w", encoding="utf-8") as f:
            f.write(f"{old:.0f}")
        self.assertFalse(read_miss("abc", self.tmp))

    def test_garbage_file_is_ignored(self):
        with open(miss_path("abc", self.tmp), "w", encoding="utf-8") as f:
            f.write("not-a-timestamp")
        self.assertFalse(read_miss("abc", self.tmp))

    def test_empty_track_id_is_safe(self):
        write_miss("", self.tmp)
        self.assertFalse(read_miss("", self.tmp))
        clear_miss("", self.tmp)


if __name__ == "__main__":
    unittest.main()
