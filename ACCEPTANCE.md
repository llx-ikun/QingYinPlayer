# 验收对照（ACCEPTANCE）

对照 `DESIGN.md` §10 的 9 条验收标准，逐条给出**测试证据**。

- ✅ = 已有自动化测试覆盖且当前全绿
- 🟡 = 沙箱环境无法验证，需用户在真实 Windows 本机确认（原因见「已知限制」）

全量回归（**240 项 / 17 个独立进程**）：

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
| 9 | 单测 + E2E 全绿；交付双 EXE | ✅ | **240 项**全绿（17 进程）+ `dist/` 双产物 + smoke |

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
| 不影响现有功能 | ✅ | 全量回归 **17 进程 234 项全绿**（原有 212 项全保留）；`ruff check .` 干净 |
| 双 EXE 重建 | ✅ | `build_v215.log`：smoke + 真实平台 8s 存活检查通过 |
| 图标回归不改写仓库资产 | ✅ | `tests/test_icon.py` 5 项（新增 `test_generate_does_not_touch_repo_asset` + `test_repo_icon_is_usable`）；测试一律写临时目录 |
| 冒烟自检不写用户曲库 | ✅ | `tests/test_smoke_isolation.py` 2 项（独立进程跑 `main.py --smoke`，APPDATA 预置哨兵 data.json，断言逐字节不变）；**反向验证**：移除隔离后立即 2 红 |

**修复的 3 个根因（都是「看起来改了其实没生效」）**：

1. **歌词颜色被冻结在 import 时**：`_NORMAL = QColor(TEXT_DIM)` 是类属性，在模块导入那一刻求值（当时是深色主题），切到浅色主题后仍是深灰 —— 浅底上对比度不足。改为 `_normal_color()` 在用时取 `current_theme().TEXT_DIM`。
2. **写库脚本静默不落盘**：`LibraryStore()` 不传路径时 `_path = None`，`load()` / `save()` 全是空操作（`open(None)` 抛的 `TypeError` 被 `except Exception` 吞掉）。所以上一次「删除失效条目」实际什么都没做，曲目自然又出现了。现在 `__init__` 明确写了「`path=None` = 纯内存 store」，`load()` 增加 `if not self._path: return` 前置守卫，不再走异常吞噬分支。
3. **图标测试改写仓库资产**：回归默认 offscreen，字体库为空，`♫` 画不出来；旧 `test_icon` 直接调 `generate_icon()` 默认路径，把 `assets/app.ico` 从 14885 B 覆盖成 11515 B 的空白图标（打包/提交后即「窗口图标空白」复发）。`generate_icon` 现支持 `out_path`，测试一律写临时目录，并断言仓库资产哈希不变。
4. **构建自检污染用户曲库**：`build.py` 每个产物都跑 `exe --smoke <音频>`，而 smoke 分支会 `store.add_or_update()` 到 `%APPDATA%\轻音播放器\data.json` —— 用户真实曲库。于是**每次构建都往库里塞一条合成「晴天」**，退出时还覆盖 `last_view`/`last_track_id`。这才是「晴天反复出现」的最终真相（前两次清理只清了表象）。现在 `--smoke` 在创建窗口前把 `APPDATA` 指向临时目录，`_real_platform_check()` 也注入隔离 APPDATA。

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

### v2.1.6 播放栏视觉打磨（2026-10-27）

| 验收项 | 状态 | 证据 |
|-------|------|------|
| 循环/单曲循环图标能读作「循环」而非「刷新」 | ✅ | `ui/icons.py` 重画为上下横线 + 两端反向箭头；`tools/probe_player_bar.py` + 72px 图标表目视 |
| 随机播放图标不再是碎线 | ✅ | 改为两条交叉车道 + 右端箭头（原为 7 段互不相连线段） |
| **上一首/下一首方向正确** | ✅ | prev = `\|◀`、next = `▶\|`（此前画反：prev 是 ▶\|，语义与图形相反）；图标表逐格目视 |
| 进度手柄在浅色主题下**可见** | ✅ | `TestSliderKnob::test_handle_visible_on_light` / `..._on_dark`（value=0 时扫手柄区必须存在饱和蓝像素）。**反向验证**：改回 `background:#ffffff` 后 2 项立即失败 |
| 手柄是**正圆**而非圆角方块 | ✅ | `test_handle_round_not_square`（手柄外接框四角不得被钮芯色填满）；QSS `border-radius = (width+2×border)/2`、`margin` 保证盒高 ≥ 手柄总高 |
| 时间标签贴住滑块两端、两侧对称 | ✅ | `test_time_labels_snug_to_slider`（左端 AlignRight、右端 AlignLeft、均 `#TimeLabel` 12px） |
| 播放键有柔和投影、随主题重染 | ✅ | `QGraphicsDropShadowEffect` + `PlayerBar.refresh_theme()`（`main_window._apply_theme` 调用）；截图中蓝色圆下方可见光晕 |
| 控制行与进度行有呼吸空间 | ✅ | 间距 2→6px；截图确认不再贴边 |
| 长标题不得顶爆播放栏最小宽度 | ✅ | `test_player_bar_fits_min_window_with_long_title`（实测 **1042 ≤ 1100**，修复前 1185）。**反向验证**：移除 `ElidedLabel.minimumSizeHint` 覆盖后立即失败 |
| 不影响现有功能 | ✅ | 全量回归 **17 进程 240 项全绿**；`ruff check .` 干净 |
| 双 EXE 重建 | ✅ | smoke + 真实平台 8s 存活检查通过 |

**修复的 2 个功能性缺陷（不是审美问题）**：

1. **上一首/下一首图标方向画反**：`_paint("prev")` 的三角朝右、竖线在右（▶|），`next` 恰好相反。按钮语义与图形相反，用户点「上一首」看到的是「前进」符号 —— 一直存在，靠 72px 图标验收表才发现。
2. **进度手柄在浅色主题下隐形**：手柄是 `background:#ffffff` + `1px solid BORDER`，浅色主题底色也是白 → 只剩一圈极淡灰边，等于看不见手柄在哪。改为强调色实心圆 + SURFACE 外环。

### v2.1.7 左下浮动工具条美化（2026-10-27）

| 验收项 | 状态 | 证据 |
|-------|------|------|
| 三个入口读成**一组工具**而非三个输入框 | ✅ | 结构改为 `QWidget#FloatTray` 分段托盘内嵌三个透明入口；`test_entries_share_one_tray`（三者 parent 均为 tray） |
| 圆角**不再是直角** | ✅ | 根因是 `border-radius:16px` 配 28px 高（超短边一半 Qt 静默退化）。现按钮 10 / 托盘 12 / 主题钮 17；`test_text_button_radius_within_half_height`（10 ≤ 半高 15）。**反向验证**：改回 16px 立即失败 |
| 主题按钮是正圆且与托盘同高 | ✅ | `test_theme_toggle_is_a_circle`（17 ≥ 18−1，两者均 36px）；截图中与托盘上下沿齐平 |
| 两主题下主题按钮**不再长得不一样** | ✅ | 去掉 `:checked` 强调色边框（图标已表明目标主题），底座统一 `SURFACE` + `BORDER` |
| 悬停有可辨反馈 | ✅ | `test_hover_fill_is_distinguishable`（通道差 ≥ 12，实测浅 28 / 深 20）；`tools/probe_float_bar.py --hover dir` 预览胶囊几何 |
| 悬停时图标跟着点亮 | ✅ | `_HoverIconButton.enter/leaveEvent` 重绑颜色角色（QSS `color` 染不动 QIcon） |
| 三个入口空隙均匀 | ✅ | 等内边距 9px + 内容宽（原强制等宽 78px 使「设置」两侧空出一截）；截图 4 倍目视 |
| 浮动条不压播放栏封面、内容不被裁 | ✅ | `test_float_bar_fits_player_bar_indent`（16 + 288 = 304 ≤ 312；每个按钮 `sizeHint().width() > 40`） |
| 不影响现有功能 | ✅ | 全量回归 **17 进程 244 项全绿**；`ruff check .` 干净 |
| 双 EXE 重建 | ✅ | smoke + 真实平台 8s 存活检查通过 |

