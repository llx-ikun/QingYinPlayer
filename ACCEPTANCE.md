# 验收对照（ACCEPTANCE）

对照 `DESIGN.md` §10 的 9 条验收标准，逐条给出**测试证据**。

- ✅ = 已有自动化测试覆盖且当前全绿
- 🟡 = 沙箱环境无法验证，需用户在真实 Windows 本机确认（原因见「已知限制」）

全量回归（**232 项 / 16 个独立进程**）：

```bash
cd music-player
env -u PYTHONPATH .venv/Scripts/python.exe run_tests.py
# 每个模块（或测试类）独立进程运行，全部 PASS
```

> 为什么不用 `unittest discover` 单进程跑：`QMediaPlayer` 在 offscreen 无音频后端下，
> 同进程累积 ~15-20 个实例后会在 C++ 层偶发死锁。逐模块/逐类独立进程可彻底规避，
> 属测试环境约束，不是业务缺陷。

## 总览

| # | 验收标准 | 状态 | 主要证据 |
|---|---------|------|---------|
| 1 | 双击 EXE 启动，深色中文界面正常渲染 | 🟡 本机 | build smoke（启动+解码）；UI 装配由 E2E 构造主窗口覆盖；**字体/QSS 真实渲染需本机** |
| 2 | 导入后列表显示标题/艺人/专辑/时长/封面 | ✅ | `test_import_list_row_fields` 等 10 项 |
| 3 | 播放/暂停/切歌/进度拖动/音量 | ✅（🟡 声音） | `test_play_seek_volume_mode` 等 9 项；**声音输出需本机** |
| 4 | 四种播放模式 + 播完自动续播 | ✅ | `test_autoplay_*` 6 项 + `test_queue.py` 10 项 |
| 5 | 歌单：新建/重命名/删除/加歌/移出/拖拽排序 | ✅ | `test_playlist_flow` 等 6 项 + `test_store.py` 4 项 |
| 6 | 歌词：LRC 匹配/同步/点击跳转/内嵌/手动绑定 | ✅ | `test_lyrics_sync` 等 3 项 + `test_lyrics.py` 18 项 |
| 7 | 关闭重开：歌单/设置/上次曲目与位置恢复 | ✅ | `test_restart_restores_state` 等 4 项 |
| 8 | 文件丢失时友好提示不崩溃 | ✅ | `test_missing_file_errors_and_skips` 等 4 项 |
| 9 | 单测 + E2E 全绿；交付双 EXE | ✅ | **232 项**全绿（16 进程）+ `dist/` 双产物 + smoke |

## 逐条明细

### 1. 双击 EXE 启动，深色中文界面正常渲染

- 自动化：`build.py` 的 smoke 步骤验证 EXE 可启动、可解码附带音频（`QingYinPlayer.exe --smoke <音频文件>`），并新增真实平台存活检查；E2E 每次构造真实 `MainWindow`（应用 QSS 深色主题、装配全部控件）。
- 🟡 沙箱为 offscreen 虚拟平台且字体库为空，中文截图全为方块——**真实显示效果必须在本机验证**。

### 2. 导入文件夹/文件后，列表显示标题/艺人/专辑/时长/封面

| 测试 | 断言要点 |
|------|---------|
| `test_e2e::test_import_populates_list` | 导入 5 个多格式夹具，列表行数与「共 N 首」 |
| `test_e2e::test_import_list_row_fields` | **逐字段**：标题、`艺人 · 专辑`、时长 `0:02`；无标签文件回退「文件名 + 未知艺人 · 未知专辑」 |
| `test_e2e::test_drag_import` | 拖拽文件夹 → `dropEvent` → 入库 |
| `test_e2e::test_cancel_import_stops_partially` | 取消导入：扫描器停止、窗口句柄清理、不扫完 |
| `test_metadata.py`（7 项） | MP3/FLAC/WAV/OGG 标签读取、裸文件回退、非音频返回 None |
| `test_covers_scanner.py`（13 项） | 目录展开/去重/跳过系统目录/扩展名大小写；封面缓存、无封面占位图、文件不存在不崩 |

