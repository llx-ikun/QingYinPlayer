# -*- coding: utf-8 -*-
"""主窗口：无边框圆角壳 + 通栏标题栏 + 侧边栏/列表/正在播放/播放栏装配。

v2.0 变更：
- FramelessWindowHint + WA_TranslucentBackground，圆角由 mask 硬裁剪；
- 边缘缩放（应用级事件过滤，命中 6px 热区即进入 resize 态）；
- 标题栏提供视图前进/后退/刷新/全局搜索；搜索过滤当前视图；
- toast 取代状态栏做瞬时提示；
- 主题在启动时按 settings.theme 应用，切换即时生效；
- 「我喜欢」：行内心 / 播放栏心 -> store.toggle_favorite。
"""
from __future__ import annotations

import os

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QRectF,
    QTimer,
    QUrl,
    Qt,
)
from PySide6.QtGui import QDesktopServices, QKeySequence, QPainterPath, QRegion, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.covers import CoverProvider
from app.lyrics import LyricLine, lyrics_from_text
from app.metadata import read_track
from app.models import PLAYLIST_FAVORITES, PLAYLIST_LIBRARY, PLAYLIST_RECENT, Track
from app.paths import covers_dir, data_file
from app.player import PlaybackController
from app.scanner import ScannerWorker
from app.store import LibraryStore
from ui import theme as ui_theme
from ui.dialogs import ImportProgressDialog
from ui.float_bar import FloatBar
from ui.player_bar import PlayerBar
from ui.settings_dialog import SettingsDialog, stats_for
from ui.sidebar import Sidebar
from ui.title_bar import TitleBar
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