## v2.1.8 增量验收（浮动条对齐 / 主题钮上移 / 版本号右下角）

| 需求 | 状态 | 证据 |
|---|---|---|
| 浮动条**对齐**侧边栏，不跨进内容区 | ✅ | 宽 288 → **224**（= 248−24），右缘 12+224 = **236** = 侧栏内容右边界；`test_width_matches_sidebar_content`、`test_float_bar_inside_window`（右缘 ≤ 236） |
| 主题按钮**往上调** | ✅ | `FloatBar` 单行 → 上下两排（上圆钮 / 下托盘），圆钮左缘与托盘左缘都对齐侧栏内容左边界 12；`test_float_bar_not_overlap_cover`（圆钮 top < 托盘 top） |
| 三个入口文字不被截断 | ✅ | 托盘三等分 + 字号 11 / 内边距 4，224px 内放下「正在播放 / 数据目录 / 设置」（`probe_float_bar.py` 4 倍目视） |
| 版本号放**右下角** | ✅ | 侧栏底部删除 → 右下角 `QLabel#VersionLabel`（10px、TEXT_DIM），随 resize/show/主题切换重定位；`test_version_label_at_bottom_right`（靠右、贴底、侧栏内无版本号） |
| 不压播放栏封面 / 不影响最小宽 | ✅ | 右缘 236 ≤ 播放栏左缩进 312；`test_float_bar_fits_player_bar_indent` |
| 不影响现有功能 | ✅ | 全量回归 **17 进程全绿**；`ruff check .` 干净 |
| 双 EXE 重建 | ✅ | smoke + 真实平台 8s 存活检查通过 |

## v2.1.9 增量验收（导入即复制：受管理曲库）

| 需求 | 状态 | 证据 |
|---|---|---|
| 导入 = **把文件复制进软件** | ✅ | 曲库存于 `%APPDATA%/轻音播放器/library/`；`test_copies_file_into_library`（原文件仍在、副本内容一致） |
| 曲目与原文件解耦 | ✅ | 导入后 `Track.path` 指向曲库副本；e2e `test_import_copies_files_into_library`（5 首全在曲库内且文件存在） |
| 重复导入不占第二份空间 | ✅ | `file_signature`（size+首尾 64KB）去重；`test_same_content_is_deduped`（第二次 `copied=False`、目录仅 1 个文件） |
| 同名不同内容不覆盖 | ✅ | 追加 8 位指纹后缀；`test_same_name_diff_content_not_overwritten`（2 个文件、内容各自完整） |
| 同名 `.lrc` 歌词一并进曲库 | ✅ | `test_sidecar_lrc_copied`；回归抓到的真实缺陷（只复制媒体会让自动歌词失效）→ 修复后 `test_lyrics_sync` 恢复 |
| 曲库已有歌词不被覆盖 | ✅ | `test_existing_lrc_not_overwritten`（再次导入不覆盖用户手动换过的歌词） |
| 失败不留半成品 | ✅ | `.part` + `os.replace` 原子落盘；`test_no_partial_file_left_behind` |
| 非法文件名安全 | ✅ | `safe_stem` 过滤 `< > : " / \| ? *`；`test_safe_stem_strips_illegal_chars` |
| 复制失败不中断导入 | ✅ | `ScannerWorker.failed` 计数 + toast 提示；不传 `library_dir` 时维持旧行为（`test_scanner_without_library_keeps_original_path`） |
| 移出资料库不留孤儿副本 | ✅ | 曲库内副本随移除删除；外部老条目不动（对话框文案自动区分） |
| 不影响现有功能 | ✅ | 全量回归 17 进程全绿；`ruff check .` 干净 |
| 双 EXE 重建 | ✅ | smoke + 真实平台 8s 存活检查通过 |

## v2.2 增量验收（歌词联网补全 + 外观自定义）

### 歌词

| 需求 | 状态 | 证据 |
|---|---|---|
| 本地没有歌词时自动找到歌词 | ✅ | 5 级来源：手动绑定 → 同名 `.lrc` → 内嵌 → 本地缓存 → 联网（LRCLIB）；e2e `test_online_lyrics_fetched_once_then_cached` |
| 本地已有歌词时不联网 | ✅ | e2e `test_local_lyrics_win_over_online`（假线程记录启动次数 = 0） |
| 匹配结果离线也能看 | ✅ | 写 `<track_id>.lrc` 到 `lyrics_cache/`；上例清掉内存缓存后重新加载仍显示歌词 |
| 不配错歌（宁可没有） | ✅ | `pick_best` 身份门槛：无歌名/艺人/时长信号一律丢弃；`test_rejects_unrelated_song`、`test_skips_instrumental` |
| 同名翻唱/纯音乐不误配 | ✅ | `instrumental` 候选跳过；`test_exact_duration_alone_is_enough`（时长完全一致才算同一录音） |
| 同一首只请求一次 | ✅ | `_online_attempted` 集合；e2e 连续加载两次只启动一个线程 |
| 切歌后旧结果不串词 | ✅ | 回调比对 `current_track.id`；e2e `test_online_result_ignored_for_other_track` |
| 断网/脏数据不影响播放 | ✅ | 任何异常降级为 None；`test_swallows_network_error`、`test_swallows_json_garbage`、`test_tolerates_garbage` |
| 可以关闭联网 | ✅ | 设置 → 歌词与统计；`test_online_lyrics_respects_setting_and_skips_video`（关闭后不启动线程）、开关落盘 |
| 视频不抓歌词 | ✅ | `track.is_video` 直接跳过 |

### 外观（强调色 / 字号）

| 需求 | 状态 | 证据 |
|---|---|---|
| 强调色可自定义 | ✅ | 6 个预设 + 取色器 + 「随主题」；`test_accent_applies_and_persists`（QSS 里出现该色、落盘、重启保持） |
| 只选一个色值就够用 | ✅ | `derive_accent` 派生 hover/dim/soft/on_accent；`test_hover_and_dim_are_distinguishable`（通道差 ≥12） |
| 任何颜色下前景都可读 | ✅ | `ON_ACCENT` 按白字对比度是否 ≥3:1 选白/近黑；`test_on_accent_contrast_for_any_accent`（8 个极端色） |
| 脏数据不炸 | ✅ | 空/非 hex/三位缩写 → 回落主题默认；`test_invalid_accent_falls_back_to_theme_default` |
| 切主题不丢自定义色 | ✅ | `set_theme` 重派生；e2e `test_accent_survives_theme_switch` |
| 字号可调 | ✅ | 四档（较小/标准/较大/特大）；`test_scaling_multiplies_every_font_size`（13→17px 等比例） |
| 字号不会把布局搞坏 | ✅ | 夹取 0.85~1.30、单处不小于 9px；e2e `test_font_scale_rebuilds_qss_and_keeps_layout`（`PlayerBar.minimumSizeHint ≤ 1100`、浮动条右缘 ≤ 236） |

### 自定义背景

