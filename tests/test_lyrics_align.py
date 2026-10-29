# -*- coding: utf-8 -*-
"""联网歌词对齐（LyricTimestamps）：key 校验 / 三步流程 / 错误分类 / 后台线程。

设计要点：所有网络请求通过 `fetch` 参数注入，本文件**完全不联网**。
`align_lyrics` 是纯函数（读本地音频 + 调注入的 fetch + 拼 multipart），
错误码用 `describe_error` 统一转中文，UI 只关心 AlignOutcome 的三态。
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.lyrics_align import (
    AlignOutcome,
    LyricsAlignWorker,
    _Response,
    _build_multipart,
    align_lyrics,
    describe_error,
    sidecar_lrc_path,
    verify_key,
    write_sidecar_lrc,
)
from app.models import Settings


def setUpModule():
    from PySide6.QtWidgets import QApplication
    global _app
    _app = QApplication.instance() or QApplication(sys.argv[:1])


def _resp(status: int, body, content_type: str = "application/json") -> _Response:
    if isinstance(body, str):
        body = body.encode("utf-8")
    return _Response(status=status, body=body, content_type=content_type)


LRC_OK = "[00:01.00]第一句歌词\n[00:05.00]第二句歌词"


class _FakeHttp:
    """按 URL 后缀分发响应，覆盖三步流程；测试改字段即可模拟各错误。"""

    def __init__(self):
        self.calls: list[tuple] = []
        self.usage = _resp(200, '{"plan":"pro","tier":"pro","remaining_minutes":10}')
        self.create = _resp(201, '{"job_id":"job123","status":"queued"}')
        self.poll = _resp(200, '{"job_id":"job123","status":"done"}')
        self.export = _resp(200, LRC_OK, "text/plain; charset=utf-8")

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body, timeout))
        if url.endswith("/v1/usage"):
            return self.usage
        if "/exports/lrc" in url:
            return self.export
        if method == "POST" and url.endswith("/v1/alignments"):
            return self.create
        if method == "GET" and "/v1/alignments/" in url:
            return self.poll
        return _resp(404, '{"code":"job_not_found","message":"no"}')

    @property
    def create_body(self) -> bytes:
        for method, _url, _headers, body, _timeout in self.calls:
            if method == "POST":
                return body
        return b""


def _tmp_audio(content: bytes = b"fake-mp3-bytes", suffix: str = ".mp3") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, content)
    os.close(fd)
    return path


class TestDescribeError(unittest.TestCase):
    def test_known_codes(self):
        self.assertIn("Key", describe_error("invalid_api_key"))
        self.assertIn("30MB", describe_error("file_too_large"))
        self.assertIn("额度", describe_error("limit_reached"))

    def test_unknown_code_falls_back(self):
        self.assertEqual(describe_error("whatever"), "对齐失败，请重试")

    def test_empty_code(self):
        self.assertEqual(describe_error(""), "")


class TestVerifyKey(unittest.TestCase):
    def test_valid_key(self):
        fake = _FakeHttp()
        self.assertTrue(verify_key("ltk_ok", fetch=fake))

    def test_anonymous_is_invalid(self):
        fake = _FakeHttp()
        fake.usage = _resp(200, '{"plan":"anonymous"}')
        self.assertFalse(verify_key("ltk_bad", fetch=fake))

    def test_empty_key(self):
        self.assertFalse(verify_key("", fetch=_FakeHttp()))

    def test_http_error(self):
        fake = _FakeHttp()
        fake.usage = _resp(401, '{"code":"invalid_api_key"}')
        self.assertFalse(verify_key("ltk_x", fetch=fake))


class TestBuildMultipart(unittest.TestCase):
    def test_contains_audio_and_lyrics(self):
        content_type, body = _build_multipart(b"ABC", "song.mp3", "第一行\n第二行")
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="audio_file"', body)
        self.assertIn(b"ABC", body)
        self.assertIn('name="lyrics_text"'.encode(), body)
        self.assertIn("第一行\n第二行".encode("utf-8"), body)

    def test_filename_escaped(self):
        _ct, body = _build_multipart(b"", 'a"b\\c.mp3', "歌词")
        self.assertIn(b'filename="a_b_c.mp3"', body)


class TestAlignLyrics(unittest.TestCase):
    def test_happy_path(self):
        path = _tmp_audio()
        fake = _FakeHttp()
        outcome = align_lyrics(path, "第一句\n第二句", "ltk_ok", fetch=fake,
                               poll_interval=0)
        self.assertEqual(outcome.lrc, LRC_OK)
        self.assertFalse(outcome.soft_fail)
        self.assertEqual(outcome.error_code, "")
        # 三步都打到了
        urls = [c[1] for c in fake.calls]
        self.assertTrue(any(u.endswith("/v1/usage") for u in urls))
        self.assertTrue(any("/exports/lrc" in u for u in urls))
        # multipart 里带上了歌词文本
        self.assertIn("第一句\n第二句".encode("utf-8"), fake.create_body)

    def test_missing_key(self):
        outcome = align_lyrics(_tmp_audio(), "歌词", "", fetch=_FakeHttp())
        self.assertEqual(outcome.error_code, "missing_key")

    def test_no_lyrics(self):
        outcome = align_lyrics(_tmp_audio(), "   ", "ltk_ok", fetch=_FakeHttp())
        self.assertEqual(outcome.error_code, "no_lyrics")

    def test_no_audio_file(self):
        outcome = align_lyrics("/no/such.mp3", "歌词", "ltk_ok", fetch=_FakeHttp())
        self.assertEqual(outcome.error_code, "no_audio")

    def test_unsupported_format(self):
        outcome = align_lyrics(_tmp_audio(suffix=".xyz"), "歌词", "ltk_ok", fetch=_FakeHttp())
        self.assertEqual(outcome.error_code, "unsupported_format")

    def test_file_too_large(self):
        path = _tmp_audio()
        with mock.patch("app.lyrics_align.DIRECT_UPLOAD_LIMIT", 10):
            outcome = align_lyrics(path, "歌词", "ltk_ok", fetch=_FakeHttp())
        self.assertEqual(outcome.error_code, "file_too_large")

    def test_invalid_key_via_usage(self):
        fake = _FakeHttp()
        fake.usage = _resp(200, '{"plan":"anonymous"}')
        outcome = align_lyrics(_tmp_audio(), "歌词", "ltk_bad", fetch=fake,
                               poll_interval=0)
        self.assertEqual(outcome.error_code, "invalid_api_key")

    def test_limit_reached_on_create(self):
        fake = _FakeHttp()
        fake.create = _resp(429, '{"code":"limit_reached","message":"out"}')
        outcome = align_lyrics(_tmp_audio(), "歌词", "ltk_ok", fetch=fake,
                               poll_interval=0)
        self.assertEqual(outcome.error_code, "limit_reached")

    def test_failed_status(self):
        fake = _FakeHttp()
        fake.poll = _resp(200, '{"status":"failed","error":"boom"}')
        outcome = align_lyrics(_tmp_audio(), "歌词", "ltk_ok", fetch=fake,
                               poll_interval=0)
        self.assertEqual(outcome.error_code, "failed")

    def test_soft_fail(self):
        fake = _FakeHttp()
        fake.poll = _resp(200, '{"status":"done","soft_fail":true,'
                               '"soft_fail_code":"collapsed_region"}')
        outcome = align_lyrics(_tmp_audio(), "歌词", "ltk_ok", fetch=fake,
                               poll_interval=0)
        self.assertEqual(outcome.lrc, LRC_OK)
        self.assertTrue(outcome.soft_fail)

    def test_poll_then_done(self):
        """第一次轮询还在 queued，第二次 done——验证轮询循环推进。"""
        fake = _FakeHttp()
        fake.poll = _resp(200, '{"status":"queued","progress":10}')
        responses = [fake.poll,
                     _resp(200, '{"status":"done"}')]
        real = fake

        def multi_poll(method, url, headers, body, timeout):
            if method == "GET" and "/v1/alignments/" in url and "/exports" not in url:
                return responses.pop(0) if len(responses) > 1 else responses[0]
            return real(method, url, headers, body, timeout)

        outcome = align_lyrics(_tmp_audio(), "歌词", "ltk_ok", fetch=multi_poll,
                               poll_interval=0)
        self.assertEqual(outcome.lrc, LRC_OK)
        self.assertEqual(outcome.error_code, "")

    def test_progress_callback(self):
        stages = []
        fake = _FakeHttp()
        align_lyrics(_tmp_audio(), "歌词", "ltk_ok", fetch=fake, poll_interval=0,
                     progress=lambda p, s: stages.append((p, s)))
        self.assertTrue(stages)
        self.assertEqual(stages[-1][0], 100)


class TestAlignWorker(unittest.TestCase):
    def test_done_signal(self):
        path = _tmp_audio()
        got = {}
        with mock.patch("app.lyrics_align.align_lyrics",
                        return_value=AlignOutcome(lrc=LRC_OK)):
            worker = LyricsAlignWorker("tid1", path, "歌词", "ltk_ok")
            worker.done.connect(lambda tid, lrc: got.update(tid=tid, lrc=lrc))
            worker.run()
        self.assertEqual(got["tid"], "tid1")
        self.assertEqual(got["lrc"], LRC_OK)

    def test_failed_signal_maps_error(self):
        worker = LyricsAlignWorker("tid1", "/x.mp3", "歌词", "ltk_ok")
        got = {}
        worker.failed.connect(lambda tid, msg: got.update(tid=tid, msg=msg))
        # 没文件 → no_audio
        worker.run()
        self.assertEqual(got["tid"], "tid1")
        self.assertIn("不存在", got["msg"])

    def test_soft_fail_signal(self):
        worker = LyricsAlignWorker("tid1", "/x.mp3", "歌词", "ltk_ok")
        got = {}
        with mock.patch("app.lyrics_align.align_lyrics",
                        return_value=AlignOutcome(lrc=LRC_OK, soft_fail=True)):
            worker.soft_fail.connect(lambda tid, lrc: got.update(tid=tid, lrc=lrc))
            worker.run()
        self.assertEqual(got["lrc"], LRC_OK)


class TestSidecarLrc(unittest.TestCase):
    def test_path_strips_extension(self):
        self.assertEqual(sidecar_lrc_path("/music/晴天.mp3"), "/music/晴天.lrc")
        self.assertEqual(sidecar_lrc_path("/music/晴天.flac"), "/music/晴天.lrc")

    def test_write_creates_file(self):
        audio = _tmp_audio()
        try:
            path = write_sidecar_lrc(audio, LRC_OK)
            self.assertEqual(path, sidecar_lrc_path(audio))
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), LRC_OK)
        finally:
            os.remove(sidecar_lrc_path(audio))
            os.remove(audio)

    def test_write_overwrites_existing(self):
        audio = _tmp_audio()
        sidecar = sidecar_lrc_path(audio)
        try:
            with open(sidecar, "w", encoding="utf-8") as f:
                f.write("旧内容")
            write_sidecar_lrc(audio, LRC_OK)
            with open(sidecar, encoding="utf-8") as f:
                self.assertEqual(f.read(), LRC_OK)
        finally:
            os.remove(sidecar)
            os.remove(audio)

    def test_write_failure_returns_none(self):
        audio = _tmp_audio()
        try:
            with mock.patch("app.lyrics_align.open", side_effect=OSError("readonly")):
                self.assertIsNone(write_sidecar_lrc(audio, LRC_OK))
        finally:
            os.remove(audio)

    def test_write_empty_returns_none(self):
        self.assertIsNone(write_sidecar_lrc("", LRC_OK))
        self.assertIsNone(write_sidecar_lrc(_tmp_audio(), ""))


class TestSettingsKeyPersist(unittest.TestCase):
    def test_roundtrip(self):
        s = Settings(lyrics_align_api_key="ltk_secret")
        data = json.loads(json.dumps(s.to_dict()))
        self.assertEqual(data["lyrics_align_api_key"], "ltk_secret")
        s2 = Settings.from_dict(data)
        self.assertEqual(s2.lyrics_align_api_key, "ltk_secret")

    def test_default_empty(self):
        self.assertEqual(Settings().lyrics_align_api_key, "")


if __name__ == "__main__":
    unittest.main()
