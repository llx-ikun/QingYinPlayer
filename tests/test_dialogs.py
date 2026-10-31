# -*- coding: utf-8 -*-
"""导入进度对话框测试：固化「完成后『关闭』按钮失效」回归（v2.1.2）。"""
from __future__ import annotations

import unittest

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QDialog

import ui.dialogs as dlg_mod
import ui.settings_dialog as dlg_mod_settings


def setUpModule() -> None:
    if QApplication.instance() is None:
        QApplication([])


class TestImportDialog(unittest.TestCase):
    def test_close_after_finish_closes_dialog(self) -> None:
        dlg = dlg_mod.ImportProgressDialog()
        dlg.finish(1, 1)
        # 完成后点击「关闭」按钮：应直接 accept 关闭，
        # 而非走已结束 worker 的 cancel 链路（历史 bug：弹窗关不掉）
        dlg.cancel_btn.click()
        self.assertEqual(dlg.result(), QDialog.Accepted)

    def test_cancel_before_finish_emits_cancelled(self) -> None:
        dlg = dlg_mod.ImportProgressDialog()
        fired = []
        dlg.cancelled.connect(lambda: fired.append(1))
        # 扫描中点「取消」：必须发出 cancelled，由主窗口接管取消 worker
        dlg.cancel_btn.click()
        self.assertEqual(fired, [1])

    def test_finish_sets_state(self) -> None:
        dlg = dlg_mod.ImportProgressDialog()
        dlg.finish(3, 3)
        self.assertTrue(dlg._finished)
        self.assertEqual(dlg.cancel_btn.text(), "关闭")
        self.assertIn("音乐库新增 3 首", dlg.detail.text())


class _FakeWorker(QObject):
    """假的单曲对齐线程：只回放预设信号，不碰模型也不碰音频。"""

    done = Signal(str, object)
    failed = Signal(str, str)
    progress = Signal(int, str)

    started_ids: list[str] = []
    auto: str = "done"          # done / fail

    def __init__(self, track_id, audio_path, lines, model_name, parent=None):
        super().__init__(parent)
        self._track_id = track_id
        _FakeWorker.started_ids.append(track_id)
        self._parent = parent

    def start(self):
        from app.lyrics_asr import AlignOutcome

        if _FakeWorker.auto == "done":
            outcome = AlignOutcome(lines=[], matched_ratio=0.9)
            self.done.emit(self._track_id, outcome)
        else:
            self.failed.emit(self._track_id, "识别不出人声")

    def isRunning(self):  # noqa: N802
        return False


class TestAiBatchAlignDialog(unittest.TestCase):
    """批量对齐对话框（v3.0.0）：逐首跑、失败不中断、没有行时间轴就跳过。"""

    def setUp(self):
        self.dialog = None

    def _make(self, items, resolver, auto="done"):
        _FakeWorker.auto = auto
        _FakeWorker.started_ids = []
        d = dlg_mod.AiBatchAlignDialog(items, resolver, "base")
        d._worker_cls = _FakeWorker      # 注入假线程，避开真实推理
        self.dialog = d
        return d

    def test_skip_when_no_synced_lyrics(self):
        d = self._make([("t1", "歌一", "/a.mp3"), ("t2", "歌二", "/b.mp3")],
                       lambda tid: [])
        summary = []
        d.finished_summary.connect(lambda ok, bad: summary.append((ok, bad)))
        d.start()
        self.assertEqual(summary, [(0, 2)], "两首都没歌词 → 全跳过，成功 0 失败 2")
        self.assertIn("跳过", d.list.item(0).text())
        self.assertEqual(_FakeWorker.started_ids, [], "没歌词就不该起线程")

    def test_successful_tracks_counted(self):
        from app.lyrics import LyricLine

        d = self._make([("t1", "歌一", "/a.mp3")], lambda tid: [LyricLine(0, "一句")])
        summary = []
        d.finished_summary.connect(lambda ok, bad: summary.append((ok, bad)))
        d.start()
        self.assertEqual(summary, [(1, 0)])
        self.assertIn("完成", d.list.item(0).text())
        self.assertIn("90%", d.list.item(0).text(), "完成行要带匹配率")

    def test_failure_does_not_stop_batch(self):
        items = [("t1", "歌一", "/a.mp3"), ("t2", "歌二", "/b.mp3")]
        from app.lyrics import LyricLine

        d = self._make(items, lambda tid: [LyricLine(0, "一句")], auto="fail")
        d.finished_summary.connect(lambda ok, bad: None)
        d.start()
        self.assertEqual(_FakeWorker.started_ids, ["t1", "t2"],
                         "第一首失败后必须继续跑第二首")
        self.assertEqual(len(d._failed), 2)
        self.assertIn("识别不出人声", d.fail_summary())

    def test_resolver_exception_treated_as_skip(self):
        def boom(_tid):
            raise RuntimeError("读歌词炸了")

        d = self._make([("t1", "歌一", "/a.mp3")], boom)
        d.start()
        self.assertIn("跳过", d.list.item(0).text(), "单首取歌词失败不该中断整批")

    def test_stop_prevents_next_track(self):
        from app.lyrics import LyricLine

        items = [("t1", "歌一", "/a.mp3"), ("t2", "歌二", "/b.mp3")]
        d = self._make(items, lambda tid: [LyricLine(0, "一句")])
        d._stop = True
        d.start()
        self.assertEqual(_FakeWorker.started_ids, [], "已停止就不再起线程")
        self.assertIn("结束", d.title_label.text())

    def test_close_blocked_while_running(self):
        class _RunningWorker(_FakeWorker):
            def isRunning(self):  # noqa: N802
                return True

        d = self._make([("t1", "歌一", "/a.mp3")], lambda tid: [])
        d._worker = _RunningWorker("t1", "/a.mp3", [], "base")
        event = QCloseEvent()
        d.closeEvent(event)
        self.assertFalse(event.isAccepted(), "跑着的时候关闭必须被忽略")
        self.assertIn("停止", d.stage_label.text())


class TestAiSettings(unittest.TestCase):
    """设置页 AI 区块（v3.0.0）：档位切换要能发出去，默认 base。"""

    def _dialog(self, ai_model="base"):
        return dlg_mod_settings.SettingsDialog(
            "light", "昵称", {}, None, ai_model=ai_model)

    def test_default_model_is_base(self):
        from app.models import DEFAULT_AI_MODEL

        self.assertEqual(DEFAULT_AI_MODEL, "base")

    def test_combo_has_all_tiers_and_emits(self):
        d = self._dialog()
        got = []
        d.ai_model_changed.connect(got.append)
        combo = d.ai_model_combo
        self.assertEqual(combo.count(), 3)
        combo.setCurrentIndex(combo.findData("small"))
        self.assertEqual(got, ["small"])

    def test_unknown_model_falls_back_to_default(self):
        d = self._dialog(ai_model="gigantic")
        self.assertEqual(d.ai_model_combo.currentData(), "base")