| 需求 | 状态 | 证据 |
|---|---|---|
| 支持图片 / 纯色 / 渐变 | ✅ | `BackgroundConfig.type` 四态；`test_paints_each_type_without_crashing`；真实平台出图 3 张 |
| 背景不透明度可调 | ✅ | 滑块 20%~100%；`test_opacity_controls_strength`（render 到黑图上采样亮度确实不同） |
| 背景模糊可调 | ✅ | 滑块 0~40（降采样近似高斯）；`test_blur_keeps_size_and_changes_pixels` |
| 背景暗化可调 | ✅ | 滑块 0%~70%；paintEvent 里叠一层黑（不受不透明度影响） |
| 图片铺满不变形 | ✅ | `KeepAspectRatioByExpanding` + 居中裁切；`test_output_matches_target_size`、`test_aspect_ratio_not_distorted` |
| 图片不会因为原图被删而失效 | ✅ | 选图即复制进 `%APPDATA%/轻音播放器/bgs/`；`test_copies_into_data_dir`、`test_same_image_reused` |
| 按页面分别设置 | ✅ | `bg_all / bg_library / bg_now` + `bg_config(page)` 回退；e2e `test_background_per_page_override`、`test_background_page_without_override_follows_all` |
| 背景能被看见（不被面板盖住） | ✅ | 有背景时 QSS 面板转 rgba(0.78)；e2e `test_background_applies_and_persists` |
| 降透明度时不透出桌面 | ✅ | 窗口根底色强制不透明；`test_window_root_stays_opaque` |
| 对话框/菜单不被半透明污染 | ✅ | 末尾追加不透明覆盖；`test_dialogs_stay_opaque` |
| 关掉背景完全还原 | ✅ | e2e `test_background_off_restores_opaque`（QSS 里不再有 rgba） |
| 背景设置落盘 | ✅ | `LibraryStore(data_file()).settings.bg_all`；老数据无 `bg` 字段时用默认值 |

### 质量门

| 项 | 状态 | 证据 |
|---|---|---|
| 全量回归 | ✅ | `run_tests.py` **22 进程全绿**（原 258 项 + 新增 73 项 = **331 项**，`unittest` loader 点数） |
| 代码风格 | ✅ | `ruff check .` 全通过 |
| 视觉验收 | ✅ | 真实平台出图：渐变背景 / 模糊图片背景 / 浅色纯色背景 / 设置背景页 / 橙色强调色 / 绿色+特大字号 |
| 双 EXE 重建 | ✅ | `build.py` onefile **55.6MB** + onedir **2.4MB**；两者 smoke 与真实平台 8s 存活检查均通过；图标仍 14885B（未被 offscreen 污染） |
| 版本号 | ✅ | 界面 `v2.2 · 本地音乐与视频`；`main.APP_VERSION = "2.2.0"` |

## v2.2.1 增量验收（封面缓存内存优化）

| 需求 | 状态 | 证据 |
|---|---|---|
| 封面内存缓存有上限 | ✅ | `CoverProvider._mem` 改为按像素预算 LRU（`_LruPixmapCache`，默认 10M px ≈ 40MB）；`test_mem_cache_bounded_by_pixels` |
| 大图不把小图全挤掉、最近用优先保留 | ✅ | 按像素（非条目数）淘汰，命中 `move_to_end`；`test_lru_evicts_least_recently_used`、`test_lru_hit_marks_recent` |
| 单张超预算不崩 | ✅ | `test_oversized_pixmap_still_returned`（200px 图远超预算仍正常返回） |
| 量化对比 | ✅ | 探针 `build/probe_memory.py`：5000 首列表 + 切 300 首，改前 **123MB 无上限** → 改后 **38MB 封顶**（条目 5600 → 247） |
| 不影响现有功能 | ✅ | 全量回归 22 进程 **335 项全绿**；`ruff check .` 干净 |

**根因**：`track_list.set_tracks` 是 QListWidget 全量渲染（`setItemWidget` 逐行），每首一张 40px 封面；「正在播放」页每次切歌再请求一张 280px 大图（约 49 倍像素）。旧缓存是无上限 dict，大图随切歌单调累积、永不回收。

## v2.2.2 增量验收（左下工具条重排：齿轮设置 + 独立按钮）

| 需求 | 状态 | 证据 |
|---|---|---|
| 设置改成齿轮图标 | ✅ | 新增手绘 `gear`（锯齿外轮廓 + 中心镂空孔，`fillPath(subtracted)`）；`test_settings_uses_gear_icon` |
| 齿轮放在主题按钮下方 | ✅ | FloatBar 左列竖排：主题 34 → 间距 6 → 齿轮 34；`test_left_column_has_two_circle_buttons` |
| 导入音乐 / 数据目录放右边、做成单独按钮 | ✅ | 右侧两个 `#FloatTextBtn` 各 88×34 并排，不再有 `#FloatTray` 分段托盘；`test_import_and_dir_are_separate_buttons` |
| 侧栏里的「导入音乐」大按钮移除 | ✅ | `sidebar.py` 删除按钮与 `import_menu_requested` 信号；连线改到 `float_bar.import_clicked` |
| 整条仍收在侧栏内容宽度内 | ✅ | 224 = 34 + 8 + 88 + 6 + 88，右缘 236；`test_width_matches_sidebar_content`、`test_float_bar_fits_player_bar_indent` |
| 圆钮正圆、按钮圆角合规 | ✅ | 圆钮 radius 17 配 34 高；按钮 radius 12 配 34 高（均 ≤ 短边一半）；`test_theme_toggle_is_a_circle`、`test_text_button_radius_within_half_height` |
| 齿轮 16px 下读得出来、不与太阳混淆 | ✅ | 图标验收表 `shots/icons_v222b.png`（72px 原图 + 16px 最近邻放大 8×，浅/深两版） |
| 不影响现有功能 | ✅ | 22 进程 **337 项全绿**；`ruff check .` 干净 |

**两处关键取舍**：

1. **齿轮首版作废**：最初画「空心圆环 + 8 条短射线」，出图标验收表后发现与 `sun`（实心圆点 + 细长射线）在小尺寸下几乎同形 —— 而齿轮就排在主题钮正下方，用户会以为两个都是换主题的。改为「实心 + 宽齿锯齿轮廓 + 中心镂空孔」，靠形状而非线宽区分，16px 放大后锯齿清晰。
2. **移除浮动条里的「正在播放」**：列表页头本就有等价按钮（`TrackList.np_btn`），点播放栏封面也能回正在播放页，它不再是唯一入口；腾出的横向空间给「导入音乐」，让最高频操作离手更近。

### v2.2.3 尺寸放大（沿用 v2.2.2 布局）

| 项 | 变化 | 证据 |
|---|---|---|
| 整条尺寸 | 224×74 → **224×82** | 宽度 224 是侧栏内容宽上限，只能往高度 / 图标 / 字号方向放大 |
| 圆钮直径 | 34 → **38**（radius 17 → 19，仍是正圆） | `test_theme_toggle_is_a_circle` |
| 文字按钮 | 88×34 → **86×38**（radius 12 → 13） | 38 + 8 + 86 + 6 + 86 仍 = 224 |
| 图标 | 14 → **16** | `test_settings_uses_gear_icon` |
| 字号 | 11 → **12** | `#FloatTextBtn` |
| 底部间距 | 「在播放栏内居中」（只剩 1px）→ **固定留 4px** | 82 高的条放进 84 高的播放栏只剩 1px 余量，正好压进窗口圆角遮罩里被削掉一块（整窗截图裁角 4× 复现） |
| 不影响现有功能 | ✅ | 22 进程 **337 项全绿**；`ruff check .` 干净 |

