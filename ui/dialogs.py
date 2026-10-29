# -*- coding: utf-8 -*-
"""对话框：导入进度、数据目录迁移进度。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from app.filesize import format_size

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
        self.detail.setText(f"共处理 {total} 个文件，音乐库新增 {added} 首")
        self.cancel_btn.setText("关闭")
        self._finished = True
        self.bar.setValue(self.bar.maximum())

    def reject(self) -> None:  #  ESC 关闭 = 取消导入
        self.cancelled.emit()
        super().reject()


class StorageMoveWorker(QThread):
    """后台搬运数据目录：复制 + 逐文件核对，成功后删源。

    搬的可能是几个 GB 的曲库，必须离开 UI 线程 —— 阻塞主线程会让窗口白屏，
    Windows 还会给标题栏加「无响应」。取消走 Qt 的 interruption 标志，
    `storage.migrate` 每复制一个文件检查一次。
    """

    progress = Signal(int, int, str)     # 已复制字节, 总字节, 当前文件名
    moved = Signal(dict)                 # {"files", "bytes", "removed"}
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, dst: str, remove_source: bool = True, parent=None):
        super().__init__(parent)
        self._dst = dst
        self._remove_source = remove_source

    def run(self) -> None:
        from app import storage

        try:
            result = storage.switch_root(
                self._dst,
                remove_source=self._remove_source,
                progress=lambda done, total, name: self.progress.emit(done, total, name),
                should_stop=self.isInterruptionRequested,
            )
        except storage.Cancelled:
            self.cancelled.emit()
            return
        except storage.MigrationError as e:
            self.failed.emit(str(e))
            return
        except Exception as e:  # noqa: BLE001  兜底：线程里抛异常会静默吞掉
            self.failed.emit(f"迁移失败：{e}")
            return
        self.moved.emit(result)


class StorageMoveDialog(QDialog):
    """迁移进度弹窗。结束后 `result_info` 为迁移结果，`error` 为错误消息。"""

    def __init__(self, dst: str, remove_source: bool = True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("正在移动数据")
        self.setMinimumWidth(430)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.result_info: dict | None = None
        self.error: str | None = None
        self._finished = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(10)

        self.title_label = QLabel("正在把数据搬到新位置…")
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        root.addWidget(self.title_label)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        root.addWidget(self.bar)

        self.detail = QLabel("准备中…")
        self.detail.setObjectName("Dim")
        root.addWidget(self.detail)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("Ghost")
        self.cancel_btn.clicked.connect(self._on_button)
        btn_row.addWidget(self.cancel_btn)
        root.addLayout(btn_row)

        self.worker = StorageMoveWorker(dst, remove_source, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.moved.connect(self._on_moved)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.start()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(min(done, max(total, 1)))
        self.detail.setText(f"{format_size(done)} / {format_size(total)} · {name}")

    def _on_moved(self, result: dict) -> None:
        self.result_info = result
        self._finished = True
        self.bar.setValue(self.bar.maximum())
        self.detail.setText(f"已移动 {result.get('files', 0)} 个文件"
                            f"（{format_size(result.get('bytes', 0))}）")
        self.accept()

    def _on_failed(self, message: str) -> None:
        self.error = message
        self._finished = True
        self.title_label.setText("移动失败")
        self.detail.setText(message)
        self.cancel_btn.setText("关闭")
        self.bar.setRange(0, 1)
        self.bar.setValue(0)

    def _on_cancelled(self) -> None:
        self._finished = True
        self.title_label.setText("已取消")
        self.detail.setText("新位置已清理，原数据没有改动")
        self.cancel_btn.setText("关闭")
        self.reject()

    def _on_button(self) -> None:
        if self._finished:
            self.accept()
            return
        # 取消：置标志让 worker 在下一个文件前停下，并禁掉按钮避免连点
        self.cancel_btn.setEnabled(False)
        self.detail.setText("正在取消…")
        self.worker.requestInterruption()

    def reject(self) -> None:
        if not self._finished and self.worker.isRunning():
            self.worker.requestInterruption()
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        # 线程带 parent=self，对话框销毁时它必须已经结束，否则 Qt 会报
        # "QThread: Destroyed while thread is still running" 并直接崩。
        # 中断检查在每个文件开始前，所以最多等「当前这个文件复制完」。
        if self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait()
        super().closeEvent(event)
