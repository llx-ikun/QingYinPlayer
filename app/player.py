# -*- coding: utf-8 -*-
"""播放控制器：QMediaPlayer + QAudioOutput 封装 + 队列调度。

UI 层只跟本类的信号/方法交互，不直接碰 QMediaPlayer。
音量/模式变更会写回 store.settings（由调用方决定何时落盘）。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from app.models import (
    MODE_LOOP,
    MODE_SEQUENTIAL,
    MODE_SINGLE,
    MODE_SHUFFLE,
    PLAY_MODES,
    Track,
)
from app.queue import PlayQueue

# 「上一首」在播放超过该毫秒数时先回到本曲开头
RESTART_THRESHOLD_MS = 3000


class PlaybackController(QObject):
    state_changed = Signal(str)            # playing / paused / stopped
    position_changed = Signal(int)         # ms
    duration_changed = Signal(int)         # ms（加载完成后）
    track_changed = Signal(object)         # Track
    mode_changed = Signal(str)
    volume_changed = Signal(float, bool)   # volume, muted
    error = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self._store = store
        self._player = QMediaPlayer()
        self._audio = QAudioOutput()
        self._player.setAudioOutput(self._audio)

        self._queue = PlayQueue(mode=store.settings.play_mode)
        self._current: Track | None = None
        self._pending_seek_ms: int | None = None

        self._player.playbackStateChanged.connect(self._on_state)
        self._player.positionChanged.connect(self._on_position)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)

        self._apply_volume()

    # ---------- 属性 ----------

    @property
    def current_track(self) -> Track | None:
        return self._current

    @property
    def mode(self) -> str:
        return self._queue.mode

    @property
    def volume(self) -> float:
        return self._store.settings.volume

    @property
    def muted(self) -> bool:
        return self._store.settings.muted

    @property
    def position_ms(self) -> int:
        return self._player.position()

    @property
    def duration_ms(self) -> int:
        return self._player.duration()

    # ---------- 播放控制 ----------

    def play_tracks(self, track_ids: list[str], start_index: int = 0, autoplay: bool = True) -> None:
        """设置队列并从指定位置开始播放（双击列表/切换歌单时调用）。"""
        ids = [tid for tid in track_ids if self._store.get_track(tid) is not None]
        if not ids:
            return
        start_index = max(0, min(start_index, len(ids) - 1))
        self._queue.set_ids(ids, start_index)
        self._load_current(autoplay=autoplay)

    def play_single(self, track_id: str, autoplay: bool = True, seek_ms: int | None = None) -> None:
        """单曲播放（用于恢复上次播放状态）。"""
        track = self._store.get_track(track_id)
        if track is None:
            return
        self._queue.set_ids([track_id], 0)
        self._load_current(autoplay=autoplay, seek_ms=seek_ms)

    def toggle_play(self) -> None:
        if self._current is None:
            return
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def pause(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()

    def resume(self) -> None:
        if self._current is not None and self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._player.play()

    def stop(self) -> None:
        self._player.stop()

    def next(self) -> None:
        nxt = self._queue.next(auto=False)
        if nxt is None:
            self.stop()
            return
        self._load_current(autoplay=True)

    def previous(self) -> None:
        if self._current is None:
            return
        if self._player.position() > RESTART_THRESHOLD_MS:
            self.seek(0)
            return
        prev = self._queue.previous()
        if prev is None or prev == self._current.id:
            self.seek(0)
            return
        self._load_current(autoplay=True)

    def seek(self, position_ms: int) -> None:
        if self._current is None:
            return
        position_ms = max(0, position_ms)
        self._player.setPosition(position_ms)
        self.position_changed.emit(position_ms)

    def set_volume(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        self._store.settings.volume = value
        if value > 0 and self._store.settings.muted:
            self._store.settings.muted = False
        self._apply_volume()
        self.volume_changed.emit(self._store.settings.volume, self._store.settings.muted)

    def toggle_mute(self) -> None:
        self._store.settings.muted = not self._store.settings.muted
        self._apply_volume()
        self.volume_changed.emit(self._store.settings.volume, self._store.settings.muted)

    def set_mode(self, mode: str) -> None:
        if mode not in PLAY_MODES or mode == self._queue.mode:
            return
        self._queue.set_mode(mode)
        self._store.settings.play_mode = mode
        self.mode_changed.emit(mode)

    def cycle_mode(self) -> str:
        order = [MODE_LOOP, MODE_SEQUENTIAL, MODE_SINGLE, MODE_SHUFFLE]
        try:
            idx = order.index(self._queue.mode)
        except ValueError:
            idx = 0
        self.set_mode(order[(idx + 1) % len(order)])
        return self._queue.mode

    # ---------- 内部 ----------

    def _apply_volume(self) -> None:
        s = self._store.settings
        self._audio.setVolume(0.0 if s.muted else max(0.0, min(1.0, s.volume)))

    def _load_current(self, autoplay: bool = True, seek_ms: int | None = None) -> None:
        tid = self._queue.current
        track = self._store.get_track(tid) if tid else None
        if track is None or not _file_exists(track.path):
            if track is not None:
                self._store.set_broken(track.id, True)
                self.error.emit(f"文件不存在，已跳过：{track.display_title}")
            self._current = None
            self._player.stop()
            # 自动尝试下一首（最多绕一圈，避免死循环）
            if autoplay:
                nxt = self._queue.next(auto=True)
                if nxt is not None and nxt != tid:
                    self._load_current(autoplay=True)
            return

        self._current = track
        self._pending_seek_ms = seek_ms
        self._store.set_broken(track.id, False)
        self._store.touch_played(track.id)
        self._player.setSource(QUrl.fromLocalFile(track.path))
        self.track_changed.emit(track)
        if autoplay:
            self._player.play()

    # ---------- QMediaPlayer 信号槽 ----------

    def _on_state(self, state) -> None:
        name = {
            QMediaPlayer.PlaybackState.PlayingState: "playing",
            QMediaPlayer.PlaybackState.PausedState: "paused",
            QMediaPlayer.PlaybackState.StoppedState: "stopped",
        }.get(state, "stopped")
        self.state_changed.emit(name)

    def _on_position(self, position_ms: int) -> None:
        self.position_changed.emit(position_ms)

    def _on_media_status(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            duration = self._player.duration()
            if duration > 0:
                self.duration_changed.emit(duration)
            if self._pending_seek_ms is not None:
                seek = self._pending_seek_ms
                self._pending_seek_ms = None
                if seek > 0:
                    self._player.setPosition(seek)
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._handle_finished()

    def _handle_finished(self) -> None:
        if self._queue.mode == MODE_SINGLE:
            self._player.setPosition(0)
            self._player.play()
            return
        nxt = self._queue.next(auto=True)
        if nxt is None:
            self.stop()
            return
        self._load_current(autoplay=True)

    def _on_error(self, error, message: str) -> None:
        if self._current is not None:
            self._store.set_broken(self._current.id, True)
            self.error.emit(f"无法播放「{self._current.display_title}」：{message or '未知错误'}")
            tid = self._current.id
            nxt = self._queue.next(auto=True)
            if nxt is not None and nxt != tid:
                self._load_current(autoplay=True)


def _file_exists(path: str) -> bool:
    import os
    return bool(path) and os.path.isfile(path)