## v2.3 「星月」默认主题（用角色元素做的新主题）

| 项 | 实现 | 证据 |
|---|---|---|
| 新做一个主题 | `COLUMBINA` 色卡：深紫夜空 `#130e26` + 冰蓝月光 `#7ec8e8` + 莓红 `#ff5c8a` 点缀 | `test_all_themes_registered`（三主题集合） |
| 成为**所有背景**下的默认主题 | `DEFAULT_THEME = "columbina"`；`Settings.theme` 默认值与旧数据回落都改到它 | `test_default_is_columbina`、`test_legacy_data_without_new_settings` |
| 只有一坨深色不够 | 新增 `Theme.BG_ALT`，窗口底走 `qlineargradient` 斜向渐变（首版纯色糊成一块黑） | `test_bg_gradient_only_for_columbina` |
| 角色元素（星月） | 底层 56 颗固定星点（alpha 22~72）+ 一枚完整细月牙（alpha 14） | `TestThemeDecor` 3 项 + 截图目检 |
| 装饰不能干扰内容 | 只在「星月主题 + 背景类型 none」时画；不算自定义背景，不触发面板半透明 | `test_decor_does_not_count_as_custom_background` |
| 主题钮能切到新主题 | 改为**两态循环** 空月 ↔ 浅色；图标与提示都指向「点下去会切到哪个」 | `test_cycle_covers_all_themes_and_closes`、e2e `test_float_bar_theme_toggle` |
| 设置里能选 | 按 `THEME_ORDER` 生成两个 radio；`light_radio` 保留为别名（原 `dark` 主题已删除） | 截图 `shots/columbina-settings-v230r2.png` |
| 文字可读 | `TEXT/SURFACE=16.0`、`ACCENT/SURFACE=9.8`、`ON_ACCENT/ACCENT=9.8`、`TEXT_DIM/SURFACE=6.3` | `test_theme` 对比度断言 |
| 图标要认得出 | 新增 `feather`（实心羽片 + 镂空羽轴 + 羽枝缺口） | `shots/icons_v230.png`（16px 放大 8× 与 gear/settings 对照） |
| 不影响现有功能 | ✅ | 22 进程 **344 项全绿**；`ruff check .` 干净 |

**三处返工（都是截图才看出来的）**：

1. **配色太黑**：首版 `BG #0e0a18` 与 `SURFACE #181226` 只差一点，整窗糊成一块黑。
   → 整套面板色提亮拉开 + 渐变色 `BG_ALT`，深度来自光而不是靠深色。
2. **月牙位置三版**：贴右下角被播放栏压成残弧；裁出右上角变成淡圆盘（像污渍）；
   最终放右半区竖向 70%（歌曲行下方空白带），完整细月牙、alpha 14。
3. **羽毛图标太碎**：首版「羽轴 + 8 条细羽枝」在 16px 下糊成灰团，且与相邻的
   `settings`（细横线）撞气质 → 改实心羽片，靠轮廓站住（与 v2.2.2 齿轮同一类教训）。

**边界**：只复刻**视觉语言**（配色 / 星月 / 羽毛），**不嵌入官方立绘** —— 版权素材
不随 EXE 分发。

## v2.3.2 侧栏圆钮与浮动条对齐

| 项 | 变化 | 证据 |
|---|---|---|
| 侧栏「我喜欢 / 资料库」两个圆钮 | 46×46 圆角方块（radius 12）→ **38×38 正圆**（radius 19） | `test_icon_buttons_keep_declared_size`（38×38） |
| 与浮动条左列圆钮 | 同尺寸、**左缘同在 x=12**（侧栏内容左边 = 浮动条 x） | e2e `test_sidebar_nav_aligned_with_float_bar`（逐钮比 width/height/x） |
| 钮内图标 | 20 → **18**（38 圆内 16 偏小、20 偏挤） | 截图 `shots/columbina-library-nav38.png`、`shots/light-library-nav38.png` |
| 不影响现有功能 | ✅ | 全量回归全绿；`ruff check .` 干净 |

为什么不再用圆角方块：浮动条就在同一列的窗口底部，两者上下呼应；一个 46 圆角方块 + 一个 38 正圆，
竖向读下来是「两个不同的东西」。统一成正圆后，左缘成一条竖线。

## v2.3.3 「空月」主题增强（用哥伦比娅元素重做默认背景）

v2.3 的「星月」主题只有配色 + 一枚淡月牙。这次按用户给的参考立绘，把角色的**核心视觉**补进背景装饰层：背后那枚多层**符文圆环**、披风上的**羽饰**，主题更名为「空月」（贴合「空月之歌」）。

| 项 | 实现 | 证据 |
|---|---|---|
| 配色微调 | BG `#130e26`→`#120e22`、SURFACE 整体提亮一档（`#1c1632`→`#1d1738`）、BG_ALT `#0b1526`→`#0a1220` | 层次来自「光」而不是「更黑」，截图上能一眼分出侧栏/列表/播放栏三层 |
| 符文圆环 | 三层同心圆（alpha 30 / 22 / 18）+ 八枚刻度（34）+ 中心淡点（40）；位置 `(0.78w, 0.26h)`、半径 `0.23min` | `build/probe_decor.py` 真实尺寸渲染 |
| 羽饰 | 三片**描边**叶片 + 羽轴中线（alpha 50、线宽 1.5），放在内容区右上空白处 | 与圆环组成「光环 + 羽翼」，避开页头标题与「播放全部」 |
| 月牙 | **沿用 v2.3.1 的尺寸/alpha/位置**（行下空白带、alpha 14），未重复调氛围 | 尊重既有微调，改为收缩圆环半径去错开 |
| 装饰名 | `"moon"` → `"columbina"`（现在画四种元素，旧名不准） | `test_decor_paints_when_enabled` 等 3 处同步 |
| 主题标签 | 「星月」→「空月」 | `test_float_bar_theme_toggle` 断言同步 |
| 不影响现有功能 | ✅ | 22 进程 **345 项全绿**；`ruff check .` 干净 |

**三处返工，全都返在「看不见」而不是「画错」**：

1. **探针自身 bug**：`layer.render(img)` 时 `QPainter` 还没 `end()`，同一张图被并发绘制 → 装饰全被丢掉，第一版探针图是一片纯色（看起来像「alpha 太低」，其实是没画上去）。
2. **alpha 定档**：初版圆环 13 / 羽饰 11 / 月牙 14，压在 `#120e22` 底色上几乎完全看不见。提到外环 30 / 刻度 34 / 中心 40 / 羽饰 50 才读得出 —— 亮度靠 alpha 加**锐利的细线**，不靠涂大块（涂大块就成了污渍）。
3. **羽饰位置两次搬家**：放侧栏内 → 被半透明面板（不透明度 0.78）盖得只剩 5/50；骑侧栏/内容区分界 → 仍有一半在面板下。最终放内容区右上空白处。教训：**装饰只有落在没有面板盖着的区域才真的看得见**。

## v2.3.4 主题改名「空月」→「深色」+ 默认主题改浅色

只动**显示名**，不动内部 id 与持久化数据（`settings.theme` 仍是 `columbina` / `light`）。