### 3. 播放/暂停/上一首/下一首/进度拖动/音量

| 测试 | 断言要点 |
|------|---------|
| `test_e2e::test_play_seek_volume_mode` | UI 链路：seek→时间标签更新、音量滑条联动、模式循环 |
| `test_e2e::test_next_previous_via_bar` | 播放栏按钮切歌 |
| `test_player::test_play_tracks_changes_track_and_state` | 播放状态机 + track_changed 信号 |
| `test_player::test_pause_resume_stop` | 暂停/恢复/停止/再播放 |
| `test_player::test_seek` | seek 后 position 精确落位 |
| `test_player::test_volume_and_mute` | 音量钳制、静音、调音量自动解除静音 |
| `test_player::test_previous_restarts_track_after_threshold` | 「上一首」3 秒阈值：超阈值回本曲开头、不切歌 |

- 🟡 沙箱无音频渲染设备，position 不自动推进；**声音输出与进度自动推进需本机确认**。

### 4. 播放模式四种切换 + 播完自动续播

- 纯逻辑：`test_queue.py`（10 项）覆盖 loop 回绕、sequential 末尾停止、single 自动重播/手动前进、shuffle 排列与轮次、jump_to、set_mode、空队列。
- 端到端调度（`app/player.py` 的 `_handle_finished` 链路）：

| 测试 | 场景 |
|------|------|
| `test_autoplay_next_sequential` | 顺序播完 → 自动下一首 |
| `test_autoplay_stops_at_end_sequential` | 顺序到末尾 → 停止 |
| `test_autoplay_loop_wraps_to_first` | 列表循环末尾 → 回第一首 |
| `test_autoplay_single_replays_same_track` | 单曲循环 → 重播本曲且回开头 |
| `test_autoplay_shuffle_reshuffles_and_continues` | 随机播完一轮 → 重洗牌继续，队列仍为合法排列 |
| `test_manual_next_at_end_stops` | 手动下一首到末尾 → 停止 |

- 说明：沙箱无音频渲染，EndOfMedia 不会自然到来，测试直接驱动真实信号槽 `_on_media_status(EndOfMedia)`，保证调度逻辑与信号接线均为真实代码路径。

### 5. 歌单：新建/重命名/删除/加歌/移出/拖拽排序

| 测试 | 断言要点 |
|------|---------|
| `test_e2e::test_playlist_flow` | 建单/加歌/视图切换/侧边栏数量/删除 |
| `test_e2e::test_rename_current_playlist_refreshes_header` | **本轮回归**：重命名当前浏览歌单，头部标题+侧边栏同步 |
| `test_e2e::test_rename_playlist_cancelled` | 取消重命名不改数据 |
| `test_e2e::test_playlist_drag_reorder` | 拖拽重排：store 顺序与 UI 列表顺序同步 |
| `test_e2e::test_add_to_playlist_via_menu` | 右键菜单加歌；重复添加不入队并提示 |
| `test_store::test_playlist_crud / test_remove_track_cleans_playlists / test_recent_tracks / test_views` | 资料库/最近播放/移除联动 |

### 6. 歌词：LRC 匹配、同步高亮、点击跳转、内嵌、手动绑定

| 测试 | 断言要点 |
|------|---------|
| `test_lyrics.py`（18 项） | 多时间标签、offset、元数据行、乱序容错、CRLF/BOM、边界索引 |
| `test_e2e::test_lyrics_sync` | 同步模式行数、`update_position` 驱动高亮、**点击歌词 seek 精确认位置（1500ms）** |
| `test_e2e::test_bind_lyrics_manually` | 手动绑定 `.lrc` 优先级最高（patch QFileDialog） |
| `test_e2e::test_embedded_lyrics_fallback` | FLAC 内嵌带时间戳歌词回退 |

### 7. 关闭重开：歌单、设置、上次曲目与位置恢复

