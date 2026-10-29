# -*- coding: utf-8 -*-
"""主窗口：无边框圆角壳 + 通栏标题栏 + 侧边栏/列表/正在播放/播放栏装配。

v2.0 变更：
- FramelessWindowHint + WA_TranslucentBackground，圆角由 mask 硬裁剪；
- 边缘缩放（应用级事件过滤，命中 6px 热区即进入 resize 态）；
- 标题栏提供视图前进/后退/刷新/全局搜索；搜索过滤当前视图；
- toast 取代状态栏做瞬时提示；
- 主题在启动时按 settings.theme 应用，切换即时生效；
- 「我喜欢」：行内心 / 播放栏心 -> store.toggle_favorite。

v2.1 变更（本地视频导入与画面播放）：
- 双击视频直接进入视频页（显示画面并播放），双击音频保持原行为；
- 正在播放页按当前曲目类型在音频/视频子视图间切换，切换不中断播放；
- 视频全屏走独立浮窗（只针对画面），F11 切换、Esc 退出；
- 导入入口（文件夹/文件/拖拽）同时接受音频与视频文件。
"""
from __future__ import annotations

import contextlib
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
from app.filesize import file_size
from app.lyrics import LyricLine, lyrics_from_text, strip_meta_lines
from app.lyrics_align import LyricsAlignWorker
from app.lyrics_import import match_lrc_files
from app.lyrics_online import (LyricsFetchWorker, build_web_search_url, clear_miss,
                               read_cache, read_miss, write_cache, write_miss)
from app.metadata import read_track
from app.library import is_in_library
from app.models import PLAYLIST_FAVORITES, PLAYLIST_LIBRARY, PLAYLIST_RECENT, BackgroundConfig, Track
from app.paths import covers_dir, data_file, library_dir
from app.player import PlaybackController
from app.scanner import ScannerWorker
from app.sorting import default_sort_for, preset_by_id, sort_tracks
from app.store import LibraryStore
from ui import theme as ui_theme
from ui.background import BackgroundLayer
from ui.dialogs import ImportProgressDialog
from ui.float_bar import FloatBar
from ui.player_bar import PLAYER_BAR_HEIGHT, PlayerBar
from ui.settings_dialog import SettingsDialog, stats_for
from ui.sidebar import SIDEBAR_WIDTH, Sidebar
from ui.title_bar import TitleBar
from ui.track_list import TrackList
from ui.now_playing import NowPlayingPage
from ui.video_view import VideoFullscreenOverlay

# 联网检索中给用户的提示：既解释「为什么现在没歌词」，也暗示等一下会出现
ONLINE_PENDING_HINT = "正在联网匹配歌词…"
# 检索结束仍无结果：明确区分「没找到」和「这首歌本来就没歌词」，并告诉用户出路
ONLINE_MISSED_HINT = "未找到歌词\n可右键「重新联网匹配」再试一次"
# 联网被中断（超时/限流/预算耗尽）：不等于「没歌词」，不落负缓存，只提示可重试
ONLINE_ABORTED_HINT = "联网匹配失败，请稍后重试\n可右键「重新联网匹配」再试一次"