| 项 | 变化 | 证据 |
|---|---|---|
| 主题中文名 | `THEME_LABEL = {"columbina": "深色", "light": "浅色"}` | `test_float_bar_theme_toggle`（tooltip「切换到深色主题」） |
| 改名的影响面 | 设置对话框 radio、浮动条 tooltip、切换 toast 三处**全部读 `THEME_LABEL`**，改一张表即全局生效 | 设置/浮动条/`_apply_theme` 均无硬编码主题名 |
| 默认主题 | `columbina` → **`light`**；`Settings.theme` 默认值与旧数据回落同步改 | `test_default_is_light`、`test_legacy_data_without_new_settings`、`test_video` |
| 内部 id 为什么不改 | 改 id 要迁移所有已落盘 `data.json` 与主题表 key，收益只是一个内部字符串 | — |
| 不影响现有功能 | ✅ | 22 进程 **345 项全绿**；`ruff check .` 干净 |

## v2.3.5 浅色主题按参考图重做

| 项 | 变化 | 证据 |
|---|---|---|
| 底色 | `#f4f2fc`（粉紫）→ **`#eef2fb`**（冷调月白，参考图采样值） | `test_light_surfaces_are_blue_tinted`（B≥R、B≥G） |
| 面板 | 纯白卡片 → `#f5f8fd`，与底色只差 1~2 阶（参考图里三块几乎同色） | 截图目检 |
| 强调色 | `#7c83f0`（偏紫）→ **`#7389cb`**（periwinkle） | `test_accent_readable_on_surface` 3.20:1、`test_on_accent_readable_on_accent` 3.43:1 |
| 装饰 | 18 颗碎星撒满全窗 + 2 片小叶子 → **1 支 0.9 窗高线描羽毛 + 1 枚带光环罗盘星 + 5 点微光** | `test_light_decor_paints_when_enabled` + 灰度分布采样 |
| 装饰浓度 | 用强调色 + 低 alpha（最深 173）→ 强调色压深 75% + 高 alpha（p0.5=176 / p2=211，参考 193/219） | 无文字区灰度统计 |
| 深色主题 | 不动 | 截图回归目检 |
| 不影响现有功能 | ✅ | 22 进程 **345 项全绿**；`ruff check .` 干净 |

**三处返工**：实心四角星→蓝色菱形（改用腰部 7% 的细长尖刺）；羽枝 26 对→梳子
（疏到 16 根 + 轮廓与羽枝共用同一生成器 + 斜扫）；羽片根部硬截断（t 先重映射到
羽片自己的 0~1）。另有一处位置教训：星放参考图相对位置会被"排序"下拉框盖掉半个。

## v2.3.6 深色主题按参考图重做

| 项 | 变化 | 证据 |
|---|---|---|
| 月牙 | 实心近白（α205，深底上像贴纸）→ **玻璃质感**：两圆差集 + 淡填充（α10/7/4）+ 双层软内带 + 1.6px 亮边 | 灰度采样：月内/月外差 14 阶（参考图 11 阶；旧版 30 阶） |
| 月牙尖角 | 两段圆弧拼 → 端点间留直线弦，尖角被削平成"灰色 D" → 改 `subtracted()` 差集 | 探针单独渲染确认 |
| 轨道环 | 无 → 1px 细圈 + 24 个长短交替刻度 | 截图目检 |
| 罗盘星 | 月亮右下角的实心四角星 → 环正下方交点：内凹四角星 + 竖杆 + 人字刻度 + 十字准线 | 截图目检 |
| 辉光 | 一圈淡圆（α26）→ 径向渐变，半径 = 环 × 2.55，中心 α58 | 近/远区亮度差 12.3（参考 6.0） |
| 浮羽 | 3 片线描叶片 → 4 片柔焦浮羽（横向渐变填充 + 羽枝 + 基部发亮的羽轴） | 放大 2× 目检能读成羽毛 |
| 不影响现有功能 | ✅ | 22 进程 **345 项全绿**；`ruff check .` 干净 |

**一处位置取舍**：参考图的罗盘星在环的右侧，但我们的右侧是"时长/编辑"列，星会压住图标
→ 改放环的正下方（无遮挡优先于构图完全吻合）。

## v2.4.0 联网歌词检索改进

| 项 | 变化 | 证据 |
|---|---|---|
| 检索策略 | 单条 `search` 查询 → **有序查询计划**：`/api/get` 精确 → search（原艺人）→ search（主艺人）→ `q=` 自由文本；命中高信任度即早停 | 真实联网：`晴天/周杰伦` 第 1 条即命中，只发 1 个请求 |
| 标签清洗 | 无 → `clean_title` / `clean_artist`：全角转半角、括号噪声（live/remaster/伴奏/主题曲/版…）、`feat.` 尾巴、前导音轨号、破折号噪声后缀、多艺人切分 | **命中率 6/11 → 10/11**（同一批脏标签） |
| 身份门槛 | 「歌名 or 艺人 or 时长」→ **「歌名对得上 or 时长差 ≤2s」**（移除"只有艺人对上"） | `test_artist_only_match_is_rejected` |
| 同名翻唱 | 无惩罚 → 歌名对上但艺人和时长双双不符时 −1.5 | `test_cover_version_is_penalized` |
| 短标题误匹配 | 包含式比对无长度校验（"雨"能匹配"下雨天"）→ 加长度比例门槛 | `test_short_title_does_not_match_longer_song` |
| 同步稿优先 | 按总分统一排序 → **同步稿单独分区**，同曲有同步稿就绝不用纯文本 | `test_synced_wins_over_higher_scoring_plain` |
| 无效歌词 | 空白/纯时间戳文本也算命中 → `usable_text()` 过滤 | `test_rejects_blank_and_tag_only` |
| 负缓存 | 无（每次启动都重打请求）→ `<track_id>.miss`，TTL 7 天 | `TestMissCache` 5 项 |
| 手动重试 | 无出路 → 歌词区**右键「重新联网匹配歌词」** | e2e `test_miss_cache_suppresses_retry_until_manual_retry` |
| 限流处理 | 429/503 被当成"没找到"（会误写负缓存 7 天）→ `FetchOutcome.aborted` 区分；请求间隔 250ms | `test_emits_aborted_not_missed_when_rate_limited` |
| 空状态文案 | 只有"暂无歌词" → 三态：默认 / 检索中 / 未找到（含重试提示） | e2e 断言文案 |
| 不影响现有功能 | ✅ | 22 进程 **393 项全绿**；`ruff check .` 干净 |

**关键坑（真实联网才暴露）**：连发十几个请求被 LRCLIB 429，`fetch_lyrics` 返回 None，
上层当成"未命中"写进负缓存 —— 一首明明有歌词的歌被记住 7 天。修法是让结果带上
`aborted` 原因，中止时**不发** `missed` 信号、改发 `aborted` 信号（v2.6.2），
界面据此显示「失败可重试」而不落负缓存。

**测试净增 39 项**：`tests/test_lyrics_online.py` 33 → 71（+38），
`tests.test_e2e.TestE2ELyricsOnline` 5 → 6（+1）。全量 22 进程 393 项。


## v2.5.0 图标清晰度与齿轮重画