| 测试 | 断言要点 |
|------|---------|
| `test_e2e::test_restart_restores_state` | 音量 0.33、模式 shuffle、上次曲目、列表完整 |
| `test_e2e::test_restart_restores_last_position` | **断点 1200ms 落位**、恢复后不自动播放 |
| `test_store::test_persistence_roundtrip / test_settings_roundtrip / test_corrupt_file_backed_up` | JSON 往返、设置白名单、损坏数据自动备份 |

### 8. 文件丢失时友好提示不崩溃

| 测试 | 断言要点 |
|------|---------|
| `test_player::test_missing_file_errors_and_skips` | 幽灵文件 → error 信号（含文件名）→ 标记 broken → 跳过播下一首 |
| `test_player::test_consecutive_broken_files_are_skipped` | 连续两个坏文件的跳过链，各报一次错 |
| `test_covers_scanner::test_missing_file_placeholder` | 封面缺失返回占位图不崩 |
| `test_covers_scanner::test_unparsable_file_falls_back_to_filename` | 无法解析的音频以文件名兜底入库，不阻断整次导入 |

### 9. 单测 + E2E 全绿；交付 EXE

- 全量回归：**91 项 OK**（单测 74 + E2E 17），命令见文首。
- 产物：`dist/QingYinPlayer.exe`（onefile）+ `dist/QingYinPlayer-Portable/`（onedir，免安装）。
- 冒烟：`QingYinPlayer.exe --smoke <音频文件>` 验证启动 + FFmpeg 解码；真实平台（非 offscreen）存活检查确认窗口创建链路无崩溃。

## 本轮（v1.1）修复的缺陷

1. **重命名当前浏览中的歌单，列表头部标题不刷新**（`ui/main_window.py:_playlist_action` 的条件刷新）。
   回归：`test_rename_current_playlist_refreshes_header`。
2. **随机播放播完一轮后，重新洗牌产生重复曲目**（`app/queue.py:_shuffled_from(-1)` 切片公式在哨兵值下复制了队列）。
   回归：`test_queue::test_shuffle_permutation_and_cycle` 重排后排列断言 + `test_autoplay_shuffle_reshuffles_and_continues` 队列断言；另以 200 轮随机重排验证无重复。

新增测试 24 项：E2E +9、播放器 +9、扫描器/封面 +6（另强化 2 项既有断言）。

## v2.0 UI 改版增量验收

对照 `DESIGN.md` §12，v2.0 新增/变更项逐条给证据（全量 **122 项** 全绿，命令见下）：

```bash
cd music-player
env -u PYTHONPATH .venv/Scripts/python.exe run_tests.py   # 逐模块/逐类独立进程，122 项 OK
env -u PYTHONPATH .venv/Scripts/python.exe -m ruff check .  # 静态检查干净
```

| 验收项 | 状态 | 证据 |
|-------|------|------|
| 双主题（默认深色，浅色 QQ 绿 `#31c27c`） | ✅ | `TestE2EV2::test_theme_switch_applies_and_persists`（QSS 含强调色 + 重启保持）、`test_float_bar_theme_toggle` |
| 无边框圆角窗口 + 自定义标题栏 | ✅（🟡 真实拖拽手感） | `test_titlebar_close_button`、`test_titlebar_maximize_toggle`（is_maximized 属性）；真实贴边/缩放需本机确认 |
| 标题栏导航（前进/后退） | ✅ | `test_view_history_back_forward`、`test_nav_buttons_disabled_without_history` |
| 全局搜索（标题栏搜索框） | ✅ | `test_search_from_title_bar`、`test_search_filters` |
| 「我喜欢」收藏（行内心 + 播放栏心） | ✅ | `test_row_heart_toggles_favorite`、`test_favorites_view_and_player_bar_heart`、`test_favorites_survive_restart` + `test_store` 收藏 5 项 |
| 队列浮层跳转 | ✅ | `test_queue_panel_jump` |
| 昵称修改 | ✅ | `test_nickname_change` |
| toast 提示 | ✅ | `test_toast` |
| 设置框（昵称/主题/统计） | ✅ | `test_settings_dialog_signals` |
| 浮动工具条（主题/正在播放/数据目录/设置） | ✅ | `test_float_bar_inside_window`、`test_float_bar_theme_toggle` |
| 视图历史初始项可后退 | ✅ | `test_view_history_back_forward`（初始视图入栈修复） |
| 文本省略（ElidedLabel） | ✅ | `tests/test_widgets.py` 7 项（延后省略 + full_text + 销毁安全） |
| 视觉自审（双主题 × 7 状态） | ✅（🟡 真机） | `tools/shot.py` 真实平台截图：深/浅 × {曲库/播放中/歌词/队列/设置/最大化/空库}，中文渲染/布局/激活态/收藏心均正常 |

