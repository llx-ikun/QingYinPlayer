# -*- coding: utf-8 -*-
"""歌词匹配纯文本层（v3.0.5）：归一化 / 分词 / 相似度 / 置信分档。

这一层**没有网络、没有 Qt**，所以本文件不需要 QApplication，也不会被
`QMediaPlayer` 实例累积拖死。设计意图：把「文字怎么比」和「歌词怎么发请求」
彻底分开，前者可以精确到单字符地钉住。

测试口径说明：相似度是连续值，断言一律用「区间」而不是「等于某个小数」——
`difflib` 与 `rapidfuzz` 的取值在小数第三位上可能略有差别，钉死会变成
环境相关的假失败。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lyrics_match import (
    ALBUM_STRONG,
    ARTIST_STRONG,
    CONF_HIGH,
    CONF_LOW,
    CONF_MEDIUM,
    T2S,
    TITLE_STRONG,
    TITLE_WEAK,
    _T2S_PAIRS,
    classify_confidence,
    clean_title,
    fold,
    language_of,
    lyrics_fingerprint,
    normalize,
    prepare_title,
    same_lyrics,
    scripts_disjoint,
    similarity,
    strip_artist_prefix,
    tokens,
    version_penalty,
    words,
)


class TestT2STable(unittest.TestCase):
    """手写的繁简表必须结构完好——长度错一项就说明打错了字。"""

    def test_all_pairs_are_two_chars(self):
        bad = [token for token in _T2S_PAIRS.split() if len(token) != 2]
        self.assertEqual(bad, [], f"繁简表里有长度不是 2 的项：{bad}")

    def test_known_pairs(self):
        self.assertEqual(T2S["祕"], "秘")
        self.assertEqual(T2S["週"], "周")
        self.assertEqual(T2S["裡"], "里")
        self.assertEqual(T2S["妳"], "你")

    def test_table_is_not_tiny(self):
        """表太小说明手写时被截断了，繁简归一基本等于没做。"""
        self.assertGreater(len(T2S), 400)


class TestFold(unittest.TestCase):

    def test_fullwidth_becomes_halfwidth(self):
        self.assertEqual(fold("Ｖｉｖａ"), "viva")

    def test_accent_is_stripped(self):
        self.assertEqual(fold("Beyoncé"), "beyonce")

    def test_case_is_folded(self):
        self.assertEqual(fold("Hello"), "hello")

    def test_traditional_is_merged(self):
        self.assertEqual(fold("祕密"), fold("秘密"))

    def test_punctuation_is_kept(self):
        """`fold` 保留标点，因为 `words()` 要靠它切词。"""
        self.assertIn(" ", fold("hello world"))

    def test_empty(self):
        self.assertEqual(fold(""), "")


class TestNormalize(unittest.TestCase):

    def test_drops_punctuation_and_spaces(self):
        self.assertEqual(normalize("Don't Stop, Believin'!"), "dontstopbelievin")

    def test_keeps_cjk_and_digits(self):
        self.assertEqual(normalize("晴天 2005"), "晴天2005")

    def test_punctuation_only_is_empty(self):
        self.assertEqual(normalize("（）…—— "), "")

    def test_idempotent(self):
        once = normalize("Ｖｉｖａ la Vida (Live)")
        self.assertEqual(normalize(once), once)


class TestWords(unittest.TestCase):

    def test_latin_words(self):
        self.assertEqual(words("Hello, World!"), ["hello", "world"])

    def test_chinese_stays_one_token(self):
        """中文没有空格，`words()` 给一整段，交给 `tokens()` 切 bigram。"""
        self.assertEqual(words("下雨天"), ["下雨天"])

    def test_mixed(self):
        self.assertEqual(words("晴天 love"), ["晴天", "love"])


class TestTokens(unittest.TestCase):

    def test_chinese_bigrams(self):
        self.assertEqual(tokens("下雨天"), ["下雨", "雨天"])

    def test_single_char_is_unigram(self):
        self.assertEqual(tokens("雨"), ["雨"])

    def test_latin_is_word_level(self):
        self.assertEqual(tokens("Hello World"), ["hello", "world"])

    def test_kana_is_char_level(self):
        self.assertEqual(tokens("レモン"), ["レモ", "モン"])

    def test_hangul_is_char_level(self):
        self.assertEqual(tokens("봄날"), ["봄날"])

    def test_cyrillic_is_word_level(self):
        self.assertEqual(tokens("Катюша"), ["катюша"])


class TestSimilarity(unittest.TestCase):

    def test_identical_is_one(self):
        self.assertEqual(similarity("晴天", "晴天"), 1.0)

    def test_empty_is_zero(self):
        self.assertEqual(similarity("", "晴天"), 0.0)
        self.assertEqual(similarity("晴天", "（）"), 0.0)

    def test_case_and_space_insensitive(self):
        self.assertEqual(similarity("Viva la Vida", "viva  la  vida"), 1.0)

    def test_traditional_matches_simplified(self):
        self.assertEqual(similarity("不能说的秘密", "不能说的祕密"), 1.0)

    def test_accent_insensitive(self):
        self.assertGreater(similarity("Beyoncé", "Beyonce"), 0.99)

    def test_single_char_does_not_match_longer(self):
        """「雨」不能匹配「下雨天」——单字歌名配到别的歌是最典型的误配。"""
        self.assertLess(similarity("雨", "下雨天"), TITLE_WEAK)

    def test_short_title_does_not_match_longer(self):
        self.assertLess(similarity("晴天", "晴天娃娃"), TITLE_WEAK)

    def test_missing_one_char_still_strong(self):
        self.assertGreater(
            similarity("夜空中最亮的星", "夜空中最亮星"), TITLE_STRONG)

    def test_unrelated_is_low(self):
        self.assertLess(similarity("晴天", "孤勇者"), 0.35)

    def test_symmetric(self):
        a, b = "打上花火", "打上花火 - DAOKO"
        self.assertAlmostEqual(similarity(a, b), similarity(b, a), places=6)

    def test_word_order_tolerance(self):
        """词序调整不该掉到 0——Dice 那条路就是为此存在的。"""
        self.assertGreater(similarity("love me do", "do love me"), 0.6)


class TestLanguageOf(unittest.TestCase):

    def test_chinese(self):
        self.assertEqual(language_of("晴天"), "zh")

    def test_japanese_kana_wins_over_kanji(self):
        """日文必然混汉字，但有假名就一定是日文。"""
        self.assertEqual(language_of("打上花火 レモン"), "ja")

    def test_korean(self):
        self.assertEqual(language_of("봄날"), "ko")

    def test_russian(self):
        self.assertEqual(language_of("Катюша"), "ru")

    def test_latin(self):
        self.assertEqual(language_of("Viva la Vida"), "latin")

    def test_unknown(self):
        self.assertEqual(language_of("123 ()"), "unknown")


class TestStripArtistPrefix(unittest.TestCase):

    def test_dash_prefix(self):
        self.assertEqual(strip_artist_prefix("周杰伦 - 稻香", "周杰伦"), "稻香")

    def test_dash_suffix(self):
        self.assertEqual(strip_artist_prefix("稻香 - 周杰伦", "周杰伦"), "稻香")

    def test_slash_suffix(self):
        self.assertEqual(
            strip_artist_prefix("打上花火 / DAOKO×米津玄師", "DAOKO"), "打上花火")

    def test_not_stripped_when_artist_differs(self):
        title = "Jay-Z - 99 Problems"
        self.assertEqual(strip_artist_prefix(title, "Ed Sheeran"), title)

    def test_hyphen_inside_name_is_not_split(self):
        """`Jay-Z` 里的连字符没有空格，不该被当分隔符。"""
        self.assertEqual(strip_artist_prefix("Jay-Z - 99 Problems", "Jay-Z"),
                         "99 Problems")

    def test_empty_inputs(self):
        self.assertEqual(strip_artist_prefix("", "周杰伦"), "")
        self.assertEqual(strip_artist_prefix("稻香", ""), "稻香")


class TestPrepareTitle(unittest.TestCase):

    def test_noise_bracket_removed(self):
        self.assertEqual(prepare_title("晴天 (Live)"), "晴天")

    def test_numeric_bracket_removed(self):
        """纯数字括号视为年份/版次（v3.0.5 增补）。"""
        self.assertEqual(prepare_title("夜曲 (2005)"), "夜曲")

    def test_leading_track_number_removed(self):
        self.assertEqual(prepare_title("03. 稻香"), "稻香")

    def test_feat_tail_removed(self):
        self.assertEqual(
            prepare_title("Something Just Like This (feat. Coldplay)"),
            "Something Just Like This")

    def test_plain_title_untouched(self):
        self.assertEqual(prepare_title("Bohemian Rhapsody"), "Bohemian Rhapsody")


class TestVersionPenalty(unittest.TestCase):

    def test_karaoke_penalized(self):
        self.assertLess(version_penalty("晴天 (伴奏)"), 0)
        self.assertLess(version_penalty("Shape of You (Karaoke Version)"), 0)

    def test_live_penalized(self):
        self.assertLess(version_penalty("起风了 (Live)"), 0)

    def test_normal_title_not_penalized(self):
        self.assertEqual(version_penalty("晴天"), 0.0)

    def test_song_name_containing_live_is_safe(self):
        """`Live and Let Die` 歌名里就有 live，但它没有被删掉的括号，不该扣分。"""
        self.assertEqual(version_penalty("Live and Let Die"), 0.0)


class TestCleanTitleCompat(unittest.TestCase):
    """`clean_title` 从 lyrics_online 迁到本模块，行为必须保持。"""

    def test_noise_bracket(self):
        self.assertEqual(clean_title("起风了 (Live)"), "起风了")

    def test_non_noise_bracket_kept(self):
        self.assertEqual(clean_title("Bohemian Rhapsody (Live Aid Version)"), "Bohemian Rhapsody")

    def test_empty_returns_empty(self):
        self.assertEqual(clean_title(""), "")


class TestLyricsFingerprint(unittest.TestCase):

    def test_timestamps_are_stripped(self):
        self.assertEqual(lyrics_fingerprint("[00:12.34]故事的小黄花"),
                         normalize("故事的小黄花"))

    def test_two_timelines_share_fingerprint(self):
        a = "[00:12.34]故事的小黄花\n[00:15.00]从出生那年就飘着"
        b = "[00:10.00]故事的小黄花\n[00:13.20]从出生那年就飘着"
        self.assertTrue(same_lyrics(a, b))

    def test_different_lyrics_do_not_match(self):
        self.assertFalse(same_lyrics("[00:01.00]晴天", "[00:01.00]孤勇者"))

    def test_empty_never_matches(self):
        self.assertFalse(same_lyrics("", ""))
        self.assertFalse(same_lyrics("[00:01.00]", ""))


class TestScriptsDisjoint(unittest.TestCase):
    """跨书写系统的「艺人对不上」是无从比较，不是不相似。"""

    def test_latin_vs_hangul_is_disjoint(self):
        self.assertTrue(scripts_disjoint("BTS", "방탄소년단"))

    def test_same_script_is_not_disjoint(self):
        self.assertFalse(scripts_disjoint("周杰伦", "周杰倫"))

    def test_latin_vs_han_is_disjoint(self):
        self.assertTrue(scripts_disjoint("周杰伦", "Jay Chou"))

    def test_empty_is_not_disjoint(self):
        """信息不足时不能声称「不相交」，否则会关掉本该生效的扣分。"""
        self.assertFalse(scripts_disjoint("", "周杰伦"))
        self.assertFalse(scripts_disjoint("2020", "周杰伦"))


class TestClassifyConfidence(unittest.TestCase):

    def test_gate_failure_is_low(self):
        self.assertEqual(
            classify_confidence(0.0, 0.0, 0.0, -1.0, gate=False), CONF_LOW)

    def test_title_plus_artist_is_high(self):
        self.assertEqual(
            classify_confidence(TITLE_STRONG, ARTIST_STRONG, 0.0, -1.0, gate=True),
            CONF_HIGH)

    def test_title_plus_duration_is_high(self):
        self.assertEqual(
            classify_confidence(TITLE_STRONG, 0.0, 0.0, 1.0, gate=True), CONF_HIGH)

    def test_title_alone_is_medium(self):
        self.assertEqual(
            classify_confidence(TITLE_STRONG, 0.0, 0.0, -1.0, gate=True),
            CONF_MEDIUM)

    def test_weak_title_alone_is_low(self):
        """0.70~0.85 的弱标题单打独斗：正是「晴天→晴天娃娃」的温床。"""
        self.assertEqual(
            classify_confidence(TITLE_WEAK, 0.0, 0.0, -1.0, gate=True), CONF_LOW)

    def test_weak_title_with_artist_is_medium(self):
        self.assertEqual(
            classify_confidence(TITLE_WEAK, ARTIST_STRONG, 0.0, -1.0, gate=True),
            CONF_MEDIUM)

    def test_duration_only_is_medium(self):
        self.assertEqual(
            classify_confidence(0.0, 0.0, 0.0, 1.0, gate=True), CONF_MEDIUM)

    def test_duration_plus_artist_is_high(self):
        self.assertEqual(
            classify_confidence(0.0, ARTIST_STRONG, 0.0, 1.0, gate=True), CONF_HIGH)

    def test_album_bridge_is_medium(self):
        """跨语言时专辑是唯一桥梁：专辑+艺人对得上就够 medium。"""
        self.assertEqual(
            classify_confidence(0.0, ARTIST_STRONG, ALBUM_STRONG, -1.0, gate=True),
            CONF_MEDIUM)


if __name__ == "__main__":
    unittest.main()
