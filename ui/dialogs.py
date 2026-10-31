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

    关闭行为（v3.0.2 重写）：**关闭永远有出路**。

    v3.0.0 的写法是「跑着就 ignore 掉关闭，并提示先点停止」，但「停止」点完立刻就
    灰了、worker 又不会真的中断 —— 用户被锁在一个既关不掉、也没按钮可点的窗口里。
    现在的分工是：

    - 点「停止」= 请求中止 + 留在窗口看最后结果（按钮随即置灰，避免重复点）；
    - 点「关闭」或窗口 X = 请求中止 + **中止完成后自动关闭**；
    - 只有一种情况会 ignore 关闭事件：还有活线程在跑（否则就是带活线程析构那个崩溃
      老坑），但此时一定会同时发出中止请求，所以最多等一个检查点。
    """

    finished_summary = Signal(int, int)      # (成功数, 失败数)

    # 中止文案要写真实预期：实测 whisper 出第一个识别段之前已经把整曲编码完了，
    # 那一段是 C++ 一次性调用、打不断，所以「立刻停」做不到，别骗用户。
    _ABORTING_TEXT = ("正在中止：等手上这一段算完（通常十几秒，慢的时候一两分钟），"
                      "完成后窗口会自动关闭…")

    def __init__(self, items: list[tuple[str, str, str]], resolver, model_name: str,
                 parent=None, language: str = "auto", quality: str = "balanced"):
        """`items` = `[(track_id, 显示名, 音频绝对路径)]`；`resolver(track_id)` 取同步歌词。

        `language` / `quality`（v3.0.3）：透传给 worker，决定识别语言与 beam 大小。
        """
        super().__init__(parent)
        from app.lyrics_asr import LyricsAsrWorker

        self._worker_cls = LyricsAsrWorker
        self._queue = list(items)
        self._resolver = resolver
        self._model = model_name
        self._language = language
        self._quality = quality
        self._index = 0
        self._stop = False
        self._close_when_done = False
        self._ok = 0
        self._failed: list[tuple[str, str]] = []
        self._worker = None
        self._retired: list = []      # 已发出终态信号、但线程可能还没退干净的 worker

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
        # 这根条数是「第几首」，不是当前这首的进度；显示成 0% 会让人以为卡死了
        self.bar.setFormat("%v / %m 首")
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
        self.close_btn.clicked.connect(self._on_close_clicked)
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
        # 「没有同步歌词」用循环跳过而不是递归：全库批量时可能有几千首没歌词，
        # 递归会把栈直接打爆（RecursionError），对话框当场死掉。
        while True:
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
            if lines:
                break
            self._failed.append((name, "没有同步歌词，跳过"))
            self._set_row(self._index, f"跳过 · {name}（没有同步歌词）")
            self._index += 1

        worker = self._worker_cls(track_id, path, lines, self._model,
                                  language=self._language, quality=self._quality,
                                  parent=self)
        worker.progress.connect(self._on_progress)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        worker.start()

    def _on_progress(self, _track_id: str, percent: int, stage: str) -> None:
        # 中止期间进度还在刷，别把「正在中止」的说明冲掉，否则用户又不知道发生了什么
        if self._stop or self._close_when_done:
            return
        self.stage_label.setText(f"{stage}… {percent}%")

    def _on_done(self, _track_id: str, outcome) -> None:
        _tid, name, _path = self._queue[self._index]
        self._ok += 1
        self._set_row(self._index, f"完成 · {name}（匹配 {outcome.matched_ratio:.0%}）")
        self._index += 1
        self._start_next()

    def _on_failed(self, _track_id: str, message: str) -> None:
        from app.lyrics_asr import describe_error

        _tid, name, _path = self._queue[self._index]
        if message == describe_error("cancelled"):
            # 用户主动停的，不算失败；否则汇总里会出现「失败 1 首：已取消」这种误导
            self._set_row(self._index, f"已停止 · {name}")
        else:
            self._failed.append((name, message))
            self._set_row(self._index, f"失败 · {name}（{message}）")
        self._index += 1
        self._start_next()

    def _on_stop(self) -> None:
        """停止 = 请求中止 + 留在窗口看最后结果。"""
        if self._stop:
            return
        self._stop = True
        self.stop_btn.setEnabled(False)
        if self._request_abort():
            self.stage_label.setText(self._ABORTING_TEXT)
        else:
            self.stage_label.setText("已停止")

    def _request_abort(self) -> bool:
        """给 worker 发中断请求。返回是否真有线程在跑。

        这一步是 v3.0.0 缺失的关键：`_on_stop` 原来只翻了个 `_stop` 标志位，
        worker 该跑多久还跑多久，用户以为「点了没反应」。
        """
        worker = self._worker
        if worker is None or not worker.isRunning():
            return False
        worker.requestInterruption()
        return True

    def _on_close_clicked(self) -> None:
        """关闭 = 请求中止 + 中止完成后自动关。永远给用户留一条出路。

        `self._stop = True` 这一行是必须的：少了它，当前这首中止完 `_on_failed`
        还会照常调 `_start_next` 去跑下一首，队列永远走不完、窗口永远关不掉。
        这个 bug 只有真机跑才能发现 —— 假 worker 是瞬时返回的，看不出来。
        """
        if self._request_abort():
            self._stop = True
            self._close_when_done = True
            self.stop_btn.setEnabled(False)
            self.close_btn.setEnabled(False)
            self.stage_label.setText(self._ABORTING_TEXT)
            return
        self.close()

    def _finish(self) -> None:
        self._retire()
        self.bar.setValue(len(self._queue))
        self.stop_btn.setEnabled(False)
        total = len(self._queue)
        text = f"结束：成功 {self._ok} 首 / 共 {total} 首"
        if self._failed:
            text += f"，失败 {len(self._failed)} 首"
        self.title_label.setText(text)
        self.stage_label.setText(
            "可以关闭窗口了" if not self._alive_workers() else self._ABORTING_TEXT)
        self.finished_summary.emit(self._ok, len(self._failed))
        self._maybe_close()

    # ---------- 线程回收 ----------

    def _retire(self) -> None:
        """把当前 worker 退场：请求中断，然后交给 `finished` 回收。

        **不要在这里 `wait()` 等**：实测中止本身要等 60~90 秒（whisper 的第一段
        之前已经把整曲编码完了，那一段是 C++ 一次性调用，打不断）。在 UI 线程里
        wait 只会白卡住界面，而且卡 3 秒超时后 worker 还在跑，`close()` 又会被
        `closeEvent` 挡回来 —— 反而把死路推迟了 3 秒。

        所以：这里只 `wait(0)` 回收已经退出的，其余等 `finished`（跨线程自动排队到
        主线程）来收，收完由 `_on_worker_finished` 决定要不要真正关闭窗口。
        """
        worker, self._worker = self._worker, None
        if worker is None:
            return
        worker.requestInterruption()
        if worker.wait(0):
            return
        self._retired.append(worker)
        worker.finished.connect(self._on_worker_finished)

    def _on_worker_finished(self) -> None:
        """worker 真退出后在主线程收到：清理 + 该关就关。"""
        self._retired = [w for w in self._retired if w.isRunning()]
        self._maybe_close()

    def _alive_workers(self) -> list:
        workers = list(self._retired)
        if self._worker is not None:
            workers.append(self._worker)
        return [w for w in workers if w.isRunning()]

    def _maybe_close(self) -> None:
        """用户点过关、且已经没有任何活线程 → 真正关闭。"""
        if self._close_when_done and not self._alive_workers():
            self._close_when_done = False
            self.close()

    # ---------- 关闭 ----------

    def closeEvent(self, event) -> None:  # noqa: N802
        """还有活线程时挡一下（带活线程析构会崩），但**同时发中止请求**。

        v3.0.0 这里只 ignore + 提示「先点停止」，而停止按钮那时已经灰了 ——
        提示的是一条做不到的指令，窗口就锁死了。
        """
        if self._alive_workers():
            event.ignore()
            self._stop = True
            self._close_when_done = True
            for worker in self._alive_workers():
                worker.requestInterruption()
            self.stop_btn.setEnabled(False)
            self.close_btn.setEnabled(False)
            self.stage_label.setText(self._ABORTING_TEXT)
            return
        super().closeEvent(event)

    def fail_summary(self) -> str:
        """失败清单（给主窗口做 toast 用，最多列 3 条）。"""
        if not self._failed:
            return ""
        head = "；".join(f"{name}：{reason}" for name, reason in self._failed[:3])
        more = f" 等 {len(self._failed)} 首" if len(self._failed) > 3 else ""
        return head + more