## v2.1 增量验收（本地视频导入与画面播放）

对照 `DESIGN.md` §13，v2.1 新增项逐条给证据。全量回归 **157 项** 全绿（既有 122 + 新增 35），`ruff check .` 干净。

```bash
cd music-player
env -u PYTHONPATH .venv/Scripts/python.exe run_tests.py   # 11 个独立进程，157 项 OK
env -u PYTHONPATH .venv/Scripts/python.exe -m ruff check .  # 静态检查干净
```

| 验收项 | 状态 | 证据 |
|-------|------|------|
| 本地视频导入（mp4/mkv/mov/avi/wmv/flv/webm/m4v） | ✅ | `test_video.py::TestMediaScan`（混合扫描/单文件/旧别名/大写扩展名）、`TestE2EVideo.test_import_video_into_library` |
| 视频行显示「视频」徽标，音频不回归 | ✅ | `test_video.py::TestBadge`、`TestE2EVideo.test_video_row_shows_video_badge` |
| 双击视频进入视频页并播放画面 | ✅ | `TestE2EVideo.test_double_click_video_enters_video_page`、`test_video_frames_are_painted`（sink 收帧 + widget 出现非黑像素） |
| 视频页播放/暂停/切歌/进度/音量/队列/收藏与音频一致 | ✅ | `test_video_supports_favorite_and_queue`、`test_back_to_list_keeps_playing` |
| 音乐模式 ↔ 视频模式切换不中断声音/进度/曲目 | ✅ | `test_music_mode_switch_keeps_playback`（`current_track`/`position_ms`/`source()` 三重断言） |
| 自动切歌按曲目类型切视图 | ✅ | `test_auto_switch_view_by_track_type` |
| 返回列表声音继续 | ✅ | `test_back_to_list_keeps_playing` |
| `F11` 全屏 / `Esc` 退出；全屏优先于清空搜索 | ✅ | `test_f11_shortcut_toggles_fullscreen`、`test_fullscreen_toggle_keeps_playback`、`test_escape_exits_fullscreen_before_clearing_search` |
| 时长加载后回填并落盘（mutagen 读不出 AVI 时长） | ✅ | `test_video_duration_backfilled_after_load` |
| 旧数据无损兼容（无 v2.1 字段的 JSON 仍可用） | ✅ | `test_video.py::TestStoreCompatibility`（旧 JSON 加载 + 视频 roundtrip） |
| 画面渲染（QVideoSink 自绘，非原生 surface） | ✅（🟡 真机） | `shots/dark-video.png`、`shots/light-video.png`、`shots/dark-video_fullscreen.png` 真实 windows 平台；浅色/深色均中文正常、4:3 等比居中、letterbox 正确、全屏无残留 UI |
| 播放器绑定 sink 长期稳定（切模式不重连媒体源） | ✅ | `test_video_output_bound_to_player` |

### v2.1.1 窗口图标修复（2026-10-26）

| 验收项 | 状态 | 证据 |
|-------|------|------|
| 窗口/任务栏图标不再显示「图片找不到」占位符 | ✅ | `tests/test_icon.py::test_generate_produces_spec_compliant_ico`（ICO 目录项 planes/bitcount 全为 0，数据为 PNG）；`main.py` 显式 `setWindowIcon` |
| 开发态与打包态均能定位并应用图标 | ✅ | `test_icon_resolves_at_runtime`（`_resolve_app_icon` 冻结态取 `sys._MEIPASS`、否则取本地 `assets/app.ico`） |
| 图标可在运行时被 Qt 正常加载（7 尺寸全非空） | ✅ | `test_qicon_loads_all_sizes` |
| 全量回归 / 静态检查 | ✅ | 11 进程 **160 项全绿**（157 + 新 3）；`ruff check .` 干净 |

