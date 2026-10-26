# -*- coding: utf-8 -*-
"""视频画面层：QVideoSink -> QVideoFrame -> QPainter 自绘 + 全屏浮窗。

为什么不用原生 QVideoWidget：
- 本项目窗口是「无边框 + 半透明 + 圆角 mask」，原生视频 surface 是独立的
  平台 surface（Windows 上走 D3D/flip model），与 translucent 顶层窗口、
  圆角裁剪叠加时容易出现黑框、遮挡甚至驱动崩溃；
- 自绘路线把画面画进普通 QWidget 的绘制管线，与既有 QSS/主题完全一致，
  不引入额外图形后端；
- 自绘的画面控件是普通 QWidget，可以自由 reparent 到全屏浮窗里，
  而 QVideoWidget 做不到（它依赖平台 surface 层级）。

代价：每帧一次 YUV->RGB 转换（实测 320x240 约 0.1ms，1080p 约 3-6ms），
对本机离线播放完全够用。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtMultimedia import QVideoFrame, QVideoSink
from PySide6.QtWidgets import QVBoxLayout, QWidget


class VideoSurface(QWidget):
    """视频画面控件：黑底、等比缩放、居中。

    对外只暴露 set_frame(QVideoFrame)；由 VideoSink 回调驱动。
    帧只做「保存引用」，真正的 YUV->RGB 转换发生在 paintEvent 里，
    因此控件不可见时几乎零开销。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VideoSurface")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMinimumSize(240, 180)
        self._frame: QVideoFrame | None = None
        self._frames = 0

    # ---------- 数据 ----------

    def set_frame(self, frame: QVideoFrame) -> None:
        """接收一帧画面。"""
        self._frame = frame
        self._frames += 1
        self.update()

    def clear_frame(self) -> None:
        self._frame = None
        self.update()

    @property
    def frame_count(self) -> int:
        """已接收的帧数（测试用：证明画面链路真的在跑）。"""
        return self._frames

    # ---------- 绘制 ----------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        frame = self._frame
        if frame is not None and frame.isValid():
            options = QVideoFrame.PaintOptions()
            options.aspectRatioMode = Qt.AspectRatioMode.KeepAspectRatio
            options.backgroundColor = QColor("#000000")
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            try:
                frame.paint(painter, QRectF(self.rect()), options)
            except Exception:  # noqa: BLE001  个别帧格式不支持时退回 QImage 路径
                image = frame.toImage()
                if not image.isNull():
                    painter.drawImage(self.rect(), image)
        painter.end()


class VideoSinkHost(QWidget):
    """持有 QVideoSink 的容器：sink 生命周期必须与播放器绑定稳定存活。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VideoSinkHost")
        self.sink = QVideoSink()
        self.surface = VideoSurface(self)
        self.sink.videoFrameChanged.connect(self.surface.set_frame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.surface)

    @property
    def frames(self) -> int:
        return self.surface.frame_count


class VideoFullscreenOverlay(QWidget):
    """全屏浮窗：把画面控件临时 reparent 到这里，实现「只针对视频画面」的全屏。

    画面控件是普通 QWidget，可自由换父；播放器与 sink 全程不变，
    因此进入/退出全屏都不会中断播放与进度。
    """

    exited = Signal()

    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("轻音播放器 - 视频全屏")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setStyleSheet("background: #000000;")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._surface: VideoSurface | None = None
        self._orig_parent = None
        self._orig_layout = None
        self._orig_index = 0

    # ---------- 状态 ----------

    @property
    def active(self) -> bool:
        return self._surface is not None

    # ---------- 进入/退出 ----------

    def enter(self, surface: VideoSurface) -> None:
        """把画面控件搬进浮窗并全屏显示。"""
        if self._surface is not None:
            return
        self._surface = surface
        parent = surface.parentWidget()
        self._orig_parent = parent
        layout = parent.layout() if parent is not None else None
        self._orig_layout = layout
        self._orig_index = layout.indexOf(surface) if layout is not None else 0
        if layout is not None:
            layout.removeWidget(surface)
        surface.setParent(None)
        self._layout.addWidget(surface)
        self.showFullScreen()
        surface.show()
        surface.raise_()

    def leave(self) -> None:
        """把画面控件搬回原位置并关闭浮窗。"""
        if self._surface is None:
            return
        surface = self._surface
        self._layout.removeWidget(surface)
        surface.setParent(self._orig_parent)
        if self._orig_layout is not None:
            self._orig_layout.insertWidget(self._orig_index, surface)
        surface.show()
        self._surface = None
        self._orig_parent = None
        self._orig_layout = None
        self.hide()

    # ---------- 键盘 ----------

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F11):
            self.exited.emit()
            event.accept()
            return
        super().keyPressEvent(event)
