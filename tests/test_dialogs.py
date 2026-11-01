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


def dlg_cancelled_text() -> str:
    """中断提示文案从真相源取，别在测试里写死中文。"""
    from app.lyrics_asr import describe_error

    return describe_error("cancelled")


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
    finished = Signal()          # QThread 也有这个，对话框靠它回收已退场的线程

    started_ids: list[str] = []
    auto: str = "done"          # done / fail

    def __init__(self, track_id, audio_path, lines, model_name, parent=None,
                 language="auto", quality="balanced"):
        super().__init__(parent)
        self._track_id = track_id
        _FakeWorker.started_ids.append(track_id)
        self._parent = parent
        self.interrupted = False

    def start(self):
        from app.lyrics_asr import AlignOutcome

        if _FakeWorker.auto == "done":
            outcome = AlignOutcome(lines=[], matched_ratio=0.9)
            self.done.emit(self._track_id, outcome)
        else:
            self.failed.emit(self._track_id, "识别不出人声")

    def isRunning(self):  # noqa: N802
        return False

    def requestInterruption(self):  # noqa: N802
        self.interrupted = True

    def wait(self, _ms=0):  # noqa: N802
        return True


class _RunningWorker(_FakeWorker):
    """一直「在跑」的假线程：模拟长歌推理时用户点停止/关闭（v3.0.2 的现场）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = True

    def start(self):
        pass                    # 不自动完成，就是「卡在推理中」

    def isRunning(self):  # noqa: N802
        return self.running

    def wait(self, _ms=0):  # noqa: N802
        self.running = False
        return True


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

    def test_stop_requests_worker_interruption(self):
        """v3.0.2 核心：停止必须真的通知 worker，而不是只翻一个标志位。

        v3.0.0 的 `_on_stop` 只把按钮置灰，worker 该跑多久还跑多久 —— 用户看到的是
        「点了没反应」，再加上关闭被挡住，窗口就彻底锁死了。
        """
        from app.lyrics import LyricLine

        d = self._make([("t1", "歌一", "/a.mp3")], lambda tid: [LyricLine(0, "一句")])
        worker = _RunningWorker("t1", "/a.mp3", [LyricLine(0, "一句")], "base")
        d._worker = worker
        d._on_stop()
        self.assertTrue(worker.interrupted, "停止必须调 requestInterruption")
        self.assertFalse(d.stop_btn.isEnabled(), "停过一次的按钮置灰，避免重复点")
        self.assertIn("中止", d.stage_label.text())

    def test_close_while_running_always_leaves_a_way_out(self):
        """跑着时点关闭：挡一下是对的（带活线程析构会崩），但必须同时中止 + 自动关。"""
        from app.lyrics import LyricLine

        d = self._make([("t1", "歌一", "/a.mp3"), ("t2", "歌二", "/b.mp3")],
                       lambda tid: [LyricLine(0, "一句")])
        worker = _RunningWorker("t1", "/a.mp3", [LyricLine(0, "一句")], "base")
        d._worker = worker

        event = QCloseEvent()
        d.closeEvent(event)
        self.assertFalse(event.isAccepted(), "活线程还在，不能立刻放行")
        self.assertTrue(worker.interrupted, "但必须发出中止请求，否则就是死局")
        self.assertTrue(d._close_when_done, "中止完成后要自动关闭")
        self.assertIn("自动关闭", d.stage_label.text())
        self.assertNotIn("先点「停止」", d.stage_label.text(),
                         "旧文案让用户去点一个已经灰掉的按钮，是做不到的指令")

    def test_auto_close_after_abort(self):
        """中止链路走完 → 对话框自动关掉，用户不用再点一次。"""
        from app.lyrics import LyricLine

        closed = []

        class _Spy(dlg_mod.AiBatchAlignDialog):
            def close(self):
                closed.append(1)
                return super().close()

        d = _Spy([("t1", "歌一", "/a.mp3"), ("t2", "歌二", "/b.mp3")],
                 lambda tid: [LyricLine(0, "一句")], "base")
        worker = _RunningWorker("t1", "/a.mp3", [LyricLine(0, "一句")], "base")
        d._worker = worker
        d._close_when_done = True
        d._stop = True
        d._on_failed("t1", dlg_cancelled_text())
        self.assertEqual(closed, [1], "中止完成必须自动关闭")
        self.assertIsNone(d._worker)

    def test_close_click_stops_queue_from_advancing(self):
        """点关闭后，当前这首中止完**不许再起下一首**（v3.0.2 真机跑出来的 bug）。

        `_on_close_clicked` 起初只设了 `_close_when_done`，忘了设 `_stop`，
        于是中止完当前这首 `_on_failed` 照常 `_start_next`，队列一路跑到底，
        窗口永远关不掉。
        """
        from app.lyrics import LyricLine

        items = [("t1", "歌一", "/a.mp3"), ("t2", "歌二", "/b.mp3")]
        d = self._make(items, lambda tid: [LyricLine(0, "一句")])
        worker = _RunningWorker("t1", "/a.mp3", [LyricLine(0, "一句")], "base")
        d._worker = worker
        d._on_close_clicked()
        self.assertTrue(d._stop, "点关闭就等于停止整个队列")
        d._on_failed("t1", dlg_cancelled_text())
        self.assertEqual(_FakeWorker.started_ids, ["t1"],
                         "已经点了关闭，不该再起第二首（只应有手工创建的那一个）")

    def test_cancelled_track_not_counted_as_failure(self):
        from app.lyrics import LyricLine

        d = self._make([("t1", "歌一", "/a.mp3")], lambda tid: [LyricLine(0, "一句")])
        d._stop = True
        d._on_failed("t1", dlg_cancelled_text())
        self.assertEqual(d._failed, [], "用户主动停的不算失败")
        self.assertIn("已停止", d.list.item(0).text())

    def test_progress_bar_shows_track_counts(self):
        d = self._make([("t1", "一", "/a.mp3"), ("t2", "二", "/b.mp3")],
                       lambda tid: [])
        self.assertIn("%m", d.bar.format(), "进度条是首数不是百分比，别显示 0% 误导用户")

    def test_many_skips_do_not_blow_the_stack(self):
        """全库批量可能有几千首没歌词：跳过必须用循环，不能递归。"""
        items = [(f"t{i}", f"歌{i}", f"/{i}.mp3") for i in range(3000)]
        d = self._make(items, lambda tid: [])
        d.start()
        self.assertEqual(len(d._failed), 3000)
        self.assertIn("结束", d.title_label.text())

    def test_close_when_idle_closes_directly(self):
        d = self._make([("t1", "歌一", "/a.mp3")], lambda tid: [])
        d._worker = None
        d.close()                        # 没有活线程时必须能直接关
        self.assertFalse(d._close_when_done)

    def test_close_blocked_while_running(self):
        class _RunningWorker2(_FakeWorker):
            def isRunning(self):  # noqa: N802
                return True

        d = self._make([("t1", "歌一", "/a.mp3")], lambda tid: [])
        d._worker = _RunningWorker2("t1", "/a.mp3", [], "base")
        event = QCloseEvent()
        d.closeEvent(event)
        self.assertFalse(event.isAccepted(), "跑着的时候关闭必须被忽略")
        self.assertTrue(d._worker.interrupted)


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


class TestLyricsEffectNaming(unittest.TestCase):
    """歌词动效的界面文案体系（v3.0.9）。

    为什么文案值得单测：它改错了不会报错，只会让用户**选错效果**。这里钉住四件事——
    值全覆盖、名字唯一、不与「歌词颜色覆盖」分区重名、文案只有一处定义。
    """

    def test_options_cover_all_effect_values_in_order(self):
        from app.models import LYRICS_EFFECTS
        got = [value for _label, value in dlg_mod_settings.LYRICS_EFFECT_OPTIONS]
        self.assertEqual(
            got, list(LYRICS_EFFECTS),
            "下拉项必须与 LYRICS_EFFECTS 一一对应且顺序一致，否则某个效果在界面上选不到")

    def test_labels_are_unique(self):
        labels = [label for label, _v in dlg_mod_settings.LYRICS_EFFECT_OPTIONS]
        self.assertEqual(len(labels), len(set(labels)), "动效文案不能重复")

    def test_no_label_reuses_color_overlay_wording(self):
        """「颜色覆盖」是 v2.9.0 那个独立分区（自定义双色渐变）的名字。

        动效里的 karaoke 曾经也叫「颜色覆盖」，两处同名会让用户以为是一件事。
        """
        for label, _value in dlg_mod_settings.LYRICS_EFFECT_OPTIONS:
            self.assertNotIn("颜色覆盖", label)

    def test_effect_label_is_the_single_source(self):
        for label, value in dlg_mod_settings.LYRICS_EFFECT_OPTIONS:
            self.assertEqual(dlg_mod_settings.effect_label(value), label)
        self.assertEqual(dlg_mod_settings.effect_label("unknown"), "unknown",
                         "未知值原样返回，别抛异常把设置页拖崩")

    def test_main_window_does_not_hardcode_effect_labels(self):
        """动效文案只能有一处定义（settings_dialog），主窗口不许再抄一份。

        事故背景：v3.0.9 之前两处各写一份文案表，只改一处就会出现
        「设置页叫 A、toast 说 B」。
        """
        import ast
        import os

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "ui", "main_window.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        known = {label for label, _v in dlg_mod_settings.LYRICS_EFFECT_OPTIONS}
        found = [n.value for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and n.value in known]
        self.assertEqual(found, [],
                         f"主窗口把动效文案写死了，应改用 effect_label()：{found}")