**修复的根因**：`build.py:generate_icon` 写 ICO 目录项时用了 `planes=1, bitcount=32`（BMP 字段值），违反 ICO 规范——PNG 压缩图像这两项必须为 0。资源管理器常容忍，但 Windows 任务栏/标题栏图标加载器更严格会拒绝，叠加 `main.py` 未曾 `setWindowIcon`，窗口图标退化为占位符。已改为 0/0，并对打包产物 `--add-data` 带上图标，运行时显式设置。

### v2.1.2 导入弹窗关闭修复 + 浮动工具条改版（2026-10-26）

| 验收项 | 状态 | 证据 |
|-------|------|------|
| 导入完成后点「关闭」可关闭弹窗 | ✅ | `tests/test_dialogs.py::test_close_after_finish_closes_dialog`（`result()==Accepted`） |
| 扫描中点「取消」仍触发取消导入（未误关） | ✅ | `test_cancel_before_finish_emits_cancelled`（emit cancelled） |
| finish 后状态正确（文案/明细/`_finished`） | ✅ | `test_finish_sets_state` |
| 浮动条主题为开关式切换按钮，状态随主题联动 | ✅ | `test_e2e.TestE2EV2.test_float_bar_theme_toggle`（checkable + `isChecked()` 随深/浅切换） |
| 浮动条其余为图标+文字（正在播放/数据目录/设置） | ✅ | 同上（三按钮 `text()` 断言） |
| 浮动条加宽后不压封面 | ✅ | 实测条宽 ~294px，`player_bar` 左缩进 330，结束于 x≈310 |
| 全量回归 / 静态检查 | ✅ | 13 进程 **163 项全绿**（160 + 新 3）；`ruff check .` 干净 |
| 双 EXE 重建 | ✅ | smoke + 真实平台 8s 存活检查通过（单文件 54.9MB / 目录版 2.2MB） |

**修复的根因**：
① **关闭失效**：`ImportProgressDialog` 完成后 worker 已结束，底部按钮仍连接 `cancelled → worker.cancel()`；`ScannerWorker.cancel()` 仅 `requestInterruption()`（no-op），`on_cancelled(dialog.reject)` 永不触发，弹窗关不掉。改为 dialog 内 `_finished` 标志 + `_on_button()`：完成后直接 `accept()` 关闭。
② **浮动条改版**：主题由纯图标按钮改为开关式 `#ThemeToggle`（checkable），其余改为图标+文字 `#FloatTextBtn`；文字按钮使条宽增至 ~294px，故 `player_bar` 左缩进由 190 扩到 330。

### v2.1.3 播放栏超宽修复（2026-10-26）

| 验收项 | 状态 | 证据 |
|-------|------|------|
| 播放栏最小宽度 ≤ 窗口最小宽度（不再超约束/抖动） | ✅ | `tests/test_widgets.py::TestPlayerBarLayout::test_player_bar_fits_min_window`（`minimumSizeHint ≤ 1100`）；实测 1340→1098 |
| 浮动条加宽后不压封面 | ✅ | `test_float_bar_not_overlap_cover`（16 + 浮动条宽 ≤ 左缩进） |
| 副标题能显示完整「艺人 · 专辑」 | ✅ | 默认窗 1280 下信息列 182px（> 90px 需求）；缩进 330→312、seek 380→200 释放宽度 |
| 全量回归 / 静态检查 | ✅ | 13 进程 **165 项全绿**（163 + 新 2）；`ruff check .` 干净 |
| 双 EXE 重建 | ✅ | smoke + 真实平台 8s 存活检查通过 |