# 边缘缩放热区（像素）与方向位
_RESIZE_MARGIN = 6
_EDGE_LEFT, _EDGE_RIGHT, _EDGE_TOP, _EDGE_BOTTOM = 1, 2, 4, 8
_CORNER_RADIUS = 10


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("轻音播放器")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(1280, 800)
        self.setMinimumSize(1100, 720)
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
        # 视图历史：初始视图即历史第 0 项——否则从初始视图导航后
        # 「后退」永远回不到起点（set_view 同视图不记录，restore 路径
        # 不会把初始视图补进历史）
        self._history: list[str] = [self._view_id]
        self._history_pos = 0
        self._resize_edge = 0
        self._resizing = False
        self._resize_start_geo: QRect | None = None
        self._resize_start_pos: QPoint | None = None

        self._build_ui()
        self._connect_signals()
        ui_theme.apply_theme(QApplication.instance() or self, self.store.settings.theme)
        self._restore_state()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    # ---------- UI 装配 ----------

    def _build_ui(self) -> None:
        self._root = QWidget()
        self._root.setObjectName("WindowRoot")
        self._root.setMouseTracking(True)
        self.setCentralWidget(self._root)

        outer = QVBoxLayout(self._root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.title_bar = TitleBar()
        outer.addWidget(self.title_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = Sidebar()
        body.addWidget(self.sidebar)

        content_col = QVBoxLayout()
        content_col.setContentsMargins(0, 0, 0, 0)
        content_col.setSpacing(0)

        self.stack = QStackedWidget()
        self.track_list = TrackList()
        self.now_playing = NowPlayingPage()
        self.stack.addWidget(self.track_list)      # index 0
        self.stack.addWidget(self.now_playing)     # index 1
        content_col.addWidget(self.stack, 1)

        body.addLayout(content_col, 1)
        outer.addLayout(body, 1)

        self.player_bar = PlayerBar()
        outer.addWidget(self.player_bar)

        # 浮动工具条（覆盖播放栏左上角）
        self.float_bar = FloatBar(self._root)
        self.float_bar.raise_()

        # toast（瞬时提示，替代状态栏）
        self._toast_label = QLabel(self._root)
        self._toast_label.setObjectName("Toast")
        self._toast_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._toast_label.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._toast_label.hide)

    def _connect_signals(self) -> None:
        # 标题栏
        self.title_bar.back_clicked.connect(self.go_back)
        self.title_bar.forward_clicked.connect(self.go_forward)
        self.title_bar.refresh_clicked.connect(self.refresh_list)
        self.title_bar.search_changed.connect(self._on_search_changed)
        self.title_bar.minimize_clicked.connect(self.showMinimized)
        self.title_bar.maximize_clicked.connect(self._toggle_maximized)
        self.title_bar.close_clicked.connect(self.close)

        # 侧边栏
        self.sidebar.view_requested.connect(self.set_view)
        self.sidebar.create_playlist_requested.connect(self._create_playlist)
        self.sidebar.playlist_action.connect(self._playlist_action)
        self.sidebar.import_menu_requested.connect(self._show_import_menu)
        self.sidebar.nickname_change_requested.connect(self._change_nickname)

        # 曲目列表
        self.track_list.track_activated.connect(self._on_track_activated)
        self.track_list.play_all_requested.connect(self._play_all)
        self.track_list.now_playing_requested.connect(lambda: self._show_page(1))
        self.track_list.sort_changed.connect(self._on_sort_changed)
        self.track_list.context_action.connect(self._on_context_action)
        self.track_list.reordered.connect(self._on_reordered)
        self.track_list.favorite_toggled.connect(self._on_favorite_toggled)

        # 播放器
        self.player.track_changed.connect(self._on_track_changed)
        self.player.state_changed.connect(self.player_bar.update_state)
        self.player.position_changed.connect(self._on_position)
        self.player.duration_changed.connect(self._on_duration)
        self.player.volume_changed.connect(self.player_bar.update_volume)
        self.player.mode_changed.connect(self.player_bar.set_mode)
        self.player.error.connect(lambda msg: self._toast(msg, 5000))

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
        self.player_bar.favorite_clicked.connect(self._toggle_current_favorite)
        self.player_bar.queue_clicked.connect(self._show_queue_panel)
        self.player_bar.more_clicked.connect(self._show_player_more_menu)

        # 浮动工具条
        self.float_bar.theme_clicked.connect(self._toggle_theme)
        self.float_bar.now_playing_clicked.connect(lambda: self._show_page(1))
        self.float_bar.data_dir_clicked.connect(self._open_data_dir)
        self.float_bar.settings_clicked.connect(self._show_settings)

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
        QShortcut(QKeySequence("Alt+Left"), self, self.go_back)
        QShortcut(QKeySequence("Alt+Right"), self, self.go_forward)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.title_bar.clear_search)
        QShortcut(QKeySequence("Ctrl+F"), self, self.title_bar.focus_search)

    def _restore_state(self) -> None:
        self.sidebar.set_nickname(self.store.settings.nickname)
        self.sidebar.refresh_playlists(self.store.user_playlists(), self._playlist_cover)
        self.set_view(self._view_id)
        self._update_nav_buttons()  # 初始历史 pos=0：前进/后退均禁用
        self.player_bar.set_mode(self.player.mode)
        self.player_bar.update_volume(self.player.volume, self.player.muted)
        self._refresh_counts()

        last_id = self.store.settings.last_track_id
        if last_id and self.store.get_track(last_id) is not None:
            self.player.play_single(last_id, autoplay=False,
                                    seek_ms=self.store.settings.last_position_ms)

    # ---------- 视图管理 ----------

    @staticmethod
    def _is_playlist_view(view_id: str) -> bool:
        return view_id not in (PLAYLIST_LIBRARY, PLAYLIST_RECENT, PLAYLIST_FAVORITES)

    def set_view(self, view_id: str, record: bool = True) -> None:
        if record and view_id != self._view_id:
            del self._history[self._history_pos + 1:]
            self._history.append(view_id)
            self._history_pos = len(self._history) - 1
            self._update_nav_buttons()
        self._view_id = view_id
        self._sort_key = "custom" if self._is_playlist_view(view_id) else "added"
        self._search_text = ""
        self.store.settings.last_view = view_id
        self.sidebar.set_active_view(view_id)
        self.sidebar.refresh_playlists(self.store.user_playlists(), self._playlist_cover)
        self.track_list.set_sort(self._sort_key)
        self.title_bar.clear_search()
        self._show_page(0)
        self.refresh_list()

    def go_back(self) -> None:
        if self._history_pos > 0:
            self._history_pos -= 1
            self.set_view(self._history[self._history_pos], record=False)
            self._update_nav_buttons()

    def go_forward(self) -> None:
        if 0 <= self._history_pos < len(self._history) - 1:
            self._history_pos += 1
            self.set_view(self._history[self._history_pos], record=False)
            self._update_nav_buttons()

    def _update_nav_buttons(self) -> None:
        self.title_bar.set_nav_enabled(self._history_pos > 0,
                                       self._history_pos < len(self._history) - 1)

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
        self.track_list.set_tracks(tracks, lambda t: self.covers.get_pixmap(t, 40, 6), current_tid,
                                   lambda t: self.store.is_favorite(t.id))
        in_playlist = self._is_playlist_view(self._view_id)
        self.track_list.set_context_config(in_playlist, in_playlist and self._sort_key == "custom")

    def _refresh_counts(self) -> None:
        self.sidebar.set_favorite_count(self.store.favorite_count())
        self.sidebar.set_recent_count(len(self.store.recent_tracks(limit=500)))

    def _playlist_cover(self, playlist):
        """歌单封面：取第一首歌的封面；空歌单返回 None（侧边栏画占位图）。"""
        tracks = self.store.playlist_tracks(playlist.id)
        if not tracks:
            return None
        return self.covers.get_pixmap(tracks[0], 40, 6)

    def _show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.track_list.set_now_playing_active(index == 1)
        if index == 1 and self.player.current_track:
            self.now_playing.set_track(
                self.player.current_track, self.covers.get_pixmap(self.player.current_track, 280, 14))

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
        self.player_bar.set_favorite_active(self.store.is_favorite(track.id))
        self.player_bar.set_format(track.fmt)
        self._toast(f"正在播放：{track.display_title} - {track.display_artist}", 3000)
        self._load_lyrics(track)

    def _on_position(self, position_ms: int) -> None:
        duration = self.player.duration_ms or (
            self.player.current_track.duration_ms if self.player.current_track else 0)
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

    # ---------- 我喜欢 ----------

    def _on_favorite_toggled(self, tid: str, checked: bool) -> None:
        if self.store.is_favorite(tid) != checked:
            self.store.toggle_favorite(tid)
            self.store.save()
        self.refresh_list()
        self._refresh_counts()
        if self.player.current_track and self.player.current_track.id == tid:
            self.player_bar.set_favorite_active(checked)

    def _toggle_current_favorite(self) -> None:
        track = self.player.current_track
        if track is None:
            return
        added = self.store.toggle_favorite(track.id)
        self.store.save()
        self.player_bar.set_favorite_active(added)
        self.refresh_list()
        self._refresh_counts()
        self._toast("已加入「我喜欢」" if added else "已取消喜欢", 2000)

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
        self.sidebar.refresh_playlists(self.store.user_playlists(), self._playlist_cover)
        self.set_view(playlist.id)
        self._toast(f"已创建歌单「{name}」", 3000)

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
        self.sidebar.refresh_playlists(self.store.user_playlists(), self._playlist_cover)
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
                self.sidebar.refresh_playlists(self.store.user_playlists(), self._playlist_cover)
            return
        pid = actions.get(chosen)
        if pid:
            added = self.store.add_to_playlist(pid, [track.id])
            self.store.save()
            self.sidebar.refresh_playlists(self.store.user_playlists(), self._playlist_cover)
            name = self.store.get_playlist(pid).name
            self._toast(
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
        self._toast(f"已绑定歌词：{os.path.basename(path)}", 3000)

    def _refresh_track(self, track: Track) -> None:
        meta = read_track(track.path)
        if meta is None:
            self._toast("读取失败：文件不存在或已损坏", 4000)
            return
        self.store.add_or_update(meta, track.path)
        self.store.save()
        self._lyrics_cache.pop(track.id, None)
        self.refresh_list()
        self._toast(f"已重新读取「{track.display_title}」", 3000)

    def _locate(self, track: Track) -> None:
        folder = os.path.dirname(track.path)
        if os.path.isdir(folder):
            ok = QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            if not ok:
                self._toast("无法打开资源管理器", 4000)
        else:
            self._toast("文件所在文件夹不存在", 4000)

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
        self.sidebar.refresh_playlists(self.store.user_playlists(), self._playlist_cover)
        self._refresh_counts()
        self._toast("已移出资料库", 3000)

    # ---------- 昵称 ----------

    def _change_nickname(self) -> None:
        name, ok = QInputDialog.getText(self, "修改昵称", "昵称：", text=self.store.settings.nickname)
        name = (name or "").strip()
        if ok and name:
            self.store.settings.nickname = name
            self.store.save()
            self.sidebar.set_nickname(name)

    # ---------- 主题 / 设置 / 数据目录 ----------

    def _apply_theme(self, name: str) -> None:
        ui_theme.apply_theme(QApplication.instance() or self, name)
        self.store.settings.theme = name
        self.store.save()
        self.float_bar.set_theme_icon(name == "dark")
        self.title_bar.refresh_icons()
        # 主题切换后重刷列表（封面占位/均衡器条颜色等随主题变化）
        self.refresh_list()
        self._toast("已切换到浅色主题" if name == "light" else "已切换到深色主题", 2000)

    def _toggle_theme(self) -> None:
        self._apply_theme("light" if ui_theme.current_theme().name == "dark" else "dark")

    def _open_data_dir(self) -> None:
        from app.paths import app_data_dir
        folder = app_data_dir()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
            self._toast("无法打开数据目录", 4000)

    def _show_settings(self) -> None:
        dialog = SettingsDialog(self.store.settings.theme, self.store.settings.nickname,
                                stats_for(self.store), self)
        dialog.theme_changed.connect(self._apply_theme)
        dialog.nickname_changed.connect(self._on_settings_nickname)
        dialog.exec()

    def _on_settings_nickname(self, name: str) -> None:
        name = name.strip()
        if name:
            self.store.settings.nickname = name
            self.store.save()
            self.sidebar.set_nickname(name)

    def _show_player_more_menu(self) -> None:
        menu = QMenu(self)
        dir_action = menu.addAction("打开数据目录")
        settings_action = menu.addAction("设置")
        menu.addSeparator()
        quit_action = menu.addAction("退出")
        chosen = menu.exec(self.player_bar.more_btn.mapToGlobal(
            self.player_bar.more_btn.rect().bottomLeft()))
        if chosen == dir_action:
            self._open_data_dir()
        elif chosen == settings_action:
            self._show_settings()
        elif chosen == quit_action:
            self.close()

    # ---------- 播放队列浮层 ----------

    def _show_queue_panel(self) -> None:
        from ui.queue_panel import QueuePanel

        ids = self.player.queue_ids
        if not ids:
            self._toast("播放队列为空，请先播放歌曲", 2500)
            return
        panel = QueuePanel(ids, self.player.queue_index, self._queue_track_text, self)
        chosen = panel.exec_at(self.player_bar.queue_button_global_pos())
        if chosen is not None:
            self.player.play_from_queue(chosen)

    def _queue_track_text(self, tid: str) -> tuple[str, str]:
        track = self.store.get_track(tid)
        if track is None:
            return tid, ""
        return track.display_title, track.display_artist

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
            self, "选择音乐文件", "",
            "音频文件 (*.mp3 *.flac *.wav *.m4a *.aac *.ogg *.oga *.opus *.wma);;所有文件 (*)")
        if files:
            self._start_import(files)

    def _start_import(self, paths: list[str]) -> None:
        if self._scanner is not None and self._scanner.isRunning():
            self._toast("已有导入任务在进行中", 3000)
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
            self.sidebar.refresh_playlists(self.store.user_playlists(), self._playlist_cover)
            self.refresh_list()
            self._refresh_counts()
            self._toast(f"导入完成，新增 {self._import_added} 首", 5000)

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

    # ---------- 无边框窗口：最大化 / 缩放 / 圆角 mask ----------

    def _toggle_maximized(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.WindowStateChange:
            maximized = self.isMaximized()
            # 注意：不能用 "maximized" 作属性名——PySide6 6.12 中该名被占用为只读属性，设不进去
            self._root.setProperty("is_maximized", "true" if maximized else "false")
            self._root.style().unpolish(self._root)
            self._root.style().polish(self._root)
            self.title_bar.set_maximized(maximized)
            self._update_mask()
        super().changeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._position_float_bar()
        self._update_mask()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_mask()
        self._position_toast()
        self._position_float_bar()

    def _position_float_bar(self) -> None:
        # 窗口左下角（压在播放栏左上角，QQ 音乐同款位置）；
        # 播放栏左侧已留出 190px 缩进，不会与内容重叠
        x = 16
        y = self._root.height() - self.float_bar.height() - 8
        self.float_bar.move(x, y)
        self.float_bar.raise_()

    def _update_mask(self) -> None:
        if self.isMaximized() or not self.isVisible():
            self._root.clearMask()
            return
        path = QPainterPath()
        path.addRoundedRect(QRectF(self._root.rect()), _CORNER_RADIUS, _CORNER_RADIUS)
        self._root.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _edge_at(self, pos: QPoint) -> int:
        if self.isMaximized():
            return 0
        rect = self._root.rect()
        x, y, w, h = pos.x(), pos.y(), rect.width(), rect.height()
        edge = 0
        if x <= _RESIZE_MARGIN:
            edge |= _EDGE_LEFT
        elif x >= w - _RESIZE_MARGIN:
            edge |= _EDGE_RIGHT
        if y <= _RESIZE_MARGIN:
            edge |= _EDGE_TOP
        elif y >= h - _RESIZE_MARGIN:
            edge |= _EDGE_BOTTOM
        return edge

    @staticmethod
    def _cursor_for_edge(edge: int):
        if edge in (_EDGE_LEFT, _EDGE_RIGHT):
            return Qt.CursorShape.SizeHorCursor
        if edge in (_EDGE_TOP, _EDGE_BOTTOM):
            return Qt.CursorShape.SizeVerCursor
        if edge == _EDGE_LEFT | _EDGE_TOP or edge == _EDGE_RIGHT | _EDGE_BOTTOM:
            return Qt.CursorShape.SizeFDiagCursor
        if edge == _EDGE_RIGHT | _EDGE_TOP or edge == _EDGE_LEFT | _EDGE_BOTTOM:
            return Qt.CursorShape.SizeBDiagCursor
        return None

    def eventFilter(self, obj, event):  # noqa: N802
        """应用级事件过滤：本窗口内任意控件上的鼠标移动都参与边缘缩放判定。"""
        if not isinstance(obj, QWidget) or obj.window() is not self:
            return False
        etype = event.type()
        if etype == QEvent.Type.MouseMove and not self._resizing:
            local = self._root.mapFromGlobal(event.globalPosition().toPoint())
            edge = self._edge_at(local)
            self._resize_edge = edge
            cursor = self._cursor_for_edge(edge)
            if cursor is not None:
                obj.setCursor(cursor)
            else:
                obj.unsetCursor()
        elif etype == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if self._resize_edge:
                self._resizing = True
                self._resize_start_geo = self.geometry()
                self._resize_start_pos = event.globalPosition().toPoint()
        elif etype == QEvent.Type.MouseButtonRelease:
            if self._resizing:
                self._resizing = False
                self._resize_edge = 0
        elif etype == QEvent.Type.MouseMove and self._resizing:
            self._apply_resize(event.globalPosition().toPoint())
        return False

    def _apply_resize(self, gpos: QPoint) -> None:
        geo = self._resize_start_geo
        delta = gpos - self._resize_start_pos
        left, top, right, bottom = geo.left(), geo.top(), geo.right(), geo.bottom()
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        if self._resize_edge & _EDGE_LEFT:
            left = min(left + delta.x(), right - min_w)
        if self._resize_edge & _EDGE_RIGHT:
            right = max(right + delta.x(), left + min_w)
        if self._resize_edge & _EDGE_TOP:
            top = min(top + delta.y(), bottom - min_h)
        if self._resize_edge & _EDGE_BOTTOM:
            bottom = max(bottom + delta.y(), top + min_h)
        self.setGeometry(QRect(QPoint(left, top), QPoint(right, bottom)))

    # ---------- toast ----------

    def _toast(self, text: str, ms: int = 3000) -> None:
        self._toast_label.setText(text)
        self._toast_label.adjustSize()
        self._position_toast()
        self._toast_label.show()
        self._toast_label.raise_()
        self._toast_timer.start(ms)

    def _position_toast(self) -> None:
        if not self._toast_label.isVisible():
            return
        x = (self._root.width() - self._toast_label.width()) // 2
        self._toast_label.move(max(0, x), 64)

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
