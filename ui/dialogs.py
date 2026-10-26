# -*- coding: utf-8 -*-
"""对话框：导入进度。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)



class ImportProgressDialog(QDialog):
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入音乐")
        self.setMinimumWidth(420)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self._done = 0
        self._total = 0
        self._current_name = ""
        self._finished = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(10)

        self.title_label = QLabel("正在扫描音乐文件…")
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        root.addWidget(self.title_label)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        root.addWidget(self.bar)

        self.detail = QLabel("")
        self.detail.setObjectName("Dim")
        self.detail.setWordWrap(False)
        root.addWidget(self.detail)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("Ghost")
        self.cancel_btn.clicked.connect(self._on_button)
        btn_row.addWidget(self.cancel_btn)
        root.addLayout(btn_row)

    def update_progress(self, done: int, total: int) -> None:
        self._done = done
        self._total = total
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        self._refresh_detail()

    def set_current_file(self, path: str) -> None:
        self._current_name = os.path.basename(path) if path else ""
        self._refresh_detail()

    def _refresh_detail(self) -> None:
        text = f"已读取 {self._done}/{self._total} 个文件"
        if self._current_name:
            text += f" · {self._current_name}"
        self.detail.setText(text)

    def _on_button(self) -> None:
        """扫描中点「取消」= 取消导入；完成后点「关闭」= 直接关闭弹窗。

        完成后 worker 已结束，cancelled 信号不会再发出；若仍走 cancel 链路，
        弹窗将无法关闭（历史 bug）。故完成后改为直接 accept 关闭。
        """
        if self._finished:
            self.accept()
        else:
            self.cancelled.emit()

    def finish(self, added: int, total: int) -> None:
        self.title_label.setText("导入完成")
        self.detail.setText(f"共处理 {total} 个文件，资料库新增 {added} 首")
        self.cancel_btn.setText("关闭")
        self._finished = True
        self.bar.setValue(self.bar.maximum())

    def reject(self) -> None:  #  ESC 关闭 = 取消导入
        self.cancelled.emit()
        super().reject()