**修复的根因**：v2.1.2 把 `player_bar` 左缩进 190→330 给浮动条让位，使 `PlayerBar.minimumSizeHint` 达 **1340px**，**超过默认窗 1280 / 最小窗 1100** → 信息列（stretch）被挤到 0（副标题全省略）、布局在约束边界反复重算导致窗口抖动。压缩固定宽元素（seek 380→200、音量 90→70、两处 addSpacing 20→8）、左缩进 330→312 后，min 降至 **1098 ≤ 1100**，任何尺寸下不再超约束。
> 附带：进度条 0:00↔0:02 来回跳的另一层原因是导入的「晴天」为 **2 秒测试片段**，循环模式每 2 秒重播归零（锯齿），真实长曲不会如此。

### v2.1.4 列表页视觉统一 + 排序增强（2026-10-26）

| 验收项 | 状态 | 证据 |
|-------|------|------|
| 可按**大小**排序（升/降） | ✅ | `tests/test_sorting.py` 大小双向 + 未知大小恒排最后；`test_e2e.TestE2EV2.test_sort_by_size_desc` 断言 `_displayed` 体积逆序 |
| 可按**时长**排序（升/降） | ✅ | `test_duration_both_directions` + `test_sort_by_duration_asc_then_desc` |
| 可按**导入时间**排序（升/降） | ✅ | `test_added_both_directions` |
| 提供「**最近导入**」独立选项 | ✅ | `test_recent_import_entry_exists`；`test_recent_import_is_default_and_newest_first`（下拉文案 = 「最近导入」） |
| 升降序可切换、当前排序清晰展示 | ✅ | 13 条预设一一对应「维度+方向」，下拉文案即当前排序；`test_each_dimension_has_both_directions`、`test_sort_combo_lists_every_preset` |
| 列表显示**文件大小**列 | ✅ | `test_row_shows_size_column`（820 KB / 8.4 MB / 未知显示 `--`）+ `test_filesize.py` 9 项 |
| 列头与数据行**逐列对齐** | ✅ | `TestTrackListAlignment::test_columns_align_pixel_by_pixel`（套 QSS 后比较 10 列全局 X，Δ=0）+ `tools/probe_columns.py` 实测全部通过 |
| 页头层次（标题 > 统计 > 控件） | ✅ | `test_header_shows_total_duration`、`test_header_hides_stats_when_empty`；截图人工审阅 |
| 固定尺寸控件不再虚胖 | ✅ | `TestThemeSizes::test_icon_buttons_keep_declared_size`（40×40 正圆 / 34×34 / 46×46） |
| 浮动条完整可见、不压封面 | ✅ | `test_float_bar_fits_player_bar_indent`；截图确认「正在播放/数据目录/设置」文字完整 |
| 侧边栏昵称不被截断 | ✅ | `test_sidebar_nickname_not_truncated`（56→156px） |
| 不影响现有功能 | ✅ | 全量回归 15 进程 **212 项全绿**（原有 165 项全保留）；`ruff check .` 干净 |
| 双 EXE 重建 | ✅ | smoke + 真实平台 8s 存活检查通过 |

**修复的 4 个既有缺陷（排查附带发现）**：
① **列头错位**：列头比行少 2 个间距位、且 `QListWidget::item` 的 8px margin 与行内容内边距叠加后未在列头补偿；更关键是弹性列宽度受 `sizeHint`（列头「歌曲」vs 行内歌名）影响而漂移。改为同一套槽位 + `sizePolicy=Ignored` 后 Δ 全为 0。
② **按钮尺寸虚胖**：基础 `QPushButton{padding:6px 10px}` 叠加在 `min/max-width` 上，34→54、40→60、46→66、36→58；播放键 borderRadius 失效变椭圆、行内按钮多占 40px 直接导致列漂移、浮动条超宽。
③ **浮动条被裁**：绝对定位的子控件不会自动取 `sizeHint` 宽度，`_position_float_bar()` 只 `move` 不 `adjustSize`，宽度停在默认 100px，图标+文字按钮全被父控件裁掉。
④ **昵称截断**：徽标 `setFixedWidth(56)` 使 `QVBoxLayout` 的最大宽度被压到 56，父布局不再分配余量，「音乐爱好者」被省略成「音乐爱…」。

### v2.1.5 浅色主题改浅蓝 + 移除前进/后退按钮（2026-10-26）