# 排序预设集中在 app/sorting.py（维度 + 方向 + 文案），此文件只负责应用

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
        self._sort_id = default_sort_for(self._is_playlist_view(self._view_id))
        # 各视图分别记住上次选择的排序：切走再切回来不会被打回默认值
        self._sort_by_view: dict[str, str] = {}
        self._search_text = ""
        self._displayed: list[Track] = []
        self._scanner: ScannerWorker | None = None
        self._lyrics_cache: dict[str, tuple[list[LyricLine], list[str], str]] = {}
        # 联网补歌词（v2.2）：同一首只试一次；worker 自己持引用，结束后清掉
        self._lyrics_workers: dict[str, LyricsFetchWorker] = {}
        # 联网对齐歌词（v2.6.6）：纯文本 → LRC，同一首同时只跑一个
        self._align_workers: dict[str, LyricsAlignWorker] = {}
        self._online_attempted: set[str] = set()
        # 当前是否处于「自定义背景」模式（面板半透明）；None = 无背景
        self._bg_scrim: float | None = None
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
        self._apply_appearance(save=False)
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

        # 自定义背景层（v2.2）：最先创建 => 天然处于最底层，被后续控件盖住。
        # 手动定位而不是进布局：它要铺满整个窗口根容器（含标题栏/播放栏下方）。
        self.background = BackgroundLayer(self._root)

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

        # 浮动工具条（覆盖播放栏左上角，右缘对齐侧边栏内容右边界）
        self.float_bar = FloatBar(self._root)
        self.float_bar.raise_()

        # 右下角版本号（原来在侧边栏底部，挪到播放栏右下角）
        self.version_label = QLabel("v2.6.6 · 本地音乐与视频", self._root)
        self.version_label.setObjectName("VersionLabel")
        self.version_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.version_label.raise_()

        # 视频全屏浮窗（v2.1）：画面控件临时搬进去，播放器不受影响
        self._fullscreen = VideoFullscreenOverlay()
        self._fullscreen.exited.connect(self._exit_video_fullscreen)

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
        self.title_bar.refresh_clicked.connect(self.refresh_list)
        self.title_bar.search_changed.connect(self._on_search_changed)
        self.title_bar.minimize_clicked.connect(self.showMinimized)
        self.title_bar.maximize_clicked.connect(self._toggle_maximized)
        self.title_bar.close_clicked.connect(self.close)

        # 侧边栏
        self.sidebar.view_requested.connect(self.set_view)
        self.sidebar.create_playlist_requested.connect(self._create_playlist)
        self.sidebar.playlist_action.connect(self._playlist_action)
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
        self.player.state_changed.connect(self._on_player_state)
        self.player.position_changed.connect(self._on_position)
        self.player.duration_changed.connect(self._on_duration)
        self.player.volume_changed.connect(self.player_bar.update_volume)
        self.player.mode_changed.connect(self.player_bar.set_mode)
        self.player.error.connect(lambda msg: self._toast(msg, 5000))

        # 歌词逐字动效需要平滑的行内进度，而 QMediaPlayer 的 positionChanged
        # 在 PySide6 里默认约 1s 一次（且无 setNotifyInterval 可调），会让
        # 「颜色覆盖」一跳一跳。这里用一个 100ms 定时器在播放时主动轮询
        # position()，只在 playing 态运行，暂停/停止即停，开销可忽略。
        self._position_timer = QTimer(self)
        self._position_timer.setInterval(100)
        self._position_timer.timeout.connect(
            lambda: self._on_position(self.player.position_ms))

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
        self.float_bar.import_clicked.connect(self._show_import_menu)
        self.float_bar.data_dir_clicked.connect(self._open_data_dir)
        self.float_bar.settings_clicked.connect(self._show_settings)

        # 正在播放页歌词
        self.now_playing.seek_requested.connect(lambda ms: self.player.seek(ms))
        # 歌词区右键「重新联网匹配歌词」（v2.4）：给用户一个补救入口，
        # 否则负缓存生效后这首歌 7 天内都不会再自动重试
        self.now_playing.lyrics.retry_online_requested.connect(
            self._retry_online_lyrics)
        # 歌词区右键「导入歌词文件 / 批量导入歌词」（v2.6.2）
        self.now_playing.lyrics.import_lyrics_requested.connect(
            self._import_lyrics_for_current)
        self.now_playing.lyrics.batch_import_requested.connect(
            self._batch_import_lyrics)
        # 歌词区右键「在线搜索歌词」（v2.6.4）：联网匹配失败时去网页自己搜
        self.now_playing.lyrics.search_online_requested.connect(
            self._open_lyrics_search)
        # 歌词区右键「联网对齐歌词」（v2.6.6）：纯文本 → 带时间轴 LRC
        self.now_playing.lyrics.align_lyrics_requested.connect(
            self._align_lyrics_for_current)

        # 视频页交互（v2.1）
        self.now_playing.back_to_list_requested.connect(lambda: self._show_page(0))
        self.now_playing.fullscreen_requested.connect(self._set_video_fullscreen)
        self.now_playing.audio_view.video_btn.clicked.connect(
            lambda: self.now_playing.set_media_mode(True))
        self.now_playing.video_view.music_btn.clicked.connect(
            lambda: self.now_playing.set_media_mode(False))
        self.now_playing.video_view.back_btn.clicked.connect(lambda: self._show_page(0))
        self.now_playing.video_view.full_btn.clicked.connect(
            lambda: self._set_video_fullscreen(True))

        # 视频画面输出：sink 与播放器长期绑定（切模式不重连，播放不中断）
        self.player.set_video_output(self.now_playing.video_host.sink)

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
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._on_escape)
        QShortcut(QKeySequence("Ctrl+F"), self, self.title_bar.focus_search)
        # 视频全屏：F11 切换，Esc 优先退出全屏
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, self._toggle_video_fullscreen)

    def _restore_state(self) -> None:
        self.sidebar.set_nickname(self.store.settings.nickname)
        self.sidebar.refresh_playlists(self.store.user_playlists(), self._playlist_cover)
        # 歌词播放动效（v2.6.4）：启动即按持久化设置渲染
        self.now_playing.lyrics.set_effect(self.store.settings.lyrics_effect)
        self.set_view(self._view_id)
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
        self._view_id = view_id
        self._sort_id = self._sort_by_view.get(
            view_id, default_sort_for(self._is_playlist_view(view_id)))
        self._search_text = ""
        self.store.settings.last_view = view_id
        self.sidebar.set_active_view(view_id)
        self.sidebar.refresh_playlists(self.store.user_playlists(), self._playlist_cover)
        self.track_list.set_sort(self._sort_id)
        self.title_bar.clear_search()
        self._show_page(0)
        self.refresh_list()

    def go_back(self) -> None:
        if self._history_pos > 0:
            self._history_pos -= 1
            self.set_view(self._history[self._history_pos], record=False)

    def go_forward(self) -> None:
        if 0 <= self._history_pos < len(self._history) - 1:
            self._history_pos += 1
            self.set_view(self._history[self._history_pos], record=False)

    def refresh_list(self) -> None:
        tracks = self.store.view_tracks(self._view_id)
        # 搜索过滤
        if self._search_text:
            needle = self._search_text.casefold()
            tracks = [t for t in tracks
                      if needle in t.display_title.casefold()
                      or needle in t.display_artist.casefold()
                      or needle in t.display_album.casefold()]
        # 排序（维度 + 方向由预设决定）
        # 文件大小一次取齐：排序与「大小」列共用，避免逐行重复 stat
        sizes = {t.id: file_size(t.path) for t in tracks}
        tracks = sort_tracks(tracks, self._sort_id, lambda t: sizes.get(t.id, 0))
        self._displayed = tracks
        current_tid = self.player.current_track.id if self.player.current_track else None
        total_ms = sum(t.duration_ms for t in tracks)
        self.track_list.set_header(self.store.view_name(self._view_id), len(tracks), total_ms)
        self.track_list.set_tracks(tracks, lambda t: self.covers.get_pixmap(t, 40, 6), current_tid,
                                   lambda t: self.store.is_favorite(t.id),
                                   lambda t: sizes.get(t.id, 0))
        in_playlist = self._is_playlist_view(self._view_id)
        # 只有「自定义顺序」才允许拖拽排序，否则拖完又被排序覆盖
        self.track_list.set_context_config(
            in_playlist, in_playlist and preset_by_id(self._sort_id).is_custom)

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
        self._refresh_background()          # 两页可以各自一套背景（v2.2）
        if index == 1 and self.player.current_track:
            track = self.player.current_track
            self.now_playing.set_track(
                track, self.covers.get_pixmap(track, 280, 14))
            # 进入正在播放页时按当前曲目类型选择子视图
            self.now_playing.set_media_mode(track.is_video)

    # ---------- 视频模式 / 全屏（v2.1） ----------

    def _set_video_fullscreen(self, active: bool) -> None:
        """视频全屏：把画面控件搬进浮窗；播放器与 sink 不动，播放不中断。"""
        if active:
            if self.now_playing.media_mode != "video":
                self.now_playing.set_media_mode(True)
            self._fullscreen.enter(self.now_playing.video_host.surface)
        else:
            self._fullscreen.leave()

    def _exit_video_fullscreen(self) -> None:
        self._fullscreen.leave()
        if self.stack.currentIndex() != 1:
            self._show_page(1)

    def _toggle_video_fullscreen(self) -> None:
        self._set_video_fullscreen(not self._fullscreen.active)

    def _on_escape(self) -> None:
        """Esc 优先级：全屏 > 清空搜索。"""
        if self._fullscreen.active:
            self._exit_video_fullscreen()
            return
        self.title_bar.clear_search()

    # ---------- 播放相关 ----------

    def _on_track_activated(self, tid: str, index: int) -> None:
        ids = [t.id for t in self._displayed]
        if tid not in ids:
            return
        track = self.store.get_track(tid)
        self.player.play_tracks(ids, ids.index(tid))
        # 视频双击 -> 直接进入视频页显示画面；音频保持原行为（留在列表页）
        if track is not None and track.is_video:
            self._show_page(1)

    def _play_all(self) -> None:
        ids = [t.id for t in self._displayed]
        if ids:
            self.player.play_tracks(ids, 0)
            self._show_page(0)

    def _on_track_changed(self, track: Track) -> None:
        self.track_list.set_current_track(track.id)
        self.now_playing.set_track(track, self.covers.get_pixmap(track, 280, 14))
        # 自动切歌后，正在播放页的子视图跟随新曲目类型
        self.now_playing.set_media_mode(track.is_video)
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

    def _on_player_state(self, state: str) -> None:
        """播放时开启进度轮询（供歌词逐字动效），暂停/停止即关。"""
        if state == "playing":
            self._position_timer.start()
        else:
            self._position_timer.stop()

    def _on_duration(self, duration_ms: int) -> None:
        self.player_bar.update_duration(duration_ms)
        track = self.player.current_track
        if track is not None and not track.duration_ms:
            # v2.1：视频等 mutagen 读不出时长的媒体，加载后回填并落盘
            track.duration_ms = duration_ms
            self.store.save()
            self.refresh_list()
            if self.now_playing.media_mode == "video":
                self.now_playing.set_track(
                    track, self.covers.get_pixmap(track, 280, 14))

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
        synced, plain, source = cached
        if synced:
            self.now_playing.set_synced(synced)
            self.now_playing.set_source(source)
        elif plain:
            self.now_playing.set_plain(plain)
            self.now_playing.set_source(source)
        elif self._start_online_lyrics(track) or track.id in self._lyrics_workers:
            # 已经发起、结果还没回来：先告诉用户「在找」，别让人以为这首没歌词
            self.now_playing.set_empty(ONLINE_PENDING_HINT)
        else:
            self.now_playing.set_empty()

    def _resolve_lyrics(self, track: Track) -> tuple[list[LyricLine], list[str], str]:
        """返回 (同步行, 纯文本行, 来源标签)。来源为空串表示「没有歌词」。"""
        # 1) 手动绑定的 .lrc
        if track.lrc_path and os.path.isfile(track.lrc_path):
            text = _read_text(track.lrc_path)
            if text:
                synced, plain = lyrics_from_text(text)
                if synced or plain:
                    return synced, plain, "本地歌词 · 手动绑定"
        # 2) 同名 .lrc
        sidecar = os.path.splitext(track.path)[0] + ".lrc"
        if os.path.isfile(sidecar):
            text = _read_text(sidecar)
            if text:
                synced, plain = lyrics_from_text(text)
                if synced or plain:
                    return synced, plain, "本地歌词 · 同名 .lrc"
        # 3) 内嵌歌词
        try:
            meta = read_track(track.path)
        except Exception:  # noqa: BLE001
            meta = None
        if meta is not None and meta.lyrics_text:
            synced, plain = lyrics_from_text(meta.lyrics_text)
            if synced or plain:
                return synced, plain, "本地歌词 · 内嵌"
        # 4) 上次联网匹配的缓存（v2.2）——命中即完全离线可用
        cached_text = read_cache(track.id)
        if cached_text:
            synced, plain = lyrics_from_text(cached_text)
            if synced or plain:
                return synced, plain, "来源：LRCLIB（缓存）"
        # 5) 联网兜底不在这里做：网络请求是异步的，交给 _start_online_lyrics
        return [], [], ""

    def _start_online_lyrics(self, track: Track, force: bool = False) -> bool:
        """本地无歌词时发起一次联网检索。返回 True 表示「已经去要了」。

        四条不发的理由：设置里关了、视频文件（歌词无意义）、本次会话已试过、
        负缓存里记着「最近查过且没查到」（默认 7 天内不重试，免得每次启动都为
        冷门歌/纯音乐空打四个请求）。`force=True` 由用户右键「重新联网匹配」触发，
        绕过后面两条。
        """
        if track.is_video:
            return False
        if not self.store.settings.online_lyrics:
            return False
        if not force:
            if track.id in self._online_attempted:
                return False
            if read_miss(track.id):
                return False
        if not (track.display_title or track.artist):
            return False
        self._online_attempted.add(track.id)
        worker = LyricsFetchWorker(track.id, track.display_title, track.artist,
                                   track.duration_ms, track.album, self)
        worker.found.connect(self._on_online_lyrics)
        worker.missed.connect(self._on_online_lyrics_missed)
        worker.aborted.connect(self._on_online_lyrics_aborted)
        worker.progress.connect(self._on_online_lyrics_progress)
        worker.finished.connect(lambda tid=track.id: self._lyrics_workers.pop(tid, None))
        self._lyrics_workers[track.id] = worker
        worker.start()
        return True

    def _on_online_lyrics_progress(self, track_id: str, cur: int, total: int) -> None:
        """联网匹配进度：只更新「正在找」的空状态文案，不打断已有歌词。"""
        current = self.player.current_track
        if current is None or current.id != track_id:
            return
        if self._lyrics_cache.get(track_id) is not None:
            return                      # 已经拿到歌词了，别再覆盖
        self.now_playing.set_empty(f"正在联网匹配歌词…（{cur}/{total}）")

    def _on_online_lyrics(self, track_id: str, text: str) -> None:
        synced, plain = lyrics_from_text(text)
        if not synced and not plain:
            return
        self._lyrics_cache[track_id] = (synced, plain, "来源：LRCLIB")
        write_cache(track_id, text)
        clear_miss(track_id)                # 之前记过「没查到」，现在推翻它
        current = self.player.current_track
        if current is None or current.id != track_id:
            return                      # 用户已经切走了，别串到当前这首歌上
        if synced:
            self.now_playing.set_synced(synced)
        else:
            self.now_playing.set_plain(plain)
        self.now_playing.set_source("来源：LRCLIB")
        self._toast("已联网匹配到歌词（LRCLIB）", 2500)

    def _on_online_lyrics_missed(self, track_id: str) -> None:
        """没匹配到：落负缓存，并把当前这首歌的空状态文案换成「没找到」。"""
        write_miss(track_id)
        current = self.player.current_track
        if current is None or current.id != track_id:
            return
        self.now_playing.set_empty(ONLINE_MISSED_HINT)

    def _on_online_lyrics_aborted(self, track_id: str) -> None:
        """联网被中断（超时/限流/预算耗尽）：不等于「没歌词」，不落负缓存。"""
        current = self.player.current_track
        if current is None or current.id != track_id:
            return
        self.now_playing.set_empty(ONLINE_ABORTED_HINT)

    def _retry_online_lyrics(self) -> None:
        """歌词区右键「重新联网匹配歌词」：无视负缓存与「本次已试过」，重新抓一次。"""
        track = self.player.current_track
        if track is None:
            self._toast("当前没有播放中的歌曲", 2000)
            return
        if track.is_video:
            self._toast("视频文件不匹配歌词", 2000)
            return
        if not self.store.settings.online_lyrics:
            self._toast("设置里未开启联网歌词", 2500)
            return
        if track.id in self._lyrics_workers:
            self._toast("正在匹配中，请稍候", 2000)
            return
        clear_miss(track.id)
        self._online_attempted.discard(track.id)
        if self._start_online_lyrics(track, force=True):
            self.now_playing.set_empty(ONLINE_PENDING_HINT)
        else:
            self._toast("无法发起联网匹配", 2500)

    def _open_lyrics_search(self) -> None:
        """歌词区右键「在线搜索歌词」：用系统默认浏览器打开 LRCLIB 网页搜索。

        联网匹配不到（未找到 / 被限流）时给用户一条自己动手的路：网页已自动
        带上「标题 + 艺人」，用户找到后下载 .lrc 再用「导入歌词文件」绑定。
        """
        track = self.player.current_track
        if track is None:
            self._toast("当前没有播放中的歌曲", 2000)
            return
        url = build_web_search_url(track.display_title, track.display_artist)
        if not QDesktopServices.openUrl(QUrl(url)):
            self._toast("无法打开浏览器，请手动访问 lrclib.net", 4000)

    # ---------- 联网对齐歌词（v2.6.6：纯文本 → 带时间轴 LRC） ----------

    def _align_lyrics_for_current(self) -> None:
        """歌词区右键「联网对齐歌词」：把当前显示的纯文本歌词转成带时间轴的 LRC。"""
        track = self.player.current_track
        if track is None:
            self._toast("当前没有播放中的歌曲", 2000)
            return
        synced, plain, _source = self._lyrics_cache.get(track.id, ([], [], ""))
        if synced:
            self._toast("这首已是带时间轴的歌词，无需对齐", 2500)
            return
        if not plain:
            self._toast("当前没有可对齐的纯文本歌词，请先导入歌词", 3000)
            return
        self._start_align(track, "\n".join(plain))

    def _start_align(self, track: Track, plain_text: str) -> None:
        """发起一次联网对齐：先检查 key 与重复任务，再开后台线程。"""
        plain_text = (plain_text or "").strip()
        if not plain_text:
            self._toast("没有可对齐的歌词文本", 2500)
            return
        key = (self.store.settings.lyrics_align_api_key or "").strip()
        if not key:
            self._toast("未填写歌词对齐 Key，请到「设置 → 歌词与统计」填写", 4000)
            return
        if track.id in self._align_workers:
            self._toast("这首歌正在对齐中，请稍候", 2000)
            return
        worker = LyricsAlignWorker(track.id, track.path, plain_text, key, self)
        worker.done.connect(self._on_align_done)
        worker.soft_fail.connect(self._on_align_soft_fail)
        worker.failed.connect(self._on_align_failed)
        worker.progress.connect(self._on_align_progress)
        worker.finished.connect(lambda tid=track.id: self._align_workers.pop(tid, None))
        self._align_workers[track.id] = worker
        worker.start()
        self.now_playing.set_empty("正在联网对齐歌词…")
        self._toast("已开始联网对齐，请稍候（约 1~2 分钟）", 3000)

    def _on_align_progress(self, track_id: str, percent: int, stage: str) -> None:
        current = self.player.current_track
        if current is None or current.id != track_id:
            return
        self.now_playing.set_empty(f"正在联网对齐歌词… {stage}")

    def _on_align_done(self, track_id: str, lrc: str) -> None:
        self._apply_aligned_lrc(track_id, lrc, soft_fail=False)

    def _on_align_soft_fail(self, track_id: str, lrc: str) -> None:
        self._apply_aligned_lrc(track_id, lrc, soft_fail=True)

    def _apply_aligned_lrc(self, track_id: str, lrc: str, soft_fail: bool) -> None:
        """对齐结果落地：缓存 + 解除纯文本绑定 + 立即刷新滚动。"""
        synced, _plain = lyrics_from_text(lrc)
        if not synced:
            # 对齐出的 LRC 解析不出时间轴，不能滚动，按失败处理
            current = self.player.current_track
            if current is not None and current.id == track_id:
                self.now_playing.set_empty("对齐结果无法解析，请重试")
            self._toast("对齐结果无效，请重试", 3000)
            return
        # 1) 落缓存，之后离线也能滚动（_resolve_lyrics 第 4 级来源）
        write_cache(track_id, lrc)
        # 2) 解除纯文本手动绑定，让缓存里的对齐结果优先生效
        track = self.store.get_track(track_id)
        if track is not None and track.lrc_path:
            track.lrc_path = None
            self.store.save()
        # 3) 更新内存缓存 + 立即刷新显示
        self._lyrics_cache[track_id] = (synced, [], "来源：联网对齐")
        current = self.player.current_track
        if current is not None and current.id == track_id:
            self.now_playing.set_synced(synced)
            self.now_playing.set_source("来源：联网对齐")
        if soft_fail:
            self._toast("对齐完成，但结果可能不准，请核对", 4000)
        else:
            self._toast("已对齐歌词，现在可以跟歌滚动了", 3000)

    def _on_align_failed(self, track_id: str, message: str) -> None:
        current = self.player.current_track
        if current is not None and current.id == track_id:
            self.now_playing.set_empty("对齐失败")
        self._toast(message or "对齐失败", 4000)

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
                                              "歌词文件 (*.lrc *.txt);;所有文件 (*)")
        if not path:
            return
        self._bind_lyrics_file(track, path)

    def _bind_lyrics_file(self, track: Track, path: str) -> bool:
        """把一份歌词文件绑到某首歌，先「识别」再绑定。返回是否绑定成功。

        识别失败（不是有效 LRC / 没有任何歌词行）时不绑定，避免给用户塞一个
        空歌词面板。
        """
        text = _read_text(path)
        synced, plain = lyrics_from_text(text)
        if not synced and not plain:
            self._toast(f"未识别到歌词行：{os.path.basename(path)}", 4000)
            return False
        track.lrc_path = path
        self.store.save()
        self._lyrics_cache.pop(track.id, None)
        if self.player.current_track and self.player.current_track.id == track.id:
            self._load_lyrics(track)
        if synced:
            self._toast(f"已绑定歌词：{os.path.basename(path)}（识别到 {len(synced)} 行同步歌词）", 3500)
        else:
            self._toast(f"已绑定歌词：{os.path.basename(path)}（识别到纯文本歌词 {len(plain)} 行）", 3500)
            self._maybe_offer_align(track, text)
        return True

    def _maybe_offer_align(self, track: Track, text: str) -> None:
        """导入纯文本歌词后询问是否联网对齐成带时间轴的歌词（v2.6.6）。"""
        clean = strip_meta_lines(text).strip()
        if not clean:
            return
        box = QMessageBox(self)
        box.setWindowTitle("联网对齐歌词")
        box.setText("检测到纯文本歌词（没有时间轴，不能跟歌滚动）。\n"
                    "是否联网对齐成带时间轴的歌词？")
        box.setInformativeText("会联网上传音频，需在设置里填写对齐 Key，免费额度约 15 分钟/月。")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self._start_align(track, clean)

    def _import_lyrics_for_current(self) -> None:
        """歌词区右键「导入歌词文件…」：给当前这首歌手动挑一份 .lrc。"""
        track = self.player.current_track
        if track is None:
            self._toast("当前没有播放中的歌曲", 2000)
            return
        self._bind_lyrics(track)

    def _batch_import_lyrics(self) -> None:
        """歌词区右键「批量导入歌词…」：选一个文件夹，按文件名把 *.lrc/*.txt 认到曲库。"""
        folder = QFileDialog.getExistingDirectory(self, "选择包含歌词文件的文件夹")
        if not folder:
            return
        lrc_files: list[str] = []
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if name.lower().endswith((".lrc", ".txt")):
                    lrc_files.append(os.path.join(root, name))
        if not lrc_files:
            self._toast("该文件夹里没有 .lrc / .txt 歌词文件", 3000)
            return
        matched, unmatched = match_lrc_files(lrc_files, self.store.all_tracks())
        for path, track in matched.items():
            track.lrc_path = path
            self._lyrics_cache.pop(track.id, None)
        if matched:
            self.store.save()
        # 若当前这首歌被绑上了，立即刷新歌词区
        current = self.player.current_track
        if current is not None and any(t.id == current.id for t in matched.values()):
            self._load_lyrics(current)
        summary = f"导入歌词：匹配 {len(matched)} 首"
        if unmatched:
            summary += f"，{len(unmatched)} 个文件未匹配"
        self._toast(summary, 4000)

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
        # 曲库内的副本：移出时一并删除，避免占着磁盘又不在列表里（v2.1.9）。
        # 老条目（外部路径）仍按「不动磁盘文件」处理。
        in_library = is_in_library(track.path, library_dir())
        box = QMessageBox(self)
        box.setWindowTitle("移除出音乐库")
        if in_library:
            box.setText(f"将「{track.display_title}」移出音乐库？\n"
                        f"（软件曲库内的副本会被删除，你自己的原文件不受影响）")
        else:
            box.setText(f"将「{track.display_title}」移出音乐库？\n"
                        f"（不会删除磁盘文件，但会从所有歌单中移除）")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        if self.player.current_track and self.player.current_track.id == track.id:
            self.player.stop()
        self.store.remove_track(track.id)
        if in_library:
            with contextlib.suppress(OSError):
                os.remove(track.path)
        self.store.save()
        self.refresh_list()
        self.sidebar.refresh_playlists(self.store.user_playlists(), self._playlist_cover)
        self._refresh_counts()
        self._toast("已移出音乐库", 3000)

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
        self.store.settings.theme = name
        self._apply_appearance()
        # 文案跟主题表走：两态循环，用主题表的中文名，别写死「浅色 / 深色」
        label = ui_theme.THEME_LABEL.get(name, name)
        self._toast(f"已切换到{label}主题", 2000)

    def _apply_appearance(self, save: bool = True) -> None:
        """把 settings 里的主题/强调色/字号一次性应用到整个界面（v2.2）。

        汇总成一个入口的理由：三者的收尾动作完全一样（重刷图标、均衡器条、
        浮动条定位、列表重绘）。分开写迟早会漏掉其中一步，表现为"换了颜色但
        某个角落还是旧的"。
        """
        s = self.store.settings
        config = s.bg_config(self._current_bg_page())
        # 背景开着时面板必须半透明，否则自定义背景被完全盖住（"设了没反应"）
        self._bg_scrim = ui_theme.BG_SCRIM if config.type != "none" else None
        ui_theme.set_appearance(QApplication.instance() or self, s.theme,
                                accent=s.accent_color, font_scale=s.font_scale,
                                scrim=self._bg_scrim)
        if save:
            self.store.save()
        self.float_bar.set_theme_icon(ui_theme.current_theme().name)
        self.title_bar.refresh_icons()
        self.player_bar.refresh_theme()
        # 字号/内边距变化会改变浮动条 sizeHint → 必须重新量一次宽度并定位
        self._position_float_bar()
        # 封面占位、均衡器条颜色等随主题变化 → 重刷列表
        self.refresh_list()
        self._apply_background_config(config)

    def _on_settings_accent(self, color: str) -> None:
        color = (color or "").strip().lower()
        if color == self.store.settings.accent_color:
            return
        self.store.settings.accent_color = color
        self._apply_appearance()
        self._toast("已恢复主题默认强调色" if not color else "已更新强调色", 2000)

    def _on_settings_font_scale(self, scale: float) -> None:
        scale = ui_theme.clamp_font_scale(scale)
        if abs(scale - self.store.settings.font_scale) < 1e-3:
            return
        self.store.settings.font_scale = scale
        self._apply_appearance()
        self._toast(f"字号已调整为 {round(scale * 100)}%", 2000)

    def _on_settings_lyrics_effect(self, effect: str) -> None:
        """歌词播放动效：保存 + 立即应用到歌词面板。"""
        if self.store.settings.lyrics_effect == effect:
            return
        self.store.settings.lyrics_effect = effect
        self.store.save()
        self.now_playing.lyrics.set_effect(effect)
        labels = {"none": "无特效", "zoom": "放大当前行",
                  "typewriter": "打字机", "karaoke": "颜色覆盖"}
        self._toast(f"歌词动效：{labels.get(effect, effect)}", 2000)

    def _on_settings_align_key(self, key: str) -> None:
        """保存联网歌词对齐 Key（不打印、不进日志）。"""
        self.store.settings.lyrics_align_api_key = key or ""
        self.store.save()

    def _toggle_theme(self) -> None:
        # 两态循环：深色 ↔ 浅色
        order = ui_theme.THEME_ORDER
        cur = ui_theme.current_theme().name
        idx = order.index(cur) if cur in order else -1
        self._apply_theme(order[(idx + 1) % len(order)])

    def _open_data_dir(self) -> None:
        from app.paths import app_data_dir
        folder = app_data_dir()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
            self._toast("无法打开数据目录", 4000)

    def _show_settings(self) -> None:
        s = self.store.settings
        dialog = SettingsDialog(s.theme, s.nickname, stats_for(self.store), self,
                                online_lyrics=s.online_lyrics,
                                accent_color=s.accent_color,
                                font_scale=s.font_scale,
                                bg_configs={"all": s.bg_all, "library": s.bg_library,
                                            "now_playing": s.bg_now},
                                bg_scope=self._current_bg_page(),
                                lyrics_effect=s.lyrics_effect,
                                lyrics_align_api_key=s.lyrics_align_api_key)
        dialog.theme_changed.connect(self._apply_theme)
        dialog.nickname_changed.connect(self._on_settings_nickname)
        dialog.online_lyrics_changed.connect(self._on_settings_online_lyrics)
        dialog.accent_changed.connect(self._on_settings_accent)
        dialog.font_scale_changed.connect(self._on_settings_font_scale)
        dialog.lyrics_effect_changed.connect(self._on_settings_lyrics_effect)
        dialog.lyrics_align_api_key_changed.connect(self._on_settings_align_key)
        dialog.background_changed.connect(self._on_settings_background)
        dialog.storage_changed.connect(self._on_storage_changed)
        dialog.exec()

    def _on_storage_changed(self, _path: str) -> None:
        """数据目录已搬走：当前进程还握着旧路径，必须重启才生效。"""
        self._toast("数据已移动，重启播放器后生效", 6000)

    def _on_settings_online_lyrics(self, enabled: bool) -> None:
        if self.store.settings.online_lyrics == enabled:
            return
        self.store.settings.online_lyrics = enabled
        self.store.save()
        if enabled:
            # 刚打开开关：把「试过但没结果」的记录清掉，让当前这首立刻重试
            self._online_attempted.clear()
            track = self.player.current_track
            if track is not None and self._lyrics_cache.get(track.id) == ([], [], ""):
                self._load_lyrics(track)
        self._toast("已开启联网补歌词" if enabled else "已关闭联网补歌词", 2500)

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
        folder = QFileDialog.getExistingDirectory(self, "选择音乐或视频文件夹")
        if folder:
            self._start_import([folder])

    def _import_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择音乐或视频文件", "",
            "媒体文件 (*.mp3 *.flac *.wav *.m4a *.aac *.ogg *.oga *.opus *.wma "
            "*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v);;"
            "音频文件 (*.mp3 *.flac *.wav *.m4a *.aac *.ogg *.oga *.opus *.wma);;"
            "视频文件 (*.mp4 *.mkv *.mov *.avi *.wmv *.flv *.webm *.m4v);;"
            "所有文件 (*)")
        if files:
            self._start_import(files)

    def _start_import(self, paths: list[str]) -> None:
        if self._scanner is not None and self._scanner.isRunning():
            self._toast("已有导入任务在进行中", 3000)
            return
        self._import_added = 0
        dialog = ImportProgressDialog(self)
        # v2.1.9：导入 = 把文件复制进软件曲库；之后曲目与原文件解耦，
        # 用户挪动/删除原文件也不会变成「失效」。
        worker = ScannerWorker(paths, library_dir=library_dir())
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
            msg = f"导入完成，新增 {self._import_added} 首，已复制到曲库"
            if worker.failed:
                msg += f"（{worker.failed} 个文件复制失败已跳过）"
            self._toast(msg, 5000)

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

    def _on_sort_changed(self, sort_id: str) -> None:
        self._sort_id = preset_by_id(sort_id).id
        self._sort_by_view[self._view_id] = self._sort_id
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
        self._layout_background()

    def _position_float_bar(self) -> None:
        # 左下角，右缘对齐侧边栏内容右边界（248 - 12 = 236），不再跨进内容区。
        # 竖直方向：在播放栏里垂直居中（v2.6.1 单行后整条只有 38 高，若继续贴
        # 窗口底边会明显"下沉"到播放栏下半截，与封面/按钮的重心错位）。
        # 注意：绝对定位的子控件不会自动拿到 sizeHint 宽度，必须 adjustSize()，
        # 否则宽度停在默认 100px，图标+文字按钮会被父控件裁掉（v2.1.2 起的真实缺陷）。
        bar = self.float_bar
        bar.adjustSize()
        right = SIDEBAR_WIDTH - 12
        x = right - bar.width()
        y = self._root.height() - PLAYER_BAR_HEIGHT + (PLAYER_BAR_HEIGHT - bar.height()) // 2
        bar.move(x, max(0, y))
        bar.raise_()
        self._position_version_label()

    def _position_version_label(self) -> None:
        # 右下角：贴在播放栏右下角，右/下各留一点边距
        lbl = self.version_label
        lbl.adjustSize()
        lbl.move(self._root.width() - lbl.width() - 14,
                 self._root.height() - lbl.height() - 4)
        lbl.raise_()

    # ---------- 自定义背景（v2.2） ----------

    def _current_bg_page(self) -> str:
        """当前页的作用域名：列表页 / 正在播放页各自可以有一套背景。"""
        return "now_playing" if self.stack.currentIndex() == 1 else "library"

    def _layout_background(self) -> None:
        """背景层铺满窗口根容器；内缩 1px，让 QSS 的圆角描边不被盖掉。"""
        rect = self._root.rect()
        self.background.setGeometry(rect.x() + 1, rect.y() + 1,
                                    max(0, rect.width() - 2), max(0, rect.height() - 2))

    def _apply_background_config(self, config) -> None:
        self.background.set_config(config)
        # 「深色」与「浅色」主题自带底层装饰（月牙星点 / 羽饰 / 四角星）；
        # 用户一旦设了自定义背景就让位，免得两套背景打架。
        theme = ui_theme.current_theme()
        self.background.set_decor(
            theme.name if config.type == "none" and theme.name in ("columbina", "light") else "",
            theme.ACCENT,
        )
        self._layout_background()
        self.background.lower()      # 任何 raise_() 之后都压回最底层

    def _refresh_background(self) -> None:
        """换页/换设置后更新背景。

        背景「有没有开」会决定面板是否半透明，而那是整张 QSS 的事 ——
        只在开关状态真的翻转时才重建样式表，避免每次切页都重刷全身。
        """
        config = self.store.settings.bg_config(self._current_bg_page())
        want_scrim = ui_theme.BG_SCRIM if config.type != "none" else None
        if want_scrim != self._bg_scrim:
            self._apply_appearance()      # 会顺带把 config 应用上
        else:
            self._apply_background_config(config)

    def _on_settings_background(self, scope: str, config) -> None:
        """设置对话框改背景：写到指定作用域（all / library / now_playing）。

        存的是**副本**：对话框后续还会就地改它自己那份配置，共享引用会让
        「没保存的改动」悄悄进到设置里。
        """
        self.store.settings.set_bg_config(scope, BackgroundConfig.from_dict(config.to_dict()))
        self.store.save()
        self._refresh_background()

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

    @staticmethod
    def _qt_edges(edge: int):
        """把内部边位映射成 Qt 的 Edges，交给 startSystemResize。"""
        edges = Qt.Edges()
        if edge & _EDGE_LEFT:
            edges |= Qt.Edge.LeftEdge
        if edge & _EDGE_RIGHT:
            edges |= Qt.Edge.RightEdge
        if edge & _EDGE_TOP:
            edges |= Qt.Edge.TopEdge
        if edge & _EDGE_BOTTOM:
            edges |= Qt.Edge.BottomEdge
        return edges

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
                # 用系统原生缩放：无边框窗口手动 setGeometry 累加会造成整体移位，
                # 且吃不到 Windows 的磁性贴靠/分屏；原生缩放两者都稳。
                handle = self.windowHandle()
                started = handle is not None and handle.startSystemResize(self._qt_edges(self._resize_edge))
                if not started:  # 兜底：没有原生窗口句柄时退回手动跟踪
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
        # 必须先 show 再定位：_position_toast 对「不可见」直接早退，
        # 原来顺序反了 → toast 永远停在 (0,0)，贴在窗口左上角压住标题栏。
        self._toast_label.show()
        self._position_toast()
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
        # 联网抓歌词的线程必须等它自己收尾，否则析构中线程还在跑会告警/崩
        for worker in list(self._lyrics_workers.values()):
            worker.wait(2000)
        self._lyrics_workers.clear()
        # 联网对齐歌词的线程同样要等它收尾（v2.6.6）
        for worker in list(self._align_workers.values()):
            worker.wait(2000)
        self._align_workers.clear()
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