| 项 | 变化 | 证据 |
|---|---|---|
| 高清屏糊化 | 图标一直按 `QPixmap(16, 16)`（DPR=1）生成，125%~150% 屏上被放大绘制 → 齿轮在界面里只剩 9×10 设备像素的一团灰影 | 用户截图裁切放大 12× 叠像素网格实测：圆钮 45px、图标 9×10px |
| 渲染管线 | 新增 `device_ratio()`；`_paint()` 按 `size×DPR` 渲染并 `setDevicePixelRatio`，笔画粗细同步缩放；缓存键带 dpr | `test_paint_scales_bitmap_with_dpr`（DPR 1.5 → 24×24 位图） |
| QLabel 图标 | 三处 `QIcon.pixmap(n, n)` 默认按 DPR=1 取图，会把高清位图又降采样回去 → 新增 `make_pixmap()` 直接用 DPR 位图 | sidebar / title_bar / queue_panel 三处替换 |
| 齿轮齿形 | 齿深 0.16→0.12、齿顶平台 0.28→0.44 步、斜边 0.16→0.09 步、轴孔 Ø0.28→Ø0.30：从"多角星"变成"厚环 + 短宽齿"的实体齿轮 | 20px / 24px 设备像素上逐轮对比定参（16px 判断会得出错误结论） |
| 与太阳区分 | 齿轮 = 实体环 + 8 短齿；太阳 = 圆点 + 8 根细射线；浅深两主题下均一眼可分 | `shots/v250-float-bar.png`、`shots/v250-icons.png` |
| 验收工具 | `probe_icons.py` 增加第三行「设备像素渲染」——只看 16px 那行**发现不了糊掉**这个问题 | 三行验收表 |
| 布局不变 | ✅ | `FloatBar.sizeHint() = (224, 82)`，右缘 236 |
| 不影响现有功能 | ✅ | 22 进程 **397 项全绿**；`ruff check .` 干净 |

**两轮弯路**（已记入 DESIGN §19.3）：① 先把齿加深、齿数降到 6，结果读成"风车/多角星"；
② 参数矩阵里四折点公式漏了齿谷那段（齿谷恒为 0），整批变体都成了锯齿边。


## v2.5.1 主题钮图标改为月亮

| 条目 | 结论 | 证据 |
|---|---|---|
| 目标确认 | 红圈盖住了钮体、无法靠像素判断，改从代码确认：浮动条左列上=主题切换、下=设置齿轮 | `ui/float_bar.py` 网格第 0 列 |
| 图标语义 | 钮上画的是「点下去会切到**哪个**主题」而非当前主题 → 浅色显示月亮、深色显示太阳（用户截图是浅色，所以原来是羽毛） | `set_theme_icon()` 取 `THEME_NEXT` |
| 月亮形状 | 两圆差集 `outer.subtracted(inner)`，尖角是两个圆真实相交处 | 24px 设备像素下仍是清晰月牙 |
| 不用拼弧 | 弃用 `arcMoveTo / arcTo`：两弧端点之间会连出一条直线弦，月牙被削平成「灰色 D」 | 与 v2.3.6 装饰月牙同一个坑（DESIGN §17.2） |
| 参数 | 外圆 R=0.42、内圆 0.90R 右移 0.16、整体转 −30° | 20/24/72/96 四档包围盒：宽 77~80%、高 85~90% |
| 与齿轮区分 | 月牙（弧形开口）vs 齿轮（实体环 + 8 短齿），浅深两主题下一眼可分 | `shots/v251-moon-before-after.png` |
| 改动面 | 只动 `icons.py` 画法 + `theme.THEME_ICON` 表 + `float_bar` 初始值；持久化 id 仍是 `columbina`/`light` | 无数据迁移 |
| 布局不变 | ✅ | `FloatBar.sizeHint() = (224, 82)`，右缘 236 |
| 不影响现有功能 | ✅ | 22 进程 **400 项全绿**；`ruff check .` 干净 |

**一次环境坑**（与代码无关，已记入 MEMORY #7）：首次全量跑时，我在旁边用探针脚本以真实平台
开了 `QApplication`，`tests.test_player` 卡到 600s 超时；单独重跑 4.3s 通过，随后全量复跑全绿。
QMediaPlayer 在媒体后端被抢占时会死锁 —— **跑回归时不要同时开任何 Qt 进程**。


## v2.6.0 数据目录可选择

| 条目 | 结论 | 证据 |
|---|---|---|
| 位置可配置 | 设置 → 存储：显示当前目录 + 模式（默认/自定义/便携），可「更改位置…」「放到软件目录」「恢复默认」「打开目录」 | `ui/settings_dialog.py` 第 4 页 |
| 优先级 | `QY_DATA_DIR` > 便携模式（软件目录 `data/`）> 指针文件 `location.txt` > `%APPDATA%` | `test_storage.TestResolveRoot` 6 项 |
| 指针放在哪 | 放**默认目录**的 `location.txt`，不能记进 data.json —— data.json 自己要被搬走 | `app/paths.py` `read_pointer()` |
| 指针失效 | 目录不存在（U 盘拔了/被删）→ 回退默认位置，不会把程序钉在空目录 | `test_broken_pointer_falls_back_to_default` |
| 便携模式 | 软件目录下存在 `data/` 即生效，整个文件夹拷走就带走曲库 | `test_packaged_uses_software_dir` |
| 便携模式仅打包版 | 源码运行时忽略，且按钮禁用 —— 否则会把数据搬进仓库、程序却不认，还会破坏测试隔离 | `test_source_run_ignores_portable_dir`、E2E `test_settings_dialog_has_storage_tab` |
| 自检隔离 | `--smoke` 同时设 `APPDATA` 与 `QY_DATA_DIR`，便携/指针都压不过它 | `test_env_beats_portable`、`test_smoke_isolation` 2 项 |
| 迁移安全性 | 目标必须空目录；先复制→逐文件核对字节→才删源；失败/取消清理目标、源不动 | `test_cancel_cleans_target_and_keeps_source` 等 5 项 |
| 迁移完整性 | `data.json` + `library/`（含子目录）+ `covers/` 全就位，`.part`/`.bak` 残留不搬 | `test_migrate_copies_everything_and_removes_source` |
| 防递归 | 目标与源相同 / 目标在源内部 / 源在目标内部 → 拒绝 | `test_rejects_same_directory`、`test_rejects_nested_target` |
| 恢复默认 | 删指针文件，数据搬回 `%APPDATA%` | `test_switch_back_to_default_clears_pointer` |
| 生效方式 | 迁移后提示重启（热切换要重建 store/封面缓存/播放器，风险大于收益） | `storage_changed` 信号 + toast |
| 不影响现有功能 | ✅ | 23 进程 **428 项全绿**；`ruff check .` 干净 |

**两个实现坑**（已记入 DESIGN §21.5）：① 迁移的「总量统计」与「实际复制」最初用了两套遍历，
统计把 `.part` 算进去而复制跳过 → 核对永远失败，现在统一走 `plan()`；② 顶层目录下的文件
相对路径写成 `name`（漏了文件名）→ 迁移后 `library` 变成文件。


## v2.6.1 浮动工具条改为单行

| 条目 | 结论 | 证据 |
|---|---|---|
| 四个入口一排 | 主题圆钮 → 设置齿轮 → 导入音乐 → 数据目录 同一水平线，`QHBoxLayout` | `shots/float_v261_light.png` / `_dark.png` |
| 整条尺寸 | **224 × 38**（原 3×2 网格 224×82），高度 = 圆钮直径 | `FloatBar.sizeHint() = (224, 38)` |
| 宽度分配 | `38+4+38+4+68+4+68 = 224`，右缘 236 齐平侧栏内容右边界 | `test_single_row_layout_is_exactly_sidebar_width` |
| 文字不再折行 | 「导入音乐」「数据目录」单行四字，65 宽会在大字号下裁字，故取 68 + QSS `padding:0px` | 1.30 倍字号下文字 64px vs 可绘制 66px |
| 竖直位置 | 由「贴窗口底边留 4px」改为**在 84 高播放栏内垂直居中**（y=739，中心 758） | `PLAYER_BAR_HEIGHT` 常量 |
| 视觉 | 圆钮 radius 19 正圆；文字按钮 radius 13（≤ 半高 19，不退化成直角） | 探针放大图 |
| 旧断言更新 | 4 处「上下关系 / 宽 >70 / 左列竖排 / 两个圆钮都对齐导航」按新几何重写 | DESIGN §22.5 |
| 不影响现有功能 | ✅ | 23 进程 **429 项全绿**；`ruff check .` 干净 |

