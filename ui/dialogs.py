# -*- coding: utf-8 -*-
"""对话框：导入进度、数据目录迁移进度。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
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


class AiBatchAlignDialog(QDialog):
    """全库批量 AI 逐字对齐（v3.0.0）。

    设计取向：**逐首串行**，失败的记下来继续下一首，绝不因为一首失败就整体中断。
    逐首而不是并行，理由是实测：whisper-base 单进程推理已能吃满几核，并行只会互相
    抢 CPU 且内存翻倍（模型常驻约 500MB）；串行对用户更友好（进度可预测）。

    关闭行为：正在跑的时候不允许关（`closeEvent` 忽略），否则就是「带活线程析构窗口」
    那类崩溃的老坑。要停请点「停止」，它会跑完当前这首就结束，不再开始下一首。
    """

    finished_summary = Signal(int, int)      # (成功数, 失败数)

    def __init__(self, items: list[tuple[str, str, str]], resolver, model_name: str,
                 parent=None):
        """`items` = `[(track_id, 显示名, 音频绝对路径)]`；`resolver(track_id)` 取同步歌词。"""
        super().__init__(parent)
        from app.lyrics_asr import LyricsAsrWorker

        self._worker_cls = LyricsAsrWorker
        self._queue = list(items)
        self._resolver = resolver
        self._model = model_name
        self._index = 0
        self._stop = False
        self._ok = 0
        self._failed: list[tuple[str, str]] = []
        self._worker = None

        self.setWindowTitle("批量 AI 对齐歌词")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(10)

        self.title_label = QLabel(f"共 {len(self._queue)} 首，逐首处理")
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        root.addWidget(self.title_label)

        self.stage_label = QLabel("准备中…")
        self.stage_label.setObjectName("Dim")
        self.stage_label.setWordWrap(True)
        root.addWidget(self.stage_label)

        self.bar = QProgressBar()
        self.bar.setRange(0, max(1, len(self._queue)))
        self.bar.setValue(0)
        root.addWidget(self.bar)

        self.list = QListWidget()
        self.list.setMinimumHeight(180)
        root.addWidget(self.list, 1)
        for _tid, name, _path in self._queue:
            self.list.addItem(f"待处理 · {name}")

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop)
        buttons.addWidget(self.stop_btn)
        self.close_btn = QPushButton("关闭")
        self.close_btn.setObjectName("Primary")
        self.close_btn.clicked.connect(self.close)
        buttons.addWidget(self.close_btn)
        root.addLayout(buttons)

    # ---------- 流程 ----------

    def start(self) -> None:
        self._index = 0
        self._start_next()

    def _set_row(self, index: int, text: str) -> None:
        item = self.list.item(index)
        if item is not None:
            item.setText(text)

    def _start_next(self) -> None:
        if self._stop or self._index >= len(self._queue):
            self._finish()
            return
        track_id, name, path = self._queue[self._index]
        self.bar.setValue(self._index)
        self._set_row(self._index, f"进行中 · {name}")
        self.title_label.setText(f"第 {self._index + 1} / {len(self._queue)} 首：{name}")

        lines = []
        try:
            lines = self._resolver(track_id) or []
        except Exception:  # noqa: BLE001 - 单首取歌词失败不该中断整批
            lines = []
        if not lines:
            self._failed.append((name, "没有同步歌词，跳过"))
            self._set_row(self._index, f"跳过 · {name}（没有同步歌词）")
            self._index += 1
            self._start_next()
            return

        worker = self._worker_cls(track_id, path, lines, self._model, parent=self)
        worker.progress.connect(self._on_progress)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        worker.start()

    def _on_progress(self, _track_id: str, percent: int, stage: str) -> None:
        self.stage_label.setText(f"{stage}… {percent}%")

    def _on_done(self, _track_id: str, outcome) -> None:
        _tid, name, _path = self._queue[self._index]
        self._ok += 1
        self._set_row(self._index, f"完成 · {name}（匹配 {outcome.matched_ratio:.0%}）")
        self._index += 1
        self._start_next()

    def _on_failed(self, _track_id: str, message: str) -> None:
        _tid, name, _path = self._queue[self._index]
        self._failed.append((name, message))
        self._set_row(self._index, f"失败 · {name}（{message}）")
        self._index += 1
        self._start_next()

    def _on_stop(self) -> None:
        self._stop = True
        self.stop_btn.setEnabled(False)
        self.stage_label.setText("正在停止：跑完当前这首就结束…")

    def _finish(self) -> None:
        self._worker = None
        self.bar.setValue(len(self._queue))
        self.stop_btn.setEnabled(False)
        total = len(self._queue)
        text = f"结束：成功 {self._ok} 首 / 共 {total} 首"
        if self._failed:
            text += f"，失败 {len(self._failed)} 首"
        self.title_label.setText(text)
        self.stage_label.setText("可以关闭窗口了")
        self.finished_summary.emit(self._ok, len(self._failed))

    # ---------- 关闭 ----------

    def closeEvent(self, event) -> None:  # noqa: N802
        """跑着的时候不许关：带着活线程析构这个对话框就是崩溃。"""
        worker = self._worker
        if worker is not None and worker.isRunning():
            event.ignore()
            self.stage_label.setText("正在处理，先点「停止」再关闭")
            return
        super().closeEvent(event)

    def fail_summary(self) -> str:
        """失败清单（给主窗口做 toast 用，最多列 3 条）。"""
        if not self._failed:
            return ""
        head = "；".join(f"{name}：{reason}" for name, reason in self._failed[:3])
        more = f" 等 {len(self._failed)} 首" if len(self._failed) > 3 else ""
        return head + more
