# -*- coding: utf-8 -*-
"""导入进度对话框测试：固化「完成后『关闭』按钮失效」回归（v2.1.2）。"""
from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QDialog

import ui.dialogs as dlg_mod


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
        self.assertIn("资料库新增 3 首", dlg.detail.text())