## v2.6.2 歌词：导入 / 进度与来源 / 匹配率

| 条目 | 结论 | 证据 |
|---|---|---|
| 单曲导入并识别 | 右键「导入歌词文件…」，无效 LRC 不绑定并提示；识别成功报告行数 | `_bind_lyrics_file` |
| 批量导入 | 歌词区右键「批量导入歌词…」扫 `*.lrc` 按文件名认到曲目，歧义跳过 | `tests/test_lyrics_import.py` 11 项 |
| 联网进度 | 空状态显示「正在联网匹配歌词…（cur/total）」 | `LyricsFetchWorker.progress` |
| 来源显示 | 列表下方小字：手动绑定 / 同名 .lrc / 内嵌 / LRCLIB(缓存) / LRCLIB | `LyricsPanel.set_source` |
| 匹配率 | 追加 `q=标题+主艺人` 兜底 + 噪声词增补；真实抽查 5/5 命中 | `test_falls_back_to_search_then_keyword` 等 |
| 不影响现有功能 | ✅ | 24 进程 **444 项全绿**；`ruff check .` 干净 |

## v2.6.5 纯文本 .txt 歌词导入识别

| 条目 | 结论 | 证据 |
|---|---|---|
| 头部信息剔除 | 浏览器下载的 `.txt` 歌词头部「歌名/作词/作曲/编曲…」信息块在解析纯文本前统一剥离 | `strip_meta_lines()` + `lyrics_from_text()` 集成 |
| 首行不误删 | 仅当下一非空行是职员表行才删首行歌名；无元数据时首句歌词保留 | `TestStripMetaLines` 4 项 |
| 手动导入收 `.txt` | 单曲「导入歌词文件…」过滤 `*.lrc *.txt` | `_bind_lyrics` |
| 批量导入收 `.txt` | 批量扫描同时收 `.lrc` 与 `.txt`，按去扩展名 basename 匹配曲目 | `test_matches_txt_extension_too` |
| 真实文件验证 | `唯有追赶风的方向 (Only By Chasing the).txt` 剥离后 74 行干净歌词（首行 `Who can surely know`） | 本地读文件核对 |
| 不影响现有功能 | ✅ | 24 进程 **460 项全绿**；`ruff check .` 干净 |

## v2.6.6 纯文本歌词联网对齐成带时间轴 LRC

| 条目 | 结论 | 证据 |
|---|---|---|
| Key 校验 | `verify_key` 走 GET /v1/usage，`plan != anonymous` 才算有效；无效直接拦下不上传音频 | `TestVerifyKey` 4 项 |
| 三步对齐流程 | 创建 multipart 任务 → 轮询 → 下载 LRC，成功返回带时间轴 LRC | `TestAlignLyrics.test_happy_path` |
| 错误分类 | 缺 key / 无歌词 / 无文件 / 格式不支持 / 超 30MB / 401 / 429 / failed / soft_fail 各自落对 error_code | `TestAlignLyrics` 多项 |
| 软失败提示 | `done` 带 `soft_fail` 时 LRC 仍返回但标记不可信，界面提示核对 | `test_soft_fail` |
| 轮询推进 | 首次 queued、下次 done 能正确轮询到终态 | `test_poll_then_done` |
| 后台线程 | worker 分发 done / soft_fail / failed 三态信号 | `TestAlignWorker` 3 项 |
| Key 持久化 | `lyrics_align_api_key` 可存可读，默认空，不进日志 | `TestSettingsKeyPersist` 2 项 |
| 触发入口 | 导入纯文本后 `_maybe_offer_align` 询问 + 歌词区右键「联网对齐歌词」 | `ui/main_window.py` / `ui/lyrics_panel.py` |
| 对齐成功落地 | 写 `lyrics_cache/<id>.lrc` + 解除纯文本绑定 + 立即 `set_synced` 滚动 | `_apply_aligned_lrc` |
| 不影响现有功能 | ✅ | 25 进程 **486 项全绿**；`ruff check .` 干净 |

## v2.6.7 .txt 转 .lrc 文件（对齐产物写成同名 .lrc）

| 条目 | 结论 | 证据 |
|---|---|---|
| 同名路径计算 | `sidecar_lrc_path` 去扩展名 + `.lrc`（晴天.mp3 → 晴天.lrc） | `TestSidecarLrc.test_path_strips_extension` |
| 原子写入 | `write_sidecar_lrc` 用 `.part` + `os.replace`，成功返回路径 | `test_write_creates_file` |
| 覆盖已有 | 同名 .lrc 已存在时覆盖为新对齐结果 | `test_write_overwrites_existing` |
| 失败兜底 | 目录只读/写入失败返回 None，界面提示「未生成 .lrc」 | `test_write_failure_returns_none` |
| 空入参 | 空路径或空歌词直接返回 None | `test_write_empty_returns_none` |
| 覆盖确认 | `_start_align` 前若同名 .lrc 已存在，弹确认再覆盖 | `ui/main_window.py` |
| 落地改动 | `_apply_aligned_lrc` 从写缓存改为写同名 .lrc + 解除纯文本绑定 | `_apply_aligned_lrc` |
| 文案 | 右键「转成 .lrc 文件」；导入后询问「是否转成带时间轴的 .lrc」 | `ui/lyrics_panel.py` / `_maybe_offer_align` |
| 不影响现有功能 | ✅ | 25 进程 **491 项全绿**；`ruff check .` 干净 |

## v2.6.8 多源联网歌词（LRCLIB + 网易云 + QQ音乐，并行取最优）

| 条目 | 结论 | 证据 |
|---|---|---|
| 网易云搜索/歌词 URL | `music.163.com/api/search/get` + `/api/song/lyric`，带 Referer | `TestSearchUrl` 4 项 |
| QQ 搜索/歌词 URL | `client_search_cp` + `fcg_query_lyric_new.fcg`，`nobase64=1` 明文 | `TestSearchUrl` |
| 网易云解析 | 毫秒转秒、艺人/专辑/时长容错；歌词取 `lrc.lyric` | `TestParseNetease` 4 项 |
| QQ 解析 | `interval` 即秒；歌词 `retcode`/`code` 双字段容错、非 0 拒绝 | `TestParseQQ` 5 项 |
| 候选遍历 | 伴奏版排第一且无歌词 → 跳过、取后面正版 | `test_skips_candidate_without_lyrics` |
| 多源并行取最优 | 三源并行、跨源统一 `pick_best`；同名翻唱（LRCLIB 艺人错）让位网易云正版 | `test_picks_most_trustworthy_across_sources` |
| 来源标注 | `found(track_id, text, source)` 三参数；界面显示 LRCLIB/网易云/QQ音乐 | `TestMultiSourceWorker` 3 项 |
| 中止语义 | 至少一源限流且全未命中 → `aborted=True`，不落负缓存 | `test_aborted_when_a_source_is_rate_limited_and_none_hit` |
| 降级链 | 单源断网/被拒 → 该源返回 None，其余源兜住 | `test_network_error_degrades_to_none`（两源） |
| 离线显示 | 命中照旧写缓存/同名 .lrc，断网可读（与单源同链路） | `_on_online_lyrics` 仍调 `write_cache` |
| 向后兼容 | `lyrics_online.py` 只增 `fetch_best_hit`；旧 `LyricsFetchWorker` 保留、测试不动 | `TestFetchWorker` 3 项仍绿 |
| 不影响现有功能 | ✅ | 26 进程 **520 项全绿**；`ruff check .` 干净 |

