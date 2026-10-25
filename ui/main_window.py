# -*- coding: utf-8 -*-
"""主窗口：装配各界面模块，接线全部信号，管理视图/导入/快捷键/持久化。"""
from __future__ import annotations

import os

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.covers import CoverProvider
from app.lyrics import LyricLine, lyrics_from_text
from app.metadata import read_track
from app.models import PLAYLIST_LIBRARY, PLAYLIST_RECENT, Track
from app.paths import covers_dir, data_file
from app.player import PlaybackController
from app.scanner import ScannerWorker
from app.store import LibraryStore
from ui.dialogs import ImportProgressDialog
from ui.player_bar import PlayerBar
from ui.sidebar import Sidebar
from ui.theme import build_stylesheet
from ui.track_list import TrackList
from ui.now_playing import NowPlayingPage

SORT_KEYS = {
    "custom": None,
    "title": lambda t: (t.display_title.lower(), t.display_artist.lower()),
    "artist": lambda t: (t.display_artist.lower(), t.display_title.lower()),
    "album": lambda t: (t.display_album.lower(), t.display_title.lower()),
    "duration": lambda t: t.duration_ms,
    "added": lambda t: -t.added_at,
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("轻音播放器")
        self.resize(1280, 800)
        self.setMinimumSize(960, 640)
        self.setAcceptDrops(True)

        # ---- 核心对象 ----
        self.store = LibraryStore(data_file())
        self.player = PlaybackController(self.store)
        self.covers = CoverProvider(covers_dir())
        self._view_id = self.store.settings.last_view or PLAYLIST_LIBRARY
        self._sort_key = "custom" if self._is_playlist_view(self._view_id) else "added"
        self._search_text = ""
        self._displayed: list[Track] = []
        self._scanner: ScannerWorker | None = None
        self._lyrics_cache: dict[str, tuple[list[LyricLine], list[str]]] = {}

        self._build_ui()
        self._connect_signals()
        self._restore_state()

    # ---------- UI 装配 ----------

    def _build_ui(self) -> None:
        self.setStyleSheet(build_stylesheet())

        central = QWidget()
        central.setObjectName("Panel")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar()
        root.addWidget(self.sidebar)

        content_col = QVBoxLayout()
        content_col.setContentsMargins(0, 0, 0, 0)
        content_col.setSpacing(0)

        self.stack = QStackedWidget()
        self.track_list = TrackList()
        self.now_playing = NowPlayingPage()
        self.stack.addWidget(self.track_list)      # index 0
        self.stack.addWidget(self.now_playing)     # index 1
        content_col.addWidget(self.stack, 1)

        self.player_bar = PlayerBar()
        content_col.addWidget(self.player_bar)

        root.addLayout(content_col, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

    def _connect_signals(self) -> None:
        # 侧边栏
        self.sidebar.view_requested.connect(self.set_view)
        self.sidebar.create_playlist_requested.connect(self._create_playlist)
        self.sidebar.playlist_action.connect(self._playlist_action)
        self.sidebar.import_menu_requested.connect(self._show_import_menu)

        # 曲目列表
        self.track_list.track_activated.connect(self._on_track_activated)
        self.track_list.play_all_requested.connect(self._play_all)
        self.track_list.now_playing_requested.connect(lambda: self._show_page(1))
        self.track_list.sort_changed.connect(self._on_sort_changed)
        self.track_list.search_changed.connect(self._on_search_changed)
        self.track_list.context_action.connect(self._on_context_action)
        self.track_list.reordered.connect(self._on_reordered)

        # 播放器
        self.player.track_changed.connect(self._on_track_changed)
        self.player.state_changed.connect(self.player_bar.update_state)
        self.player.position_changed.connect(self._on_position)
        self.player.duration_changed.connect(self._on_duration)
        self.player.volume_changed.connect(self.player_bar.update_volume)
        self.player.mode_changed.connect(self.player_bar.set_mode)
        self.player.error.connect(lambda msg: self.statusBar().showMessage(msg, 5000))

        # 播放栏
        self.player_bar.play_clicked.connect(self.player.toggle_play)
        self.player_bar.next_clicked.connect(self.player.next)
        self.player_bar.prev_clicked.connect(self.player.previous)
        self.player_bar.seek_released.connect(lambda ms: self.player.seek(ms))
        self.player_bar.volume_changed.connect(self.player.set_volume)
        self.player_bar.mute_clicked.connect(self.player.toggle_mute)
        self.player_bar.mode_clicked.connect(self._cycle_mode)
        self.player_bar.lyrics_toggled.connect(self._on_lyrics_toggled)
        self.player_bar.cover_clicked.connect(lambda: self._show_page(1))

        # 正在播放页歌词
        self.now_playing.seek_requested.connect(lambda ms: self.player.seek(ms))

        # 快捷键
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self.player.toggle_play)
        QShortcut(QKeySequence("Ctrl+Right"), self, self.player.next)
        QShortcut(QKeySequence("Ctrl+Left"), self, self.player.previous)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, lambda: self._seek_by(5000))
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, lambda: self._seek_by(-5000))
        QShortcut(QKeySequence(Qt.Key.Key_Up), self, lambda: self._volume_by(0.05))
        QShortcut(QKeySequence(Qt.Key.Key_Down), self, lambda: self._volume_by(-0.05))
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.track_list.clear_search)

    def _restore_state(self) -> None:
        self.sidebar.refresh_playlists(self.store.user_playlists())
        self.set_view(self._view_id)
        self.player_bar.set_mode(self.player.mode)
        self.player_bar.update_volume(self.player.volume, self.player.muted)

        last_id = self.store.settings.last_track_id
        if last_id and self.store.get_track(last_id) is not None:
            self.player.play_single(last_id, autoplay=False,
                                    seek_ms=self.store.settings.last_position_ms)

    # ---------- 视图管理 ----------

    @staticmethod
    def _is_playlist_view(view_id: str) -> bool:
        return view_id not in (PLAYLIST_LIBRARY, PLAYLIST_RECENT)

    def set_view(self, view_id: str) -> None:
        self._view_id = view_id
        self._sort_key = "custom" if self._is_playlist_view(view_id) else "added"
        self._search_text = ""
        self.store.settings.last_view = view_id
        self.sidebar.set_active_view(view_id)
        self.sidebar.refresh_playlists(self.store.user_playlists())
        self.track_list.set_sort(self._sort_key)
        self.track_list.clear_search()
        self._show_page(0)
        self.refresh_list()

    def refresh_list(self) -> None:
        tracks = self.store.view_tracks(self._view_id)
        # 搜索过滤
        if self._search_text:
            needle = self._search_text.casefold()
            tracks = [t for t in tracks
                      if needle in t.display_title.casefold()
                      or needle in t.display_artist.casefold()
                      or needle in t.display_album.casefold()]
        # 排序
        key_fn = SORT_KEYS.get(self._sort_key)
        if key_fn is not None:
            tracks = sorted(tracks, key=key_fn)
        self._displayed = tracks
        current_tid = self.player.current_track.id if self.player.current_track else None
        self.track_list.set_header(self.store.view_name(self._view_id), len(tracks))
        self.track_list.set_tracks(tracks, lambda t: self.covers.get_pixmap(t, 40, 6), current_tid)
        in_playlist = self._is_playlist_view(self._view_id)
        self.track_list.set_context_config(in_playlist, in_playlist and self._sort_key == "custom")

    def _show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.track_list.set_now_playing_active(index == 1)
        if index == 1 and self.player.current_track:
            self.now_playing.set_track(self.player.current_track, self.covers.get_pixmap(self.player.current_track, 280, 14))

    # ---------- 播放相关 ----------

    def _on_track_activated(self, tid: str, index: int) -> None:
        ids = [t.id for t in self._displayed]
        if tid in ids:
            self.player.play_tracks(ids, ids.index(tid))

    def _play_all(self) -> None:
        ids = [t.id for t in self._displayed]
        if ids:
            self.player.play_tracks(ids, 0)
            self._show_page(0)

    def _on_track_changed(self, track: Track) -> None:
        self.track_list.set_current_track(track.id)
        self.now_playing.set_track(track, self.covers.get_pixmap(track, 280, 14))
        self.player_bar.update_track(track.display_title, f"{track.display_artist} · {track.display_album}",
                                     self.covers.get_pixmap(track, 52, 8))
        self.statusBar().showMessage(f"正在播放：{track.display_title} - {track.display_artist}", 3000)
        self._load_lyrics(track)

    def _on_position(self, position_ms: int) -> None:
        duration = self.player.duration_ms or (self.player.current_track.duration_ms if self.player.current_track else 0)
        self.player_bar.update_position(position_ms, duration)
        self.now_playing.update_position(position_ms)

    def _on_duration(self, duration_ms: int) -> None:
        self.player_bar.update_duration(duration_ms)
        track = self.player.current_track
        if track is not None and not track.duration_ms:
            track.duration_ms = duration_ms
            self.refresh_list()

    def _cycle_mode(self) -> None:
        self.player.cycle_mode()

    def _on_lyrics_toggled(self, checked: bool) -> None:
        self.player_bar.set_lyrics_active(checked)
        if checked:
            self._show_page(1)
        else:
            self._show_page(0)

    def _seek_by(self, delta_ms: int) -> None:
        target = max(0, self.player.position_ms + delta_ms)
        self.player.seek(target)

    def _volume_by(self, delta: float) -> None:
        self.player.set_volume(self.player.volume + delta)

    # ---------- 歌词 ----------

    def _load_lyrics(self, track: Track) -> None:
        cached = self._lyrics_cache.get(track.id)
        if cached is None:
            cached = self._resolve_lyrics(track)
            self._lyrics_cache[track.id] = cached
        synced, plain = cached
        if synced:
            self.now_playing.set_synced(synced)
        elif plain:
            self.now_playing.set_plain(plain)
        else:
            self.now_playing.set_empty()

    def _resolve_lyrics(self, track: Track) -> tuple[list[LyricLine], list[str]]:
        # 1) 手动绑定的 .lrc
        if track.lrc_path and os.path.isfile(track.lrc_path):
            text = _read_text(track.lrc_path)
            if text:
                return lyrics_from_text(text)
        # 2) 同名 .lrc
        sidecar = os.path.splitext(track.path)[0] + ".lrc"
        if os.path.isfile(sidecar):
            text = _read_text(sidecar)
            if text:
                return lyrics_from_text(text)
        # 3) 内嵌歌词
        try:
            meta = read_track(track.path)
        except Exception:  # noqa: BLE001
            meta = None
        if meta is not None and meta.lyrics_text:
            return lyrics_from_text(meta.lyrics_text)
        return [], []

    # ---------- 歌单管理 ----------

    def _create_playlist(self) -> None:
        name, ok = QInputDialog.getText(self, "新建歌单", "歌单名称：")
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        playlist = self.store.create_playlist(name)
        self.store.save()
        self.sidebar.refresh_playlists(self.store.user_playlists())
        self.set_view(playlist.id)
        self.statusBar().showMessage(f"已创建歌单「{name}」", 3000)

    def _playlist_action(self, pid: str, action: str) -> None:
        playlist = self.store.get_playlist(pid)
        if playlist is None:
            return
        if action == "rename":
            name, ok = QInputDialog.getText(self, "重命名歌单", "新名称：", text=playlist.name)
            if ok and name.strip():
                self.store.rename_playlist(pid, name.strip())
        elif action == "delete":
            box = QMessageBox(self)
            box.setWindowTitle("删除歌单")
            box.setText(f"确定删除歌单「{playlist.name}」吗？\n（仅删除歌单，不会删除音乐文件）")
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.setDefaultButton(QMessageBox.StandardButton.No)
            if box.exec() != QMessageBox.StandardButton.Yes:
                return
            self.store.delete_playlist(pid)
            if self._view_id == pid:
                self.set_view(PLAYLIST_LIBRARY)
        self.store.save()
        self.sidebar.refresh_playlists(self.store.user_playlists())
        # 无条件刷新：重命名当前视图的歌单时，头部标题同样需要更新
        self.refresh_list()

    def _on_reordered(self, tid: str, new_index: int) -> None:
        if not self._is_playlist_view(self._view_id):
            return
        if self.store.move_in_playlist(self._view_id, tid, new_index):
            self.store.save()
            self.refresh_list()

    # ---------- 列表右键动作 ----------

    def _on_context_action(self, tid: str, action: str) -> None:
        track = self.store.get_track(tid)
        if track is None:
            return
        if action == "play":
            ids = [t.id for t in self._displayed]
            if tid in ids:
                self.player.play_tracks(ids, ids.index(tid))
        elif action == "add_to_playlist":
            self._add_to_playlist_menu(track)
        elif action == "remove_from_playlist":
            self.store.remove_from_playlist(self._view_id, tid)
            self.store.save()
            self.refresh_list()
        elif action == "move_up":
            self._move_in_playlist(tid, -1)
        elif action == "move_down":
            self._move_in_playlist(tid, +1)
        elif action == "bind_lyrics":
            self._bind_lyrics(track)
        elif action == "refresh":
            self._refresh_track(track)
        elif action == "locate":
            self._locate(track)
        elif action == "remove_from_library":
            self._remove_from_library(track)

    def _move_in_playlist(self, tid: str, delta: int) -> None:
        if not self._is_playlist_view(self._view_id):
            return
        playlist = self.store.get_playlist(self._view_id)
        if playlist is None or tid not in playlist.track_ids:
            return
        index = playlist.track_ids.index(tid)
        target = index + delta
        if target < 0 or target >= len(playlist.track_ids):
            return
        self.store.move_in_playlist(self._view_id, tid, target)
        self.store.save()
        self.refresh_list()

    def _add_to_playlist_menu(self, track: Track) -> None:
        menu = QMenu(self)
        playlists = self.store.user_playlists()
        actions = {}
        for pl in playlists:
            actions[menu.addAction(pl.name)] = pl.id
        if not playlists:
            menu.addAction("（还没有歌单，请先新建）").setEnabled(False)
        menu.addSeparator()
        new_action = menu.addAction("新建歌单…")
        chosen = menu.exec(self.cursor().pos())
        if chosen is None:
            return
        if chosen == new_action:
            self._create_playlist()
            playlists = self.store.user_playlists()
            if playlists:
                self.store.add_to_playlist(playlists[-1].id, [track.id])
                self.store.save()
                self.refresh_list()
                self.sidebar.refresh_playlists(self.store.user_playlists())
            return
        pid = actions.get(chosen)
        if pid:
            added = self.store.add_to_playlist(pid, [track.id])
            self.store.save()
            self.sidebar.refresh_playlists(self.store.user_playlists())
            name = self.store.get_playlist(pid).name
            self.statusBar().showMessage(
                f"已添加到「{name}」" if added else f"「{name}」中已存在该歌曲", 3000)

    def _bind_lyrics(self, track: Track) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择歌词文件", os.path.dirname(track.path),
                                              "歌词文件 (*.lrc);;所有文件 (*)")
        if not path:
            return
        track.lrc_path = path
        self.store.save()
        self._lyrics_cache.pop(track.id, None)
        if self.player.current_track and self.player.current_track.id == track.id:
            self._load_lyrics(track)
        self.statusBar().showMessage(f"已绑定歌词：{os.path.basename(path)}", 3000)

    def _refresh_track(self, track: Track) -> None:
        meta = read_track(track.path)
        if meta is None:
            self.statusBar().showMessage("读取失败：文件不存在或已损坏", 4000)
            return
        self.store.add_or_update(meta, track.path)
        self.store.save()
        self._lyrics_cache.pop(track.id, None)
        self.refresh_list()
        self.statusBar().showMessage(f"已重新读取「{track.display_title}」", 3000)

    def _locate(self, track: Track) -> None:
        folder = os.path.dirname(track.path)
        if os.path.isdir(folder):
            ok = QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            if not ok:
                self.statusBar().showMessage("无法打开资源管理器", 4000)
        else:
            self.statusBar().showMessage("文件所在文件夹不存在", 4000)

    def _remove_from_library(self, track: Track) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("移除出资料库")
        box.setText(f"将「{track.display_title}」移出资料库？\n（不会删除磁盘文件，但会从所有歌单中移除）")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        if self.player.current_track and self.player.current_track.id == track.id:
            self.player.stop()
        self.store.remove_track(track.id)
        self.store.save()
        self.refresh_list()
        self.sidebar.refresh_playlists(self.store.user_playlists())
        self.statusBar().showMessage("已移出资料库", 3000)

    # ---------- 导入 ----------

    def _show_import_menu(self) -> None:
        menu = QMenu(self)
        folder_action = menu.addAction("导入文件夹…")
        files_action = menu.addAction("导入文件…")
        chosen = menu.exec(self.cursor().pos())
        if chosen == folder_action:
            self._import_folders()
        elif chosen == files_action:
            self._import_files()

    def _import_folders(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择音乐文件夹")
        if folder:
            self._start_import([folder])

    def _import_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择音乐文件", "", "音频文件 (*.mp3 *.flac *.wav *.m4a *.aac *.ogg *.oga *.opus *.wma);;所有文件 (*)")
        if files:
            self._start_import(files)

    def _start_import(self, paths: list[str]) -> None:
        if self._scanner is not None and self._scanner.isRunning():
            self.statusBar().showMessage("已有导入任务在进行中", 3000)
            return
        self._import_added = 0
        dialog = ImportProgressDialog(self)
        worker = ScannerWorker(paths)
        self._scanner = worker

        def on_track(meta) -> None:
            track = self.store.add_or_update(meta, meta.path)
            if track is not None:
                self._import_added += 1

        def on_progress(done: int, total: int) -> None:
            dialog.update_progress(done, total)

        def on_scanning(path: str) -> None:
            dialog.set_current_file(path)

        def on_finished(total: int) -> None:
            self.store.save()
            dialog.finish(self._import_added, total)
            self.sidebar.refresh_playlists(self.store.user_playlists())
            self.refresh_list()
            self.statusBar().showMessage(f"导入完成，新增 {self._import_added} 首", 5000)

        def on_cancelled() -> None:
            self.store.save()
            dialog.reject()

        worker.track_ready.connect(on_track)
        worker.progress.connect(on_progress)
        worker.scanning.connect(on_scanning)
        worker.finished_ok.connect(on_finished)
        worker.cancelled.connect(on_cancelled)
        dialog.cancelled.connect(worker.cancel)
        worker.finished.connect(lambda: setattr(self, "_scanner", None))
        worker.start()
        dialog.exec()

    # ---------- 拖拽导入 ----------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(local)
        if paths:
            self._start_import(paths)

    # ---------- 排序/搜索 ----------

    def _on_sort_changed(self, key: str) -> None:
        self._sort_key = key
        self.refresh_list()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip()
        self.refresh_list()

    # ---------- 关闭 ----------

    def closeEvent(self, event) -> None:  # noqa: N802
        current = self.player.current_track
        if current is not None:
            self.store.settings.last_track_id = current.id
            self.store.settings.last_position_ms = self.player.position_ms
        self.store.settings.volume = self.player.volume
        self.store.settings.muted = self.player.muted
        self.store.settings.play_mode = self.player.mode
        if self._scanner is not None and self._scanner.isRunning():
            self._scanner.cancel()
            self._scanner.wait(3000)
        self.player.stop()
        self.store.save()
        super().closeEvent(event)


def _read_text(path: str) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except (UnicodeDecodeError, OSError):
            continue
    return ""