| 验收项 | 状态 | 证据 |
|-------|------|------|
| 浅色主题为**浅蓝**（不是原来的 QQ 绿） | ✅ | `LIGHT.ACCENT #3b82f6`、`ACCENT_HOVER #2f74ea`、`ACCENT_DIM #2563eb`、`ACCENT_SOFT #e7f0fe`；底板 `#f3f6fc`/`#ffffff`/`#eef3fb`/`#e3ecfb`/`#dde5f3` 全带蓝调 |
| 浅色与深色主题**同色系** | ✅ | `test_theme.py::test_accent_is_blue_dominant`（两主题强调色均为蓝通道主导）、`test_light_surfaces_are_blue_tinted` |
| 旧 QQ 绿**无残留** | ✅ | `test_legacy_green_is_gone` 断言 `#31c27c/#2bb673/#31b96f/#2fa86d/#4ecb8c` 不出现在构建出的 QSS 中 |
| 文字对比度达标 | ✅ | `test_body_text_contrast`（正文 ≥7:1）、`test_accent_readable_on_surface` / `test_on_accent_readable_on_accent`（≥3:1）、`test_accent_soft_is_a_tint_not_a_block` |
| 标题栏**移除 ← 后退 / → 前进**按钮 | ✅ | `test_e2e.TestE2EV2::test_title_bar_has_no_back_forward_buttons`（`back_btn`/`fwd_btn` 已不存在，刷新 ↻ 仍可用）；截图人工审阅 |
| 视图历史功能**不丢失** | ✅ | `test_view_history_shortcuts_still_bound`：`Alt+←` / `Alt+→` 仍绑定；`_history_pos` 按位置断言，不再依赖按钮 enabled 状态 |
| 歌词常态色**随主题切换** | ✅ | `tests/test_widgets.py::TestLyricsThemeColor` 4 项（浅色/深色各自等于 `TEXT_DIM`、同进程先浅后深必须变色、纯文本歌词同样跟随）。**反向验证**：把颜色重新冻结在深色值后该组 3 项立即失败 |
| 不影响现有功能 | ✅ | 全量回归 **16 进程 232 项全绿**（原有 212 项全保留）；`ruff check .` 干净 |
| 双 EXE 重建 | ✅ | `build_v215.log`：smoke + 真实平台 8s 存活检查通过 |
| 图标回归不改写仓库资产 | ✅ | `tests/test_icon.py` 5 项（新增 `test_generate_does_not_touch_repo_asset` + `test_repo_icon_is_usable`）；测试一律写临时目录 |

**修复的 3 个根因（都是「看起来改了其实没生效」）**：

1. **歌词颜色被冻结在 import 时**：`_NORMAL = QColor(TEXT_DIM)` 是类属性，在模块导入那一刻求值（当时是深色主题），切到浅色主题后仍是深灰 —— 浅底上对比度不足。改为 `_normal_color()` 在用时取 `current_theme().TEXT_DIM`。
2. **写库脚本静默不落盘**：`LibraryStore()` 不传路径时 `_path = None`，`load()` / `save()` 全是空操作（`open(None)` 抛的 `TypeError` 被 `except Exception` 吞掉）。所以上一次「删除失效条目」实际什么都没做，曲目自然又出现了。现在 `__init__` 明确写了「`path=None` = 纯内存 store」，`load()` 增加 `if not self._path: return` 前置守卫，不再走异常吞噬分支。
3. **图标测试改写仓库资产**：回归默认 offscreen，字体库为空，`♫` 画不出来；旧 `test_icon` 直接调 `generate_icon()` 默认路径，把 `assets/app.ico` 从 14885 B 覆盖成 11515 B 的空白图标（打包/提交后即「窗口图标空白」复发）。`generate_icon` 现支持 `out_path`，测试一律写临时目录，并断言仓库资产哈希不变。

### 测试夹具与用户目录隔离（承接用户 10-26 21:35 要求）

用户要求 `tests/fixtures/我的音乐` 只能放他本人提供的音乐，不得生成或混入合成音频。此前 `ensure_fixtures()` 直接往该目录写 6 个合成文件 → ① 每次跑测试都被塞满；② 应用导入过这些路径后，夹具被清理时库里留下失效条目。