## v2.6.9 本地歌词对齐（离线纯文本 → 带时间轴 LRC）

| 条目 | 结论 | 证据 |
|---|---|---|
| 解码 | miniaudio 解码 mp3/flac/wav/ogg 为 mono 16k float32；中文路径走 bytes 绕开 | `TestDecode` 2 项 |
| 能量包络 | 静音帧 RMS≈0、有声帧 RMS 明显更大 | `TestRmsEnvelope` |
| 静音检测 | 前奏/间奏/尾奏静音被识别，检测出 2 个有声段且位置正确 | `TestDetectSpeech` 2 项 |
| 时间戳分配 | 歌词行铺在有声段上、跳过前奏/尾奏；无有声段退化为全时长均分 | `TestAssignTimestamps` 3 项 |
| LRC 生成 | 端到端产出 4 行同步 LRC、时间戳递增、行文本正确 | `TestAlignLocal.test_end_to_end_produces_synced_lrc` |
| 错误分支 | no_audio / no_lyrics / already_synced / decode_failed 各自落对 error_code | `TestAlignLocal` 4 项 |
| 后台线程 | worker 分发 done / failed 两态信号 | `TestWorker` 2 项 |
| 本地优先 | 导入纯文本后询问默认走本地对齐；右键「本地对齐」置顶、「联网对齐」兜底 | `_maybe_offer_align` / `lyrics_panel._show_menu` |
| 来源区分 | `_apply_aligned_lrc` 按本地/联网标注「来源：本地对齐 / 联网对齐」 | `main_window.py` |
| 错误降级 | 解码器缺失（打包漏收 `_cffi_backend`）→ `no_decoder` 中文提示，不抛异常 | `test_missing_decoder_degrades_to_no_decoder` |
| 可选依赖不拖启动 | `app/lyrics_local_align` 顶层不 import miniaudio（子进程屏蔽该模块后仍可导入） | `test_module_import_does_not_require_decoder` |
| 不影响现有功能 | ✅ | 28 进程 **543 项全绿**；`ruff check .` 干净 |

## v2.6.9 打包验收（更新版本）

| 条目 | 结论 | 证据 |
|---|---|---|
| 单文件产物 | ✅ 67.4 MB，`--smoke <夹具>` 返回 0 | `EXIT 0 in 4.3s` |
| 解码器入包 | ✅ 冻结产物里 `import miniaudio` 成功 | 自检输出 `smoke decoder: miniaudio OK` |
| 音频解码链路 | ✅ `status=BufferedMedia duration=2037ms` | 自检输出 `smoke ok (含音频解码)` |
| 目录版产物 | ✅ `--smoke` 返回 0 | `smoke ok` |
| 真实平台检查 | ✅ 两变体各持续运行 8s 未崩溃 | `build.py` 输出 |
| 构建不会挂死 | ✅ 超时杀进程树 + 日志落文件（原管道方案挂过 19 分钟） | `build.py:smoke_test` |
| 失败日志可读 | ✅ cp936 日志按 utf-8→gbk 回退解码 | `tests/test_build.py` 4 项 |
| 正式图标未被降级 | ✅ md5 `9f4bdcdf12d625c16cc998e4f7ae40f0` 前后一致 | `md5sum assets/app.ico` |

## v2.6.11 修歌词自动滚动「一直往上滚」

| 条目 | 结论 | 证据 |
|---|---|---|
| 问题复现 | 逐句推进录音：滚动条每句只前进 ~8px（一行 36px），`rect.top()` 从 188 涨到 360 | `tools/probe_lyrics_scroll.py` |
| 根因 | `visualItemRect()` 是**视口坐标**，`bar.value()` 是**内容坐标**；原代码漏加已滚动距离 | 修复前目标值比应有值少整整一个 `bar.value()`（第 10 句 108 vs 208） |
| 目标值正确 | 滚到 `_scroll_target()` 后该项垂直居中度偏差 ≤2px | `test_target_centers_item_after_already_scrolled` |
| 坐标语义固化 | 目标 == `bar.value() + 视口偏移`，且 != 视口偏移 | `test_target_uses_content_coordinates` |
| 不回跳 | 双语条目下连续 8 句滚动值单调不减且确实向下 | `test_scroll_value_never_goes_backwards` |
| 单语实测 | 目标 28→64→100→136→172→208，`rect.top()` 恒 188（每句推进一行高） | 探针真实平台输出 |
| 双语实测 | 目标每句 +58（一行高），第 3 句起居中偏差 0 | 探针 `--bilingual` |
| 动画中途重算安全 | 半路重复调用 `_scroll_target()` 不漂移（`value` 与 `rect.top()` 反相互补） | 探针连续推进观测 |
| 不影响现有功能 | ✅ | 28 进程 **579 项全绿**；`ruff check .` 干净 |
| 打包 | 单文件 70.7 MB + 目录版，smoke 与真实平台检查通过 | `build.py` 输出 |

## v2.6.10 双语歌词（一句 = 原文 + 译文）

| 条目 | 结论 | 证据 |
|---|---|---|
| 双语判定 | 严格交替（两种语种各 ≥25% 且相邻异类 ≥85%）才判双语 | `TestIsBilingualAlternating` 4 项 |
| 误配对防护 | 纯中文歌夹一句英文副歌不配成双语（保持 5 句） | `test_chinese_with_one_english_hook_is_not` |
| 配对规则 | 先出现者为原文，后一行当译文；奇数尾行单独成句；空行剔除 | `TestPairBilingual` 4 项 |
| 同步双语 LRC | 同时间戳两行自动合并成一句；同文本重复不合并（副歌不被吞句） | `TestMergeTranslations` 4 项 |
| LRC 写回 | 写成「同时间戳两行」；读写往返还原成「一句 + 译文」 | `TestFormatLrc` 4 项 |
| 本地对齐 | 74 行 → 37 句，每句译文同时间戳，时间戳严格递增 | `test_bilingual_pairs_lines_into_sentences` |
| 联网对齐 | 只上传原文行（译文不进上传体）；返回后按行序回填 | `test_bilingual_uploads_main_lines_only` / `test_bilingual_restores_translations` |
| 回填安全 | 行数不符时原样返回，不硬配（配错词比没词更糟） | `test_bilingual_skips_restore_when_line_count_differs` |
| 旧路径不变 | 单语歌词上传内容与旧行为一致 | `test_monolingual_payload_unchanged` |
| 界面按句渲染 | `set_plain` 双语 8 行 → 4 条；item.text() 仍是原文，译文存独立 role | `TestBilingualLyricsPanel` 2 项 |
| 条目高度 | 有译文的条目更高（译文层不会被裁掉） | `test_item_height_grows_for_translation` |
| 逐字跨两行 | 进度按两行字符总数推进：原文打完才轮到译文 | `test_typed_split_spans_both_lines` 3 项 |
| 视觉 | 浅/深两套主题四格对比图，两行不裁切、整句一起高亮、karaoke 分界清晰 | `shots/bilingual_lyrics_{light,dark}.png` |
| 打包 | 单文件 67.4 MB + 目录版，smoke 与真实平台检查通过 | `build.py` 输出 |
| 不影响现有功能 | ✅ | 28 进程 **576 项全绿**；`ruff check .` 干净 |

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