| 验收项 | 状态 | 证据 |
|-------|------|------|
| 合成夹具**不再写入** `tests/fixtures/我的音乐` | ✅ | `make_fixtures.py` 新增 `GENERATED = tests/fixtures/_generated`，音频/视频/临时封面/`.done` 全部落到 `_generated/` 下 |
| 用户目录**保持为空** | ✅ | `test_metadata.py::TestFixtureIsolation::test_user_dir_stays_empty_after_ensure`（再调一次 `ensure_fixtures()` 后仍断言 `listdir == []`） |
| 中文路径编码覆盖不丢 | ✅ | 生成目录仍为 `_generated/我的音乐`、`_generated/我的视频`（中文段保留） |
| 夹具本身完整 | ✅ | `test_generated_audio_files_all_exist`（6 个文件）；`test_generated_audio_is_not_inside_user_dir` |
| `build.py` 不再硬编码夹具路径 | ✅ | 改为 `os.path.join(ensure_fixtures(), "晴天 - 周杰伦.mp3")`，随生成目录迁移自动跟随 |

**用户库清理与导入（本机 `%APPDATA%\轻音播放器\data.json`，每次改动前均有 `.bak-<时间戳>` 备份）**：
- 删除指向已清空夹具的失效条目「晴天」（`tests/fixtures/我的音乐/晴天 - 周杰伦.mp3`），同时清空指向它的 `last_track_id` / `last_position_ms`。
- 导入用户指定的 `C:\Users\西\Music\Chrissy Costanza _ HOYO-MiX - Blazing Heart (英文版).flac`：标题 `Blazing Heart (英文版)`、艺人 `Chrissy Costanza/HOYO-MiX`、专辑 `原神-灼火之心 Blazing Heart`、时长 **177.98 s**、格式 `flac`、内嵌封面 83483 B、文件大小 **38.2 MB**（`tools/check_media.py` 实测 `LoadedMedia`、无解码错误）。

## v2.0 修复的缺陷

1. **ElidedLabel 同步省略截断文本**：列表行创建时布局先给过渡宽度，同步省略把「新名字」截成「新…」。改为事件循环空闲时省略（0ms 单次定时器合并连续 resize），测试同步刷新后可读到完整文本。
2. **视图历史初始项缺失**：`_history` 初值 `[]`，初始视图经 `set_view` 同视图跳过而不入栈，用户从初始视图导航后「后退」回不到起点。改为 `_history = [初始视图]`。
3. **图标绑定强引用累积**：`_bindings` 用强引用持有已销毁 widget，跨窗口累积后 `refresh_icons` 对半销毁 Shiboken 对象 `setIcon` 在 C++ 层偶发 hang。改 weakref 持有，销毁自动失效。
4. **QMediaPlayer offscreen 累积死锁**（测试环境）：同进程内实例累积 ~15-20 个后 Qt 多媒体后端 C++ 层死锁。以 `run_tests.py` 逐模块/逐类独立进程规避，非业务代码缺陷。

## 已知限制

- **m4a/aac 无真实样本验证**：mutagen MP4 分支有代码实现但无测试夹具，交付标注 🟡。
- **声音输出 / 进度自动推进 / 真实字体渲染**：沙箱无音频设备、无音频渲染、offscreen 字体库为空，相关条目需用户本机确认。
- offscreen 截图中文显示为方块属环境限制，非 UI 缺陷（视觉验证需真实 windows 平台）。
- **v2.1 视频真实音频输出 / 拖拽手感 / 无边框拖拽贴边**：沙箱无音频渲染与真实显卡链路，画面已用自造 MJPEG AVI 夹具在真实平台验证渲染正确，但「声音」与「拖拽/全屏手感」需用户本机双击确认。
- **视频编码兼容性以 Qt 自带 FFmpeg 后端为准**：容器可导入 ≠ 该容器内所有编码都可解码；不支持的编码走既有 toast/跳过链，不承诺全部可播。
