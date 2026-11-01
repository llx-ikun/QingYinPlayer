# 「轻音播放器」任务清单（TASK.md）

> 当前版本：v2.1 本地视频导入与画面播放 · 2026-10-26 · 状态：**待用户评审**
> 规则：按依赖顺序执行；每项完成即勾选并跑该项验证；修复循环 ≤3 轮，超限输出待人工确认项。
> 基线：`main @ 7c4d5b1`（v2.0，122 项测试全绿，dist 双产物在手）。
> 迭代分支：`feat/video-v2_1`（用户确认设计后创建）。

## A. 后端（app/，无 UI 依赖，先行）

- [ ] **A1** `app/models.py`：新增 `PLAYLIST_FAVORITES = "__favorites__"`；`Settings` 增加 `theme: str = "columbina"`、`nickname: str = "音乐爱好者"`（含 `to_dict/from_dict`，旧数据无损升级）
  - 验收：旧 JSON（无新字段）`from_dict` 不抛错且取默认值
- [ ] **A2** `app/store.py`：`load()` 改为保留 system 歌单（原逻辑丢弃）；懒创建 favorites 系统歌单；新增 `toggle_favorite/is_favorite/favorite_tracks/favorite_count`；`view_tracks/view_name` 支持 favorites
  - 验收：单测覆盖增删切、round-trip、重复收藏幂等、`remove_track` 联动清理
- [ ] **A3** `app/player.py`：暴露 `queue_ids` / `queue_index` / `play_from_queue(tid)`
  - 验收：单测覆盖（shuffle 顺序即播放顺序、跳转后 current 正确）
- [ ] **A4** 单测：`tests/test_store.py` + `tests/test_player.py` 增量；全量回归
  - 验收：`python -m unittest discover -s tests` 全绿（≥91）

## B. 主题与图标（依赖 A1）

- [ ] **B1** `ui/theme.py`：`Theme` dataclass + 深/浅两套调色板（浅色 QQ 绿 `#31c27c`、深色沿用蓝紫）+ `build_stylesheet(theme)` + `current_theme()/set_theme()` + 主题应用器（stylesheet + 图标重绘 + EqualizerBars 换色）
  - 验收：两套 QSS 均可生成；切换后 `app.styleSheet()` 变化
- [ ] **B2** `ui/icons.py`：新增 `back/forward/refresh/minimize/maximize/restore/heart/heart_filled/more/queue/settings/sun/moon/home` 绘制；`bind_icon(button, kind, size, role)` 注册表 + `refresh_icons(theme)`
  - 验收：全 kind 渲染不抛错；`refresh_icons` 后图标缓存键随颜色变化
- [ ] **B3** 冒烟：脚本渲染两主题全部图标 + 生成 QSS 文本 diff 检查无空色值

## C. 窗口外壳（依赖 B）

- [ ] **C1** `ui/title_bar.py`：通栏标题栏（logo/前进/后退/刷新/搜索 pill/最小化/最大化/关闭）；空白区 `startSystemMove` 拖拽 + 双击最大化
  - 验收：真实平台窗口可拖拽、双击、三键行为正确（截图+手动）
- [ ] **C2** `ui/main_window.py`：`FramelessWindowHint + WA_TranslucentBackground` + 圆角 + `setMask`；四边四角 6px 缩放热区；视图历史栈（back/fwd）；标题栏搜索接入 `_on_search_changed`；toast 替换 statusBar（保留 `_toast(msg, ms)` API）
  - 验收：最大化/还原/最小化/关闭正常；边缘缩放跟手；back/fwd 正确；搜索过滤与旧行为一致
- [ ] **C3** 视觉冒烟：真实平台截图验证圆角/半透明/缩放光标（见 §12.9 方法）；异常则回退方角方案

## D. 侧边栏（依赖 C2）

- [ ] **D1** `ui/sidebar.py` 重写：用户卡片（首字母头像+昵称+「本地模式」徽标，点击请求改昵称）/ ♥我喜欢·⌂资料库图标导航 / 最近播放·N / 自建歌单+封面列表 / 导入 / 版本号
  - 验收：导航高亮、歌单封面与数量、右键菜单沿用；宽度 248
- [ ] **D2** MainWindow 接线：`refresh_playlists(playlists, cover_getter)`、favorite/recent 计数、昵称修改对话框（patch `QInputDialog` 可测）

## E. 歌曲列表（依赖 D2）

- [ ] **E1** `ui/track_list.py` 重写：列表头（歌曲/艺人/专辑/格式/时长/操作）+ 行（序号或动效条/封面36/当前行高亮/格式徽标/爱心/⋯菜单）；保留拖拽排序、双击播放、空态；`set_tracks` 保持滚动位置
  - 验收：列对齐、徽标文案（flac→无损/mp3→MP3/其他大写）、爱心切换、拖拽排序回归
- [ ] **E2** 爱心接线：`favorite_toggled` → store → 刷新（滚动保持）→ 侧边栏计数同步

## F. 播放栏与队列（依赖 E2）

- [ ] **F1** `ui/player_bar.py` 重写：左=封面+标题/艺人+♥+⋯；中=上一首/绿色圆播放(40px)/下一首 + 进度双行（0:00 ──●── 1:47）；右=音量+当前格式徽标+词+队列
  - 验收：全部既有控件语义保留（time_cur/volume_slider/mode_btn 等测试锚点兼容或更新）
- [ ] **F2** `ui/queue_panel.py`：`Qt.Popup` 队列浮层（当前队列/当前曲高亮/点击跳转）+ MainWindow 接线
  - 验收：打开即刷新、跳转后 current 正确、点击外部自动关闭

## G. 浮动工具条与设置（依赖 F）

- [ ] **G1** `ui/float_bar.py`：4 键（主题/正在播放/数据目录/设置），定位于播放栏左上角，`raise_()` 置顶
- [ ] **G2** `ui/settings_dialog.py`：昵称 / 主题（深/浅 radio）/ 关于（版本+本地统计：曲目数/歌单数/总时长）
  - 验收：改昵称/主题即时生效并落盘

## H. 测试与回归（依赖 D–G）

- [x] **H1** `tests/test_e2e.py` 更新+新增：主题切换与持久化、行内心/播放栏心、标题栏三键（close 走 closeEvent）、视图历史、全局搜索、队列浮层跳转、昵称、toast
  - 验收：新增用例全部通过；旧用例按新结构更新后通过
- [x] **H2** 全量回归：`run_tests.py` 全绿（122 项）+ `ruff check .` 干净
  - 注意：QMediaPlayer 在 offscreen 下同进程内实例累积 ~15-20 个会触发 C++ 层死锁（stop/setStyleSheet 随机 hang），故全量回归必须**逐模块/逐类独立进程**跑，见 `run_tests.py`

## I. 视觉自审与修复（依赖 H2）

- [x] **I1** `tools/shot.py`（开发工具，不进产物）：APPDATA 隔离 + 夹具注入 + 真实平台 `grab()` 截图
- [x] **I2** 截图矩阵逐项自审并修复：{深,浅} × {空库, 曲库, 播放中, 歌词页, 队列浮层, 设置框, 最大化}；修复循环 ≤3 轮

## J. 文档与交付（依赖 I）

- [ ] **J1** 文档：`README.md`（新功能/快捷键）、`DESIGN.md §12` 勾选完成态、`ACCEPTANCE.md` v2.0 增量对照、`交付报告.md` 追加章节
- [ ] **J2** `env -u PYTHONPATH .venv/Scripts/python.exe build.py
# v2.2 外观视觉验收（真实平台出图，不是 offscreen）
env -u PYTHONPATH .venv/Scripts/python.exe tools/shot.py --out ./shots --theme dark \
    --state library --bg "type=gradient;color=#1e3a8a;color2=#7c3aed" --tag bggradient
env -u PYTHONPATH .venv/Scripts/python.exe tools/shot.py --out ./shots --theme dark \
    --state library --bg "type=image;image=<某张图>;blur=16;dim=0.45" --tag bgimage
env -u PYTHONPATH .venv/Scripts/python.exe tools/shot.py --out ./shots --theme light \
    --accent "#22c55e" --font-scale 1.28 --tag big --state library
env -u PYTHONPATH .venv/Scripts/python.exe tools/shot.py --out ./shots --theme dark \
    --state settings --settings-tab 1 --tag bg` 重建双产物（smoke + 真实平台检查）
- [ ] **J3** git：`feat/ui-v2` 合并 `main`（Conventional Commits: `feat(ui): ...`）+ 更新工作区记忆

## 依赖关系

```
A1 → A2/A3 → B1 → B2 → C1 → C2 → D1 → D2 → E1 → E2 → F1 → F2 → G1 → G2 → H1 → H2 → I1 → I2 → J1 → J2 → J3
A4 紧随 A2/A3；I2 不通过则回到对应组件任务（≤3 轮）
```

## 验证命令速查

```bash
cd music-player
env -u PYTHONPATH .venv/Scripts/python.exe run_tests.py                       # 全量回归（逐模块独立进程）
env -u PYTHONPATH .venv/Scripts/python.exe -m ruff check .                     # 静态检查
env -u PYTHONPATH .venv/Scripts/python.exe tools/shot.py --out /tmp/shots      # 视觉自审截图
env -u PYTHONPATH .venv/Scripts/python.exe build.py                            # 双产物重建
```

---

# v2.1 本地视频导入与画面播放（2026-10-26）

> 范围：本地视频导入、双击显示画面、音乐模式不中断切换、全屏；不做在线视频/转码/缩略图。
> 设计依据：DESIGN.md §13；开始开发前需用户确认。

## K. 视频识别与播放输出

- [x] **K1** `app/models.py` 增加视频扩展名集合、`MEDIA_EXTENSIONS`、`Track.is_video`；`app/scanner.py` 扫描与导入过滤器支持本地视频
  - 验收：音频/视频均可扫描，大小写扩展名正确；旧 JSON 无需迁移 ✅（`tests.test_video.TestMediaScan` / `TestTrackIsVideo`）
- [x] **K2** `app/player.py` 增加 `set_video_output`；视频元数据以文件名兜底，时长加载后回填
  - 验收：现有音频播放控制测试不变；视频输出接线可测 ✅（`tests.test_player` 20 项无回归；`TestE2EVideo.test_video_output_bound_to_player`）
- [x] **K3** 后端单测：格式识别、混合媒体扫描、旧数据兼容、视频元数据兜底
  - ✅ `tests/test_video.py`（20 项全绿）

## L. 视频页与模式切换

- [x] **L1** `ui/now_playing.py` 增加音频/视频子视图：画面层等比黑底、标题信息、返回列表、音乐模式、全屏
  - 验收：视频/音频布局各自正常；全屏 F11/Esc 行为正确 ✅
  - **路线修正**：原计划 `QVideoWidget`，实测改为 `QVideoSink` → `QVideoFrame` → `QPainter` 自绘（`ui/video_view.py`）。理由：半透明无边框顶层窗 + 原生 surface（D3D/flip model）易黑框/遮挡/驱动崩溃；自绘可自由 reparent 进全屏浮窗。详见 DESIGN.md §13.3
- [x] **L2** `ui/main_window.py` 接线：双击视频进入视频页；正在播放按曲目类型显示；音乐模式只切视图不重载媒体；返回列表声音继续
  - 验收：切换前后 current_track 与 position 不变；自动切歌类型同步 ✅（`TestE2EVideo.test_music_mode_switch_keeps_playback` 三重断言）
- [x] **L3** `ui/track_list.py` 视频徽标；主题样式/必要图标补齐；不破坏现有音频行与拖拽排序
  - 验收：双主题下视频页与列表无遮挡、无文字方块 ✅（`shots/dark-video.png`、`shots/light-video.png`）

## M. 测试、视觉与交付

- [x] **M1** 新增视频测试：混合导入、双击视频页、音/视频模式切换、全屏快捷键、断点恢复；视频 E2E 独立类并加入 `run_tests.py`
  - 验收：视频用例通过；全量回归全绿；ruff 干净 ✅（11 进程 157 项全绿）
- [x] **M2** 真实视频样本验证：画面、声音、进度、音乐模式、全屏/退出、返回列表；`tools/shot.py` 增加视频页状态
  - 验收：真实平台截图/本机确认；不支持的编码有友好错误 ✅ 截图已出；真实音频输出待用户本机确认
- [x] **M3** 更新 README / DESIGN §13 / ACCEPTANCE / 交付报告；重建双 EXE（smoke + 真实平台检查）
- [x] **M4** 提交 `feat/video-v2_1`，合并 main，更新工作区记忆

## N. 窗口图标修复（2026-10-26，用户反馈「软件打开的图标」为占位符）

> 现象：软件打开后任务栏/标题栏图标显示为「图片找不到」占位符（绿方块+青绿矩形+灰块）。
> 根因：`build.py:generate_icon` 把 PNG 写进 ICO 时目录项填了 `planes=1, bitcount=32`（BMP 值）；
> 按 ICO 规范 PNG 压缩图像这两项必须为 0。资源管理器常容忍，但任务栏/标题栏图标加载器更严格会拒绝，
> 且 `main.py` 从不调用 `setWindowIcon()`，运行时完全依赖该畸形内嵌图标。

- [x] **N1** `build.py:generate_icon`：ICO 目录项改为 `planes=0, bitcount=0`（PNG 规范）
  - 验收：`tests/test_icon.py::test_generate_produces_spec_compliant_ico` 解析目录项断言全为 0/0 且数据为 PNG
- [x] **N2** `build.py:_pyinstaller`：增加 `--add-data assets/app.ico;assets`，运行时可用代码定位图标
  - 验收：`_resolve_app_icon` 在冻结态取到 `sys._MEIPASS/assets/app.ico`
- [x] **N3** `main.py`：`_resolve_app_icon()` + `_apply_app_icon(app)` 在 `--smoke` 与正常启动两处显式设置窗口图标
  - 验收：`tests/test_icon.py::test_icon_resolves_at_runtime`；`QIcon` 加载 7 尺寸全非空
- [x] **N4** 回归测试 `tests/test_icon.py`（3 项）+ 接入 `run_tests.py`；全量回归 + ruff 干净；重建双 EXE
  - 验收：全量回归 **160 项全绿**（157 + 新 3）；`ruff check .` 干净；双 EXE smoke + 真实平台检查通过

## O. v2.1.2 导入弹窗关闭修复 + 浮动工具条改版（2026-10-26，用户反馈）

> 现象①：导入完成后点击弹窗底部「关闭」按钮，弹窗无法关闭（扫描中途点「取消」却能关）。
> 根因：完成后 worker 已结束，按钮仍连 `cancelled → worker.cancel()`，而 `ScannerWorker.cancel()`
> 仅 `requestInterruption()`（no-op），`on_cancelled(dialog.reject)` 永不触发。
> 现象②（用户要求）：浮动工具条原为 4 个纯图标按钮，希望主题做成切换按钮、其余做成图标+文字。

- [x] **O1** `ui/dialogs.py`：`ImportProgressDialog` 加 `_finished` 标志 + `_on_button()`，完成后点「关闭」直接 `accept()`
  - 验收：`tests/test_dialogs.py`（完成后关闭=Accepted / 扫描中取消=emit cancelled / finish 状态）
- [x] **O2** `ui/float_bar.py` + `ui/theme.py`：主题改开关式 `#ThemeToggle`（checkable，icon-only），其余改图标+文字 `#FloatTextBtn`
  - 验收：`test_e2e.TestE2EV2.test_float_bar_theme_toggle` 断言 checkable + 开关状态随主题 + 文案
- [x] **O3** `ui/player_bar.py`：左缩进 190 → 330 给加宽后的浮动条留位（实测条宽 ~294px）
  - 验收：浮动条 x=16 起、宽 294px，结束于 x≈310 < 330，不压封面
- [x] **O4** 回归测试 `tests/test_dialogs.py`（3 项）+ 接入 `run_tests.py`；全量回归 + ruff 干净；重建双 EXE
  - 验收：全量回归 **13 进程 163 项全绿**（160 + 新 3）；`ruff check .` 干净；双 EXE smoke + 真实平台检查通过

## P. v2.1.3 播放栏超宽修复（2026-10-26，用户反馈「窗口/播放栏在抖、进度条来回跳」）

> 根因：v2.1.2 把 `player_bar` 左缩进 190→330 给浮动条让位，`PlayerBar.minimumSizeHint`
> 涨到 **1340px**（> 默认窗 1280、> 最小窗 1100）。后果：① 信息列被挤空，副标题
> 「周杰伦 · 叶惠美」全省略成「周杰伦 · ...」；② 布局在约束边界反复重算 → 窗口/播放栏
> 抖、进度手柄乱跳。「进度 0:00↔0:02」另有 2 秒测试片段循环重播的锯齿因素（属正常）。

- [x] **P1** `ui/player_bar.py`：seek 380→200、音量 90→70、两处 addSpacing 20→8、左缩进 330→312
  - 验收：`PlayerBar().minimumSizeHint().width()` 1340 → **1098 ≤ 1100**（默认 1280 下信息列 182px）
- [x] **P2** 回归测试 `tests/test_widgets.py::TestPlayerBarLayout`（min≤1100 + 浮动条不压封面）；全量回归 + ruff；重建 EXE
  - 验收：`TestPlayerBarLayout` 2 项通过；全量回归 13 进程 165 项全绿；ruff 干净；双 EXE smoke + 真实平台检查通过

## Q. v2.1.4 列表页视觉统一 + 排序增强（2026-10-26，用户反馈）

> 需求：① 统一列表页的布局、间距、字体与控件样式，提升视觉层次与操作体验；
> ② 列表支持按大小 / 时长 / 导入时间排序，提供「最近导入」选项，支持升降序切换，
> 清晰展示当前排序方式，且不影响现有功能。
>
> 排查中发现 4 个此前未被发现的真实缺陷（均由截图与几何探测暴露，非需求本身）：
> ① 列头与数据行**逐列错位**（最多 48px）；② 基础 `QPushButton` 的 padding 叠加到
> 所有固定尺寸按钮上，声明 34/40/46/36 实际 54/60/66/58；③ 左下浮动条从未 `adjustSize`，
> 宽度停在默认 100px，文字按钮被裁得只剩图标；④ 侧边栏昵称列被徽标定宽卡死，只显示「音乐爱…」。

- [x] **Q1** 新增 `app/sorting.py`：`SortPreset`（维度+方向+文案+分组）+ `SORT_PRESETS` 13 条 + `sort_tracks()`
  - 维度覆盖 custom/added/size/duration/title/artist/album，每维度升降序各一条
  - `最近导入` = `added:desc` 独立条目；旧式纯维度 key（`added`/`title`…）归一化到默认预设
  - 大小未知（文件丢失/读不到）的条目**升降序下都排最后**
  - 验收：`tests/test_sorting.py` 17 项
- [x] **Q2** 新增 `app/filesize.py`：`file_size()`（不可读返回 0）+ `format_size()`（1024 进制，`8.4 MB`/`820 KB`/`--`）
  - 验收：`tests/test_filesize.py` 9 项（含「最长形态 ≤ 7 字符以适配 56px 列宽」）
- [x] **Q3** `ui/track_list.py` 结构性重排：页头拆两行（大标题+主操作 / 统计+排序），新增「大小」列，空态改「大音符水印+说明」
  - `count_label` 保持「共 N 首」原格式（E2E 依赖），总时长放独立 `stats_label`
  - 验收：`TestTrackListLayout` 10 项
- [x] **Q4** 列对齐修复：列头改为与行**同一套槽位**（含占位槽与统一 spacing），弹性列 `sizePolicy=Ignored` 使宽度只由 stretch 决定，`QPushButton#RowBtn` padding 归零（28→实际 28，此前 48）
  - 验收：`TestTrackListAlignment` 2 项（套 QSS 后逐列比较全局 X 坐标，Δ 必须为 0）；`tools/probe_columns.py` 实测 10 列 Δ=0
- [x] **Q5** `ui/theme.py`：固定尺寸图标按钮统一 `padding: 0`（`#TitleBtn/#ControlBtn/#PlayCircle/#IconNav/#ThemeToggle`）；新增 `#PageHeader/#PageTitle/#Stats/#ColumnHeaderBar/#SortCombo/#EmptyGlyph/#EmptyText` 样式
  - 验收：`TestThemeSizes::test_icon_buttons_keep_declared_size`（播放键 40×40 正圆、控制按钮 34×34、导航 46×46）
- [x] **Q6** `ui/widgets.py` 新增 `ChevronComboBox`：QSS 覆盖 `::drop-down` 后系统箭头不再绘制，改为自绘 V 形（颜色随主题）
- [x] **Q7** `ui/main_window.py`：排序状态改为 `_sort_id`（`维度:方向`）并按视图分别记忆；`_position_float_bar()` 补 `adjustSize()`；主题切换后重算浮动条宽度
  - 验收：`test_e2e.TestE2EV2` 新增 6 项（大小/时长升降序、最近导入默认、切视图保留排序、歌单默认自定义序且非自定义序时禁用拖拽、总时长统计）
- [x] **Q8** `ui/sidebar.py`：昵称 `Ignored` 策略 + 徽标外接带 stretch 的行，解除列宽被 sizeHint 卡死
  - 验收：`TestThemeSizes::test_sidebar_nickname_not_truncated`（昵称 56→156px，完整显示「音乐爱好者」）
- [x] **Q9** 回归 + 静态检查 + 版本号（`v2.1.4`）+ 重建双 EXE
  - 验收：全量回归 **15 进程 212 项全绿**；`ruff check .` 干净；双 EXE smoke + 真实平台检查通过

## R. v2.1.5 浅色主题改浅蓝 + 移除前进/后退按钮（2026-10-26，用户反馈）

> 需求①：浅色主题原为 QQ 绿（`#31c27c`），与深色主题的蓝紫强调色（`#6c8cff`）、
> 应用图标的蓝紫渐变都不同色系，整体不统一 —— 改为**浅蓝**。
> 需求②：标题栏的「← 后退 / → 前进」按钮不再需要（截图圈出），
> 视图历史的 `Alt+←` / `Alt+→` 快捷键保留，功能不丢。
> 附带：歌词面板把主题色算在类属性里（import 时求值），切主题后颜色被冻结。

- [x] **R1** `ui/theme.py`：`LIGHT` 整套换浅蓝 —— `ACCENT #3b82f6`、`ACCENT_HOVER #2f74ea`、
      `ACCENT_DIM #2563eb`、`ACCENT_SOFT #e7f0fe`；`BG/SURFACE_HOVER/SURFACE_ACTIVE/BORDER`
      全部带蓝调（`#f3f6fc / #eef3fb / #e3ecfb / #dde5f3`），中性灰→淡蓝灰
  - 验收：`tests/test_theme.py` 色相与对比度约束（见 R4）
- [x] **R2** `ui/title_bar.py` + `ui/main_window.py`：移除 `back_btn` / `fwd_btn`、
      `back_clicked` / `forward_clicked` 信号、`set_nav_enabled()`、`_update_nav_buttons()` 及其 4 处调用；
      刷新 ↻ 保留
  - 验收：`test_title_bar_has_no_back_forward_buttons`（按钮已消失、刷新仍可用）
- [x] **R3** `test_view_history_shortcuts_still_bound`：删按钮后 `Alt+←` / `Alt+→` 必须仍然绑定
  - 验收：从 `QShortcut` 集合断言两个序列仍在；历史逻辑本身按 `_history_pos` 断言（不再依赖按钮 enabled）
- [x] **R4** 新增 `tests/test_theme.py`（10 项）：两主题强调色蓝通道主导、浅色底板蓝调、
      文字/强调色对比度下限（正文 ≥7:1、强调 ≥3:1）、`ACCENT_SOFT` 是淡底、
      旧 QQ 绿五个色值不得残留在 QSS
  - 验收：`tests.test_theme` 10 项通过；接入 `run_tests.py`（第 16 个进程）
- [x] **R5** `ui/lyrics_panel.py`：`_NORMAL = QColor(TEXT_DIM)`（类属性，import 时求值 → 被冻结在深色值）
      改为 `_normal_color()` 在用的时候取 `current_theme().TEXT_DIM`；顺手删掉从未使用的 `_PLAYED`
- [x] **R6** 回归 + 静态检查 + 版本号 `v2.1.5` + 重建双 EXE
  - 验收：全量回归 **17 进程 234 项全绿**；`ruff check .` 干净；双 EXE smoke + 真实平台检查通过

- [x] **R7** 测试夹具与用户目录隔离：`tests/make_fixtures.py` 新增 `GENERATED = tests/fixtures/_generated`，
      音频/视频/临时封面/`.done` 全部改落 `_generated/`（中文子目录 `我的音乐`/`我的视频` 保留），
      `build.py` 不再硬编码夹具路径
  - 起因：用户 10-26 21:35 要求 `tests/fixtures/我的音乐` 只能放他本人提供的音乐；
    此前合成夹具直接写该目录 → 每次跑测试被塞满，且应用导入后夹具被清理会留下失效条目
  - 验收：`tests/test_metadata.py::TestFixtureIsolation` 3 项（生成物不在用户目录 /
    再调 `ensure_fixtures()` 后用户目录仍为空 / 6 个合成文件齐全）
- [x] **R8** 用户库清理与导入：删除指向已清空夹具的失效条目「晴天」（同时清 `last_track_id`/`last_position_ms`），
      导入用户指定的 `Blazing Heart (英文版).flac`
  - 根因：`LibraryStore()` 不传路径时 `_path = None`，`load()`/`save()` 全是静默空操作
    （`open(None)` 的 `TypeError` 被 `except Exception` 吞掉）——上一次「删除」实际没落盘。
    现 `__init__` 写明「`path=None` = 纯内存 store」，`load()` 增加 `if not self._path: return` 前置守卫
  - 验收：落盘后库为 2 条（mp4 + flac）；`tools/check_media.py` 确认 FLAC `LoadedMedia`、178s、无解码错误

- [x] **R9** 图标回归不得改写仓库资产：`build.generate_icon(out_path=None)` 支持指定输出路径；
      `tests/test_icon.py` 全部生成到临时目录，并新增「仓库资产未被改写」「仓库图标可被 QIcon 加载」两项断言
  - 起因：回归默认 offscreen（字体库为空，`♫` 画不出来），旧 `test_icon` 直接调 `generate_icon()`
    默认路径，把 `assets/app.ico` 从 14885 B 覆盖成 11515 B 的空白图标 —— 如果把这份文件打包/提交，
    就是「窗口图标空白」的复发
  - 验收：`tests.test_icon` 5 项；提交前用**真实平台**重新生成 `assets/app.ico`（14885 B / 7 尺寸 /
    planes=bitcount=0），并导出 256 尺寸目视确认音符正常

- [x] **R10** 冒烟自检必须与用户曲库隔离：`main.py --smoke` 在创建窗口前把 `APPDATA` 指向
      `tempfile.mkdtemp()`（`atexit` 清理）；`build._real_platform_check()` 同样注入隔离 APPDATA
  - 起因：`build.py` 每次都跑 `exe --smoke <音频>`，smoke 分支走 `MainWindow → store.add_or_update()`，
    store 落在 `%APPDATA%\轻音播放器\data.json` —— **用户真实曲库**。于是每次构建都往库里塞一条
    合成夹具「晴天」，退出时还覆盖 `last_view`/`last_track_id`；夹具清理后就成了失效条目
    （「晴天反复出现」的最终真相）
  - 验收：新增 `tests/test_smoke_isolation.py` 2 项（独立进程跑 `main.py --smoke`，
    APPDATA 预置哨兵 data.json，断言跑完**逐字节不变**且无额外文件）；
    **反向验证**：临时移除 APPDATA 隔离后该模块 2 项立即失败；
    重建一次 EXE 后用户 `data.json` 哈希不变

## S. v2.1.6 播放栏视觉打磨（2026-10-27，用户截图反馈）

> 需求：底部播放控制区「美化一下」（截图圈出 循环 / 上一首 / 播放 / 下一首 + 进度条）。
> 排查中发现两个**功能性问题**，不只是审美：① `prev`/`next` 图标方向画反了
> （prev 画成 ▶|、next 画成 |◀，按钮语义与图形相反）；② 进度手柄是「白心 + 白环」，
> 在浅色主题的白底上**完全隐形**——用户截图里根本看不到手柄位置。

- [x] **S1** `ui/icons.py` 重画控制图标：`loop` 由「300° 圆弧 + 两条斜线当箭头」（16px 下像刷新按钮）
      改为标准 repeat（上下横线 + 两端反向箭头）；`repeat_one` 复用 repeat + 矢量「1」（不用
      `drawText`，小尺寸下字体渲染会歪）；`shuffle` 由 7 段互不相连的碎线改为两条交叉车道 + 箭头；
      `pause` 竖线加宽（0.14→0.16）、`play` 三角收窄一点
- [x] **S2** `prev` / `next` 方向修正：prev = `|◀`（竖线在左、三角朝左）、next = `▶|`
  - 验收：`tools/probe_player_bar.py` + 72px 图标表目视；`tests/test_widgets.py` 断言播放栏存在且方向语义正确（见 S8 说明）
- [x] **S3** 进度/音量滑块：轨道 4→3px；手柄改为**强调色实心圆 + SURFACE 外环**
  - 坑：QSS 手柄三个量必须同时对上，否则退化成方块或隐形
    ① 钮芯必须有色实心（白心白环白底 = 看不见）；
    ② `border-radius` = (width + 2×border) / 2；
    ③ `margin` 决定手柄盒高 = 轨道高 + 2×|margin|，必须 ≥ 手柄总高（seek 总高 14 → `-6`；音量 12 → `-5`）
  - 验收：`TestSliderKnob` 4 项（浅/深色下扫左端像素必须有饱和蓝、四角不得被填满 → 必须是圆）
    **反向验证**：把 `background` 改回 `#ffffff` 后 2 项立即失败
- [x] **S4** 时间标签：`objectName="TimeLabel"`（12px），左端**右对齐**、右端**左对齐**，
      宽度 36→38 —— 时间贴住滑块两端，两侧留白对称
  - 验收：`test_time_labels_snug_to_slider`
- [x] **S5** 播放键：图标 18→20px；加 `QGraphicsDropShadowEffect` 强调色柔和投影（QSS 无 box-shadow），
      主题切换时由 `PlayerBar.refresh_theme()` 重染颜色
- [x] **S6** 控制行与进度行间距 2→6px（原来几乎贴住），按钮间距 6→4px（cluster 更紧凑）
- [x] **S7** `ElidedLabel.minimumSizeHint()` 宽度归零：长标题把 `PlayerBar` 最小宽度顶到
      **1185px > 窗口最小 1100** —— v2.1.3「窗口抖动 + 副标题被省略」的隐患会复发
  - 验收：`test_player_bar_fits_min_window_with_long_title`（长标题下仍 ≤1100，实测 1042）；
    **反向验证**：移除该覆盖后立即失败
- [x] **S8** 回归 + 静态检查 + 版本号 `v2.1.6` + 重建双 EXE
  - 验收：全量回归 **17 进程 240 项全绿**；`ruff check .` 干净；双 EXE smoke + 真实平台检查通过

## v2.1.7 任务（左下浮动工具条美化）

- [x] **T1** 结构重排：三个平级 `QPushButton` → 一个分段托盘
      `QWidget#FloatTray` 内嵌三个透明入口，圆形主题按钮独立在左
      - 动因：三层各自带边框、互不相干，视觉上像三个输入框
- [x] **T2** 圆角修正（本次唯一根因）：`#FloatTextBtn` 原 `border-radius:16px` 配 28px 高，
      **超过短边一半 → Qt 静默退化成直角方块**。现为按钮 10px / 托盘 12px / 主题钮 17px（36 高）
- [x] **T3** 尺寸策略：三个入口由「强制等宽 78px」改为「等内边距 9px + 内容宽」
      - 托盘没有分隔线，眼睛数的是文字之间的空隙；等宽会让「设置」两侧明显空出一截
      - 总宽仍为 288（16+288 = 304 ≤ 312，不压封面）
- [x] **T4** 配色统一：托盘与主题按钮都改 `SURFACE` + `BORDER`；主题按钮不再按 `:checked`
      变蓝（图标已表明目标主题，强调色边框只会抢注意力且让两主题下长得不一样）
- [x] **T5** 悬停可辨：底色 `SURFACE_HOVER` → `SURFACE_ACTIVE`（浅色主题下前者压在白卡片上
      对比仅 ~3%，等于没有反馈）
- [x] **T6** 图标悬停点亮：新增 `_HoverIconButton` 基类，`enter/leave` 重绑颜色角色
      —— QSS 的 `color` 染不动 QIcon；`set_kind()` 保留悬停态用于太阳/月亮切换
- [x] **T7** 新增 `tools/probe_float_bar.py`：真实平台单独渲染浮动条（可指定主题/放大倍数/模拟悬停外观），
      打印 `sizeHint` 校验 304 ≤ 312
- [x] **T8** 回归 4 项：`TestFloatBarStyle`（同托盘 / 圆角不超半高 / 主题钮正圆同高 / 悬停底色可辨）
- [x] **T9** 版本号 `v2.1.7`、全量回归、`ruff check .`、重建双 EXE

## v2.1.8 任务（浮动条对齐 + 主题钮上移 + 版本号右下角）

- [x] **U1** 对齐：浮动条宽 288 → **224**（= 侧栏内容宽度 248-24），右缘与侧栏内容右边界 236 齐平，
      不再跨进内容区把「设置」压到侧栏竖线外
- [x] **U2** 主题钮上移：`FloatBar` 由单行 → 上下两排（上排圆钮 / 下排托盘），
      圆钮腾出的 44px 让托盘收进 224px 内；圆钮/托盘左缘都对齐侧栏内容左边界 12
- [x] **U3** 托盘三等分 + 字号 11 / 内边距 4：224px 内放下三个入口且文字不省略
- [x] **U4** 版本号挪位置：从侧栏底部删掉 → 右下角浮动 `QLabel#VersionLabel`（10px、TEXT_DIM），
      `_position_version_label()` 随 resize/show/主题切换重定位
- [x] **U5** 回归：`test_float_bar_not_overlap_cover` / `test_float_bar_fits_player_bar_indent`
      改判右缘 ≤ 236；新增 `test_width_matches_sidebar_content`、
      `test_float_bar_inside_window`（右缘 ≤ 236）、`test_version_label_at_bottom_right`
- [x] **U6** 版本号 `v2.1.8`、全量回归、`ruff check .`、重建双 EXE

## v2.1.9 任务（导入即复制：受管理曲库）

- [x] **V1** 新增 `app/library.py`：`file_signature`（size+首尾 64KB）、
      `import_into_library`（复制+同内容去重+同名加指纹后缀+`.part` 原子落盘）、
      `is_in_library`、`safe_stem`
- [x] **V2** `app/paths.py` 增加 `library_dir()`（`%APPDATA%/轻音播放器/library`）
- [x] **V3** `ScannerWorker` 增加可选 `library_dir`：先复制再从副本读元数据，
      复制失败跳过并计数；不传则维持旧语义
- [x] **V4** `_start_import` 传曲库目录，完成提示报告复制结果
- [x] **V5** `_remove_from_library`：曲库内副本随移除删除，外部老条目不动（文案区分）
- [x] **V6** 新增 `tests/test_library.py`（9 项）+ e2e `test_import_copies_files_into_library`
- [x] **V7** 版本号 `v2.1.9`、全量回归、`ruff check .`、重建双 EXE

## v2.2 任务（歌词联网补全 + 外观自定义：强调色 / 字号 / 背景）

- [x] **W1** 新增 `app/lyrics_online.py`：LRCLIB 检索（URL 构造 / 脏数据解析 /
      身份门槛打分 / 断网降级）+ 缓存读写（`<track_id>.lrc`，`.part` 原子落盘）
      + `LyricsFetchWorker`（QThread，后台抓、成功发 `found`）
- [x] **W2** 歌词解析扩成 5 级：手动绑定 → 同名 `.lrc` → 内嵌 → 本地缓存 → 联网兜底
      （联网异步；同一首只试一次；结果回来时若已切歌不串词）
- [x] **W3** `Settings.online_lyrics` 开关 + 设置页勾选框；关闭时不发任何请求
- [x] **W4** `ui/theme.py` 外观引擎：`derive_accent`（一个色值派生 hover/dim/soft/on_accent）、
      `clamp_font_scale` + QSS 字号乘法、`set_appearance` 统一入口、`build_stylesheet(scrim=)`
- [x] **W5** `Settings.accent_color` / `font_scale`；`_apply_appearance()` 成为主窗口唯一外观入口
- [x] **W6** `ui/background.py`：`BackgroundLayer`（纯色/渐变/图片，铺满裁切、模糊近似、暗化、
      不透明度）+ 面板半透明 + 浮层不透明兜底
- [x] **W7** `BackgroundConfig` + 三份配置（全部/列表页/正在播放页），`bg_config(page)` 回退规则；
      切页 `_refresh_background()`；`import_background()` 把图片复制进 `bgs/`
- [x] **W8** 设置对话框改三页签（外观 / 背景 / 歌词与统计）：色板 + 自定义色、字号四档、
      背景类型/作用页面/跟随开关/颜色/图片/三个滑块
- [x] **W9** 测试与交付：新增 `test_lyrics_online`(25) / `test_background`(16) /
      `TestE2ELyricsOnline`(5) / `TestE2EAppearance`(14，含 toast 居中)，`test_theme` +9、`test_store` +3；
      全量回归 **22 进程 331 项全绿**、`ruff check .` 干净、`tools/shot.py` 视觉验收、
      双 EXE 重建（55.6MB / 2.4MB，smoke + 8s 存活）、版本号 `v2.2`（`APP_VERSION=2.2.0`）

## v2.2.1 内存优化（封面缓存）

- [x] **X1** `app/covers.py`：`CoverProvider._mem` 由无上限 dict 改为 `_LruPixmapCache`
      （按像素预算 LRU，默认 `CACHE_MAX_PIXELS = 10_000_000` ≈ 40MB）；三处写入走 `put`。
      根因：`track_list.set_tracks` 全量渲染，5000 首 = 5000 张 40px；切歌 280px 大图
      （78400px/张，49 倍）随切随涨、永不回收。
  - 量化（`build/probe_memory.py`）：5000 首列表 + 切 300 首，改前 123MB 无界 → 改后 38MB 封顶
  - 验收：新增 `test_covers_scanner` +4 项（有界 / LRU 淘汰 / 命中置新 / 单张超预算）；
    全量回归 **22 进程 335 项全绿**；`ruff check .` 干净；版本 `v2.2.1`

- [x] **X2** 左下工具条重排（v2.2.2）：设置改**齿轮**圆钮放在主题钮下方；导入音乐 /
      数据目录拆成右侧两个**独立按钮**；侧栏的大蓝「导入音乐」按钮移除
  - 布局：左列 主题 34 + 6 + 齿轮 34；右侧 导入 88 + 6 + 目录 88 = 224（右缘 236）
  - 图标：新增手绘 `gear`（锯齿外轮廓 + 镂空中心孔）。首版「圆环 + 短射线」与 `sun`
    几乎同形，出验收表后作废重画 —— 齿轮就在主题钮正下方，同形等于误导
  - 验收：`test_widgets` +2（42 项）、e2e 断言同步；全量 **22 进程 337 项全绿**；
    `ruff check .` 干净；图标验收表 + 浮动条/整窗截图（深/浅）目检；版本 `v2.2.2`

- [x] **X3** 浮动条放大（v2.2.3）：224×74 → 224×82；圆钮 34→38、按钮 88×34→86×38、
      图标 14→16、字号 11→12
  - 宽度仍卡 224（侧栏内容宽上限），只能纵向放大
  - 顺带修：定位由「播放栏内居中」（只剩 1px）改为**底边固定留 4px** —— 贴太近会被
    窗口圆角遮罩削掉齿轮下半
  - 验收：22 进程 337 项全绿；ruff 干净；整窗裁角 4× 复检齿轮完整

- [x] **X4** 「星月」默认主题（v2.3）：用参考立绘的**视觉语言**（深紫夜空 / 冰蓝月光 /
      莓红点缀 / 星月·羽毛）新做一个主题，并设为**所有背景下的默认主题**
  - 边界：**不嵌入官方立绘**（版权素材不随 EXE 分发），只复刻配色与符号
  - `Theme.BG_ALT` + `qlineargradient` 斜向渐变底；56 颗固定种子星点 + 完整细月牙
    （alpha 14，直径 0.38·min），仅在「星月 + 无自定义背景」时画，不参与 `is_active()`
  - 主题钮改**三态循环**：星月 → 深色 → 浅色 → 星月；图标/tooltip 都指向「下一个」
  - 返工三次：色卡太黑糊成一块 → 提亮 + 渐变；月牙位置三版（右下被播放栏压成残弧、
    裁出画面像污渍 → 右半区竖向 70% 的行下空白带）；羽毛图标首版细线条 16px 糊成
    灰团 → 改实心羽片
  - 验收：22 进程 **344 项全绿**（+`TestThemeCycle` 4、`TestThemeDecor` 3）；ruff 干净；
    截图 `shots/columbina-library-v230r2.png`、图标表 `shots/icons_v230.png`；版本 2.3.1

- [x] **X5** 侧栏圆钮与浮动条对齐（v2.3.2）：用户圈图要求「圆钮改大并对齐」
  - `#IconNav` 46×46 / radius 12（圆角方块）→ **38×38 / radius 19（正圆）**，图标 20→18
  - 与浮动条左列圆钮同尺寸、左缘同在 x=12；加 e2e 断言逐钮比 width/height/x
  - 验收：全量回归全绿；ruff 干净；截图 `shots/columbina-library-nav38.png`、
    `shots/light-library-nav38.png`（浅色 + 黄紫渐变背景，复刻用户那张图的条件）

- [x] **X6** 「空月」主题增强（v2.3.3）：用户给哥伦比娅参考立绘，要求「用角色的元素
      新做一个所有背景的默认主题」——v2.3 已有同角色主题但只有配色 + 月牙
  - 背景装饰层补两个核心元素：**符文圆环**（三层同心圆 + 八枚刻度 + 中心点，
    右上）与**羽饰**（三片描边叶片 + 羽轴，内容区右上）；月牙沿用 v2.3.1 的设置
  - 配色微调：BG `#130e26`→`#120e22`、SURFACE 提亮一档、BG_ALT `#0b1526`→`#0a1220`
  - 装饰名 `"moon"`→`"columbina"`；主题标签「星月」→「空月」；新增 `build/probe_decor.py`
  - 验收：22 进程 345 项全绿；ruff 干净；装饰探针 + 整窗截图（深/浅）逐张目检；
    三次返工全因「看不见」而非「画错」（探针 render 并发 bug / alpha 定档 / 羽饰被面板盖住）

- [x] **X7** 主题改名 + 默认改浅色（v2.3.4）：用户要求「空月换成浅色」「空月名字换成深色」
  - `THEME_LABEL = {"columbina": "深色", "light": "浅色"}`；`DEFAULT_THEME = "light"`
  - 只改显示名：设置 radio / 浮动条 tooltip / 切换 toast 都读 `THEME_LABEL`，
    内部 id 与 `data.json` 里的 `theme` 值不动（改 id 要迁移所有已落盘数据）
  - 同步清理源码里「空月 / 星月」的残留注释与 docstring；DESIGN §12.3 / §15.4 改写
  - 验收：22 进程 345 项全绿；ruff 干净；已重建 EXE

- [x] **X8** 浅色主题按参考图重做（v2.3.5）：用户二次发参考图「浅色做成这样」
  - 色值全部从参考图采样：BG `#eef2fb`、SURFACE `#f5f8fd`、ACCENT `#7389cb`
    （参考图播放键 `#7f97d6` 白字只有 2.88:1，压深到 3.43:1 才过可读性下限）
  - 装饰层重写：1 支 0.9 窗高线描羽毛（裸羽轴伸出画面、两侧不等宽）+ 1 枚带光环的
    罗盘星 + 5 点微光；删掉"18 颗碎星撒满全窗"
  - 三次形态返工（实心星=菱形 / 羽枝=梳子 / 羽片根部硬截断）+ 一次位置返工
    （星被"排序"下拉框遮掉半个）
  - 验收：22 进程 345 项全绿；ruff 干净；灰度分布对齐参考图；EXE 重建

- [x] **X9** 深色主题按参考图重做（v2.3.6）：用户发深色参考图「深色做成这样」
  - 五层重画：径向辉光 → 星尘 → 轨道环（带刻度）→ 玻璃月牙 → 罗盘星 → 柔焦浮羽
  - 三个坑：两段圆弧拼月牙会留直线弦（改 `subtracted()` 差集）；发光不是整体涂白
    （亮在边缘，月内/月外差 14 阶 vs 参考 11）；浮羽不能用线描（改横向渐变 + 羽枝）
  - 位置取舍：星从环右侧挪到环正下方（右侧是列表列，会被图标压住）
  - 验收：22 进程 345 项全绿；ruff 干净；灰度采样对齐；EXE 重建

- [x] **Y1** 联网歌词检索改进（v2.4.0）：用户「改进联网歌词」
  - 有序查询计划：`/api/get` 精确（带 album/duration）→ search（原艺人）→ search（主艺人）
    → `q=` 自由文本；命中高信任度即早停（多为一首 1 个请求）
  - 标签清洗 `clean_title` / `clean_artist`：全角转半角、括号噪声、`feat.` 尾巴、
    前导音轨号、破折号噪声后缀、多艺人切分（不切 `&` 和 `,`）
  - 打分收紧：身份门槛改为「歌名对得上 or 时长差 ≤2s」，移除"只有艺人对上"；
    同名翻唱 −1.5；包含式比对加长度校验；同步稿单独分区优先
  - 负缓存 `<track_id>.miss`（TTL 7 天）+ 歌词区右键「重新联网匹配歌词」
  - 限流 429/503 用 `FetchOutcome.aborted` 与"未命中"区分，绝不误写负缓存；
    请求间隔 250ms（官方建议）
  - 真实联网命中率 **6/11 → 10/11**；`test_lyrics_online` 33 → 71 项，e2e 5 → 6 项


- [x] **Y2** 图标清晰度与齿轮重画（v2.5.0）：用户圈出左下设置齿轮「优化一下图案」
  - 先量化：圆钮 45 设备像素、齿轮只有 9×10 → 不是画得丑，是被放大糊掉
  - 根因：`_paint()` 按 16×16、DPR=1 生成位图，高分屏上被平滑放大
  - 修：`device_ratio()` + 按 `size×DPR` 渲染 + `setDevicePixelRatio`；缓存键带 dpr；
    新增 `make_pixmap()` 供 QLabel（`QIcon.pixmap(n,n)` 会降采样回去）
  - 齿形重画：齿深 0.16→0.12、齿顶平台 0.28→0.44、斜边→0.09、轴孔→Ø0.30
  - 验收工具补「设备像素」第三行；新增 4 项图标渲染回归
  - 布局未变（浮动条仍 224×82，右缘 236）；22 进程全绿；EXE 重建


- [x] **Y3** 主题钮图标改为月亮（v2.5.1）：用户圈出左下浮动条**上方**圆钮，「画成月亮」
  - 先定位：红圈盖住了钮体，改从代码确认该钮是主题切换，原图标 = `feather`
  - 语义澄清：钮上画的不是当前主题，而是「点下去会切到哪个主题」——
    浅色→月亮（切深色）、深色→太阳（切浅色），所以用户截图（浅色）上是羽毛
  - 画法：`outer.subtracted(inner)` 两圆差集，**不用** `arcMoveTo/arcTo` 拼弧
    （两段弧端点间会连出直线弦，月牙尖角被削平成「灰色 D」，同 v2.3.6 装饰月牙的坑）
  - 参数（20/24 设备像素上比过）：外圆 R=0.42、内圆 0.90R 右移 0.16、整体转 −30°
  - 只改三处：`icons.py` 画法、`theme.THEME_ICON` 表、`float_bar` 初始值；
    持久化的主题 id 仍是 `columbina`/`light`，无数据迁移
  - 新增回归 3 项：`test_moon_is_crescent_not_disc`、`test_moon_fills_the_canvas`、
    `test_theme_icons_are_moon_and_sun`；22 进程 **400 项全绿**；
    对比图 `shots/v251-moon-before-after.png`


- [x] **Y4** 数据目录可选择 / 便携模式（v2.6.0）
  - 需求：新电脑能直接用 + 数据位置自己选，"或者直接放到软件目录里"
  - 四级优先级：`QY_DATA_DIR`（测试/自检）> 便携模式（软件目录 `data/`）>
    指针文件 `%APPDATA%/轻音播放器/location.txt` > 默认 APPDATA
  - **指针不能记进 data.json**：data.json 自己要被搬走，记在它身上一搬家就找不着
  - **便携模式只在打包后生效**：开发态 `exe_dir()` 是仓库根，手建一个 `data/` 会让所有
    「改 APPDATA 做隔离」的测试写进仓库、污染用户曲库；设置页按钮在源码态直接禁用
  - **smoke 隔离加一层**：`--smoke` 同时设 `APPDATA` + `QY_DATA_DIR`，压过便携与指针
  - 迁移：目标必须空目录 → 复制 → 逐文件核对字节 → 才删源；失败/取消清理目标、源不动
  - UI：设置 → 存储（当前目录 / 模式 / 更改位置 / 放到软件目录 / 恢复默认 / 打开目录），
    迁移跑在 QThread 里带进度与取消，完成后提示重启
  - 新增 `tests/test_storage.py` 27 项 + 设置页 E2E 1 项；23 进程 **428 项全绿**；DESIGN §21


## v2.1 依赖关系

```
K1 → K2 → K3 → L1 → L2 → L3 → M1 → M2 → M3 → M4 → N1 → N2 → N3 → N4 → O1 → O2 → O3 → O4 → P1 → P2 → Q1 → Q2 → Q3 → Q4 → Q5 → Q6 → Q7 → Q8 → Q9 → R1 → R2 → R3 → R4 → R5 → R6 → R7 → R8 → R9 → R10 → S1 → S2 → S3 → S4 → S5 → S6 → S7 → S8 → T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → U1 → U2 → U3 → U4 → U5 → U6 → V1 → V2 → V3 → V4 → V5 → V6 → V7 → W1 → W2 → W3 → W4 → W5 → W6 → W7 → W8 → W9
```

- [x] **Y5** 浮动工具条四个入口并成一排（v2.6.1）
  - 需求：用户圈出主题/设置/导入音乐/数据目录四个控件，「这四个并成一排」
  - 布局：`QHBoxLayout` 单行，`38+4+38+4+68+4+68 = 224`，高 38（原 3×2 网格 224×82）
  - 文字按钮 68 宽的依据：字号可放大到 1.30 倍 → 12px 变 16px → 4 个中文字 64px，
    扣掉 2px 边框剩 66，刚好放得下；曾经取 65 会在最大字号下裁 1px
  - QSS 侧必须补 `padding:0px`，否则基础 `QPushButton{padding:6px 10px}` 再吃掉 20px
  - 竖直定位改为「在播放栏内垂直居中」（`PLAYER_BAR_HEIGHT` 提成常量），贴底会显得下沉
  - 4 处旧断言按单行几何重写（DESIGN §22.5），新增 `test_single_row_layout_is_exactly_sidebar_width`
  - 验收图 `shots/float_v261_{light,dark}.png`

- [x] **Y6** 歌词导入 + 联网进度/来源 + 匹配率提升（v2.6.2）
  - 需求：用户「歌词可以自己导入并识别，联网匹配歌词可以显示进度和来源，提高匹配率」
  - 手动导入：歌词区右键「导入歌词文件…」（单首，`_bind_lyrics_file` 识别同步/纯文本）
  - 批量导入：右键「批量导入歌词…」选多份 `.lrc`，按文件名归一（小写、去标点、含 CJK）
    匹配曲目（`app/lyrics_import.py`：`normalize_key` / `track_keys` / `match_lrc_files`）；
    键 = 音频文件名 → 标题 → 艺人 → 标题+艺人，歧义键（一键多曲）跳过不误绑
  - 联网进度/来源：`fetch_outcome(..., progress=cb)` 每查询前回调 `(cur, total)`；
    `LyricsFetchWorker.progress` 信号 → 歌词区显示检索进度，命中后标注「来源：LRCLIB」
  - 匹配率：`lookup_plan` 追加 `q=标题+主艺人` 全文本兜底查询；`_NOISE_WORDS` 扩
    （国语/粤语/日语/闽南语/mv/live at），脏标签清理更彻底
  - `_lyrics_cache` 由 2 元组扩为 3 元组 `(synced, plain, source)`，所有解包同步更新
  - 新增回归 `tests/test_lyrics_import.py`（11 项）+ 联网进度 2 项 + 计划 1 项
  - 验收：24 进程 **444 项全绿**，`ruff check .` 干净；真实联网命中率 5/5

- [x] **Y7** 修复：联网匹配中断时歌词区卡死在「正在找」（v2.6.3）
  - 现象：用户反馈「没显示」——联网超时/限流/预算耗尽时 `fetch_outcome` 返回
    `aborted=True` 且无文本，`LyricsFetchWorker.run()` 既不 `found` 也不 `missed`，
    界面永远停在「正在联网匹配歌词…」
  - 修法：worker 新增 `aborted = Signal(str)`，中止时发它（仍**不发** `missed`，
    不落负缓存）；`_on_online_lyrics_aborted` 把空状态换成「联网匹配失败，请稍后重试
    \n可右键「重新联网匹配」再试一次」
  - 测试：`test_stays_silent_when_aborted_by_rate_limit` 改名
    `test_emits_aborted_not_missed_when_rate_limited`（断 abort 发、missed 不发）；
    e2e 新增 `test_online_aborted_shows_retry_hint_but_no_negative_cache`
  - 验收：24 进程 **445 项全绿**，`ruff check .` 干净

- [x] **Y8** 在线搜索歌词 + 歌词播放动效（v2.6.4）
  - 需求：用户「匹配不了歌词用户可以在软件内打开网页自己匹配歌词」「歌词播放添加更多
    效果（放大 / 打字机 / 颜色逐渐覆盖）」
  - 在线搜索：歌词区右键「在线搜索歌词…」→ `build_web_search_url(标题, 艺人)` 拼
    `lrclib.net/search?q=`，`QDesktopServices.openUrl` 开系统默认浏览器（用户选轻量方案）
  - 歌词动效（单选，`Settings.lyrics_effect`，none/zoom/typewriter/karaoke）：
    - `ui/lyrics_panel.py` 改用 `QStyledItemDelegate` 自绘歌词行，支持四种效果；
      保留 `QListWidgetItem.text()/foreground()` 兼容旧测试
    - 逐字进度靠「行内进度 0~1」：`update_position` 算 `_line_progress`，
      最后一行固定 3000ms 行时长；zoom +6px、其余 +3px（`_bump_font` 像素优先）
    - 平滑：QMediaPlayer `positionChanged` 在 PySide6 无 `setNotifyInterval`，
      改主窗口 100ms `QTimer` 播放时轮询 `position()`（暂停/停止即停）
  - 坑：delegate 的 `option.font` 经 QSS 是 `pixelSize=13, pointSize=-1`（与
    `item.font()` 的 `pointSize=9` 不同），直接 `setPointSize(-1+Δ)` 会把当前行缩成
    2pt 一小截；karaoke 未唱部分用半透明 TEXT_DIM（alpha 90）才有「亮/暗」分界
  - 测试：`build_web_search_url` 3 项、`TestLyricsEffect` 5 项、settings 持久化 2 项
  - 验收：24 进程 **455 项全绿**，`ruff check .` 干净；探针截图
    `shots/lyrics_effect_{light,dark}.png` 四效果并排目检通过

- [x] **Y9** 纯文本 `.txt` 歌词导入识别（v2.6.5）
  - 需求：用户「`D:/浏览器/唯有追赶风的方向 (Only By Chasing the).txt` 做个导入识别」
  - 现象：浏览器下载的歌词常是 `.txt`，头部带「歌名 / 作词 / 作曲 / 编曲…」信息块，
    直接当纯文本会把标题与职员表混进歌词
  - 实现：
    - `app/lyrics.py` 新增 `strip_meta_lines()`：`_PLAIN_META_LABEL` 正则匹配
      「作词/作曲/编曲/填词/词曲/演唱/混音/制作/出品/发行/和声/吉他…」+ 冒号行并剔除；
      首行歌名仅在「下一非空行是职员表行」时才删（避免误删第一句歌词）
    - `lyrics_from_text()` 在 `parse_plain()` 前统一过 `strip_meta_lines()`，
      手动绑定 / 同名文件 / 内嵌 / 缓存 / 联网各路径一致生效
    - 手动导入对话框过滤 `*.lrc` → `*.lrc *.txt`；批量导入扫描同时收 `.lrc` 与 `.txt`
      （`match_lrc_files()` 只取去扩展名的 basename，天然兼容，无需改逻辑）
  - 测试：`TestStripMetaLines` 4 项（剔除标题+职员表 / 全角冒号 / 无元数据不误删 /
    无信号不删首行）、`test_matches_txt_extension_too`
  - 验收：全量回归 24 进程全绿，`ruff check .` 干净

- [x] **Y10** 纯文本歌词联网对齐成带时间轴 LRC（v2.6.6）
  - 需求：用户「歌词导入进去可以自动跟歌识别，可以滚动」；澄清后选定
    「联网自动对齐（自备 Key）」，触发方式「导入后询问 + 右键手动」
  - 背景：纯文本歌词没有时间戳，本无法跟歌滚动；必须先把每行配到音频时间轴
  - 选型：**LyricTimestamps API**（支持 multipart 直接上传本地音频，免费 15 分钟/月、
    最长 12 分钟/首、直传 30MB；QuickLRC 只收公开 URL 不适合本地文件）
  - 实现：
    - `app/lyrics_align.py` 新增：`verify_key`（GET /v1/usage）、
      `align_lyrics`（创建 multipart 任务 → 轮询 → 下载 LRC，进度回调、错误分类、
      网络可注入 `fetch`）、`describe_error`、`LyricsAlignWorker(QThread)`
    - `Settings.lyrics_align_api_key`（v2.6.6，存 data.json，不进日志）
    - 设置「歌词与统计」页加 Key 输入框（editingFinished 才保存）
    - 导入纯文本后 `_maybe_offer_align` 弹「是否联网对齐」；歌词区右键
      「联网对齐歌词」`_align_lyrics_for_current`；对齐成功缓存到
      `lyrics_cache/<id>.lrc` + 解除纯文本手动绑定，之后跟歌滚动
  - 关键坑：错误 key 在**读端点**会被当匿名游客只回 60 秒预览，所以创建任务前
    必须先 `verify_key`；必须 multipart form-data，JSON body 会被静默接受后 400
  - 测试：`tests/test_lyrics_align.py` 26 项（verify_key / multipart / happy path /
    missing_key / no_audio / 超限 / 401 / 429 / failed / soft_fail / 轮询 / worker /
    key 持久化）
  - 验收：全量回归全绿，`ruff check .` 干净

- [x] **Y11** .txt 转 .lrc 文件：对齐产物写成同名 .lrc 到歌曲目录（v2.6.7）
  - 需求：用户「添加一个可以把 .txt 文件转 .lrc 文件的功能，歌曲能识别歌词」
  - 澄清：时间轴来源复用联网对齐（LyricTimestamps），产物位置选「歌曲同目录同名 .lrc」
  - 实现：
    - `app/lyrics_align.py` 新增 `sidecar_lrc_path()` / `write_sidecar_lrc()`（原子写）
    - `_apply_aligned_lrc` 从「写缓存」改为「写同名 .lrc」；`_start_align` 前检查
      同名 .lrc 已存在则弹覆盖确认；菜单/弹窗文案改为「转成 .lrc 文件」
    - 同名 .lrc 是 `_resolve_lyrics` 第 2 级来源，比缓存更直观、可迁移、可手动管理
  - 测试：`TestSidecarLrc` 5 项（路径 / 创建 / 覆盖 / 失败返回 None / 空入参）
  - 验收：全量回归全绿，`ruff check .` 干净

- [x] **Y12** 多源联网歌词：LRCLIB + 网易云 + QQ音乐，并行取最优（v2.6.8）
  - 需求：用户「添加其他音乐平台用于识别歌词」；澄清后选网易云 + QQ、免 key 直连、
    多源并行取最优；离线显示靠既有缓存落盘，无需新做
  - 实现：
    - `app/lyrics_online.py` 增 `fetch_best_hit()`（返回 `(LyricHit|None, aborted)` 的
      `fetch_outcome` 变体，纯增量，供跨源统一打分）
    - `app/lyrics_multi.py` 新增：网易云 / QQ 两源（搜索+歌词，带 Referer、fetch 可注入、
      遍历前 3 候选挑通过门槛的）、`fetch_outcome_multi`（ThreadPoolExecutor 并行三源 +
      统一 `pick_best`）、`MultiSourceWorker`（`found` 带来源名）
    - `ui/main_window.py` 改用 `MultiSourceWorker`；`_on_online_lyrics` 增 `source` 默认参；
      缓存命中来源标签改「来源：联网（缓存）」
  - 关键坑：QQ 歌词接口缺 `Referer` 返回 -1310；网易云伴奏版排第一且无歌词须遍历候选；
    `fetch` 注入签名统一 `(url, timeout)`，三源各自默认 getter 闭包了 Referer
  - 测试：`tests/test_lyrics_multi.py` 31 项（URL / 解析 / 候选挑选 / 多源协调 / worker）；
    `test_e2e.py` 的 `TestE2ELyricsOnline` mock 目标从 `LyricsFetchWorker` 改
    `MultiSourceWorker`、`found` 信号改三参数
  - 验收：全量回归全绿，`ruff check .` 干净

- [x] **Y13** 本地歌词对齐：离线「纯文本 → 带时间轴 LRC」（v2.6.9）
  - 需求：用户「软件内制作一个类似 LyricTimestamps 的功能」；澄清后选「轻量离线对齐」
    （静音检测 + 行均分，非 AI）+「本地优先、联网兜底」
  - 选型：解码用 **miniaudio**（纯 C 无 numpy，打包 +1~2MB），替代 numpy+soundfile（+30MB）
  - 实现：
    - `app/lyrics_local_align.py` 新增：`decode_mono`（open bytes + miniaudio.decode，
      绕开中文路径坑）、`rms_envelope`、`detect_speech`（动态阈值静音检测）、
      `assign_timestamps`（歌词行铺在有声段上、跳过前奏/间奏/尾奏）、`align_local`、
      `LyricsLocalAlignWorker(QThread)`
    - `requirements.txt` 加 `miniaudio`；`lyrics_panel.py` 右键加「本地对齐」信号 +
      「联网对齐」保留；`main_window.py` 新增 `_start_local_align` /
      `_align_lyrics_local_for_current`，`_maybe_offer_align` 默认走本地，
      `_apply_aligned_lrc` 加 `source_label` 区分本地/联网对齐
  - 关键坑：miniaudio `decode_file` 对**中文路径**解码失败（-7，C 层 ANSI）→ 走
    `decode(bytes)`；`samples` 是 `array.array('f')`，纯 Python 分帧 RMS 够快无需 numpy；
    LRC 时间戳用 `[mm:ss.xx]` 百分秒与 `parse_lrc` 兼容
  - 测试：`tests/test_lyrics_local_align.py` 17 项（标准库 wave 生成正弦波+静音合成音频，
    断言解码/静音检测/时间戳分配/LRC/worker；含「解码器缺失优雅降级」「顶层不得 import
    miniaudio」两项打包防回归）
  - 验收：全量回归全绿，`ruff check .` 干净

- [x] **Y14** 更新版本：v2.6.9 打包（修 cffi 漏收 + smoke 挂死）
  - 需求：用户「更新软件版本」
  - 阻塞：产物能编出来，但 `--smoke` 永久挂住 → 定位到两个独立问题
  - 修复：
    - `build.py` 加 `--hidden-import _cffi_backend`（`_miniaudio.pyd` 在 C 层运行时
      import，PE 扫描抓不到）；`requirements.txt` 显式声明 `cffi`
    - `app/lyrics_local_align.py` 改延迟导入（`_decoder()`）+ 新增 `no_decoder` 错误码：
      可选依赖缺失不得让主程序起不来
    - `build.py` 的 `smoke_test` 重写为 Popen + 文件重定向 + 超时 `taskkill /T` 杀树
      （原 `subprocess.run(capture_output=True)` 在 onefile 子进程弹错误框时永久等 EOF）
    - `main.py --smoke` 增加解码器探测，缺 miniaudio 直接让构建失败
    - `build.py` 的 `_read_logs` utf-8 → gbk 回退（windowed 产物按 cp936 写日志）
    - `build.py` 的 `generate_icon()` 改为仅图标缺失时生成，避免 offscreen 覆盖正式图标
  - 测试：新增 `tests/test_build.py` 4 项；`test_lyrics_local_align.py` +2 项
  - 验收：28 进程 **543 项全绿**；两变体 smoke + 真实平台检查通过；`assets/app.ico`
    md5 仍为 `9f4bdcdf12d625c16cc998e4f7ae40f0`


- [x] **Y15** 双语歌词：一句 = 原文 + 译文（v2.6.10）
  - 需求：用户给双语 `.txt`（英文行 / 中文行交替），反馈「跟歌曲匹配不上，双语歌词的
    歌词效果应该一起实现」
  - 根因（实测）：74 行被当 74 句，时间轴压缩一半、译文晚半句、动效各走一遍
  - 实现：
    - `app/lyrics.py`：`has_cjk` / `is_bilingual_alternating`（整份文件 ≥85% 交替才
      判双语，挡住「中文歌夹英文副歌」的误配对）/ `pair_bilingual` /
      `merge_translations`（同时间戳两行合并）/ `format_lrc` + `format_lrc_stamp`
    - `LyricLine` 加 `translation` 字段；`lyrics_from_text` 同步分支自动合并
    - 本地对齐按句铺时间轴，译文同时间戳跟在原文后；联网对齐只上传原文、按行序回填
      译文（行数不符则原样返回）
    - `ui/lyrics_panel.py`：delegate 一层两行（译文小 3px + alpha 165）、item 高度
      自适应、`_typed_split` 按两行字符总数推进逐字、`set_plain` 也按句配对
  - 测试：`test_lyrics.py` +19、`test_lyrics_local_align.py` +3、
    `test_lyrics_align.py` +4、`test_widgets.py` +6（新增 `TestBilingualLyricsPanel`）
  - 视觉验收：`tools/probe_bilingual_lyrics.py` 出浅/深两套四格对比图
    （`shots/bilingual_lyrics_{light,dark}.png`），确认两行不裁切、整句一起高亮、
    karaoke 深浅分界、打字机「原文打完才轮到译文」
  - 验收：28 进程 **576 项全绿**；`ruff check .` 干净；两变体 exe 重新打包（单文件 67.4 MB）通过


- [x] **Y16** 修：歌词播放时一直往上滚动（v2.6.11）
  - 反馈：用户「歌词播放时一直往上滚动」
  - 根因：`visualItemRect()` 给的是**视口坐标**，`bar.value()` 是**内容坐标**；原代码
    直接把视口坐标当滚动目标，漏掉已滚动距离 → 每句只挪一点点，当前句永远滚不到中间
  - 为什么现在暴露：双语条目两层（58px）使视口可见行数从 8 降到 5，老 bug 被放大
  - 修法：`_scroll_target()` 换算成内容坐标（`bar.value() + rect.top() + h/2 - vp/2`），
    动画中途重算也不会漂移
  - 验证工具：`tools/probe_lyrics_scroll.py`（逐句推进打印 value / top / 目标 / 应得）
  - 测试：`TestLyricsAutoscroll` 2 项（滚到目标真的居中 / 目标含 value）；删掉一条
    offscreen 下动画像素抖动 13px 的脆弱用例
  - 验收：28 进程全绿；两变体 exe 重新打包（单文件 67.4 MB）通过


- [x] **Y17** 修：前奏长的歌歌词对不上（v2.6.12）
  - 反馈：用户「歌曲前奏长歌词匹配不对」；实测确认那份 `.lrc` 来自**本地对齐**
    （37/37 逐句复现，用户误以为是联网对齐）
  - 量化：以联网歌词为真值，《何者》30 句改动前 首句 −6.78s / 中位 7.24s / 最大 19.75s
  - 否决三条路（实测）：静音合并阈值 35ms 仅 18 段；人声频段带通无增益（1.12 vs 1.10）；
    能量分位门限反而更差（10~12s）
  - 实现：
    - `line_weight()` + 权重中点分配：中位 7.24 → 6.04s、最大 19.75 → 13.70s；
      等权句退化为原均匀铺，旧断言零改动
    - `shift_lrc()` 整体偏移（钳位不为负、正文方括号不碰、双语同时间戳一起动）
    - 菜单拆 `_build_menu()`；改名「本地近似·免 Key」/「联网精确·需 Key」；
      新增「整体提前/延后 0.5 秒」（未同步时置灰）
    - `_shift_current_lyrics()` 平移 → 写回 sidecar `.lrc` → 按当前播放位置重新高亮
    - 本地对齐完成提示明确「近似、可能差几秒，可微调」；未配 Key 引导精确对齐
  - 验收工具：`tools/probe_align_intro.py`、`tools/eval_align.py`（真值缓存）
  - 测试：`TestShiftLrc` 10 项、`TestAssignTimestamps` +4、`TestLyricsMenu` 3 项
  - 验收：28 进程 **596 项全绿**；ruff 干净；两变体 exe 重新打包（单文件 67.4 MB）


## v2.1 验收命令

```bash
cd music-player
env -u PYTHONPATH .venv/Scripts/python.exe run_tests.py
env -u PYTHONPATH .venv/Scripts/python.exe -m ruff check .
env -u PYTHONPATH .venv/Scripts/python.exe build.py
```

## v2.9.0 任务（歌词自定义颜色覆盖：动态渐变 + 逐句取色）

> 设计见 DESIGN.md §37。基线：当前工作区（v2.8.3/v2.8.4 改动尚未提交）。
> 分支：`feat/lyrics-color-v2_9_0`。原则：`enabled=False` 必须是旧行为的完全等价路径。

### A. 后端纯逻辑（无 Qt 依赖，先行）

- [x] **A1** `app/models.py`：新增 `LyricsColorConfig`（enabled/trigger/gradient/color_a/color_b/direction/speed/transition）
      与 `COLOR_TRIGGERS/COLOR_DIRECTIONS`；`Settings.lyrics_color` + `to_dict/from_dict`（`_as_*` 钳位、非法枚举回默认）
  - 验收：round-trip、脏数据回默认、缺字段无损
- [x] **A2** `app/paths.py`：`lyrics_colors_dir()`（与 covers/bgs 同级，`_subdir`），并入 `DATA_SUBDIRS` 以便整套迁移
  - 验收：目录随数据根走；迁移清单含它
- [x] **A3** 新模块 `app/lyrics_colors.py`：`load/save/set/clear`，键=时间戳，`base_dir` 可注入；坏 JSON/非法色值跳过；空映射删文件
  - 验收：单测覆盖 round-trip、损坏容错、清除、原子写
- [x] **A4** 单测 `tests/test_lyrics_colors.py` + `tests/test_store.py`（Settings 新字段）
  - 验收：隔离重跑全绿

### B. 渲染（依赖 A）

- [x] **B1** `ui/lyrics_panel.py`：`_draw_line` 支持 `(a,b)` 双色 + 方向 + transition；`enabled=False` 走原分支
- [x] **B2** panel：`set_color_config` / `set_line_colors`；逐行颜色解析与缓存
- [x] **B3** 时间模式：`QTimer(33ms)` 仅 `enabled && trigger=="time" && visible && synced` 启动；每 tick 只 `_update_row(当前行)`；`hideEvent/showEvent` 停启
- [x] **B4** 与 4 种 effect 正交：none/zoom/typewriter/karaoke 组合自测；译文用次级色不参与强扫光
- [x] **B5** `tests/test_widgets.py`：颜色解析、进度/时间两模式、timer 启停条件、effect 组合不崩
  - 验收：隔离重跑全绿

### C. 接线（依赖 B）

- [x] **C1** `ui/settings_dialog.py`：歌词页「歌词颜色覆盖」区（启用/触发/方向/A/B/速度/过渡），发 `lyrics_color_changed(object)`
- [x] **C2** `ui/main_window.py`：切歌加载 sidecar 并下发；`_on_settings_lyrics_color`；`line_color_requested`→`QColorDialog`→保存重下发
- [x] **C3** panel 右键菜单（仅 synced）：这一句设置颜色 / 清除这一句 / 清除本曲；接新信号
- [x] **C4** `tests/test_e2e.py` 新类 `TestE2ELyricsColor`（独立进程）：启用→下发→面板生效；逐句色持久化；清除
  - 验收：patch `QColorDialog` 后跑通

### D. 验收与交付

- [x] **D1** `run_tests.py` 全量回归（后台，独立进程）→ **32/32 模块全绿 15m44s**
- [x] **D2** `ruff check .` 干净
- [x] **D3** `build.py` 双产物 + smoke + 真实平台；`tools/probe_lyrics_effect.py` 增 `--color` 出图复核
  - onefile 56.8MB / onedir 2.9MB，两版 smoke + 真实平台 8s 通过；出图 `shots/lyrics_color_{progress,time,light}.png`
- [x] **D4** `app/version.py → 2.9.0`；更新 DESIGN/TASK 勾选与记忆

---

## v2.9.1 任务（双语译文不跟着变色）

- [x] **E1** 用探针复现：浅色主题 + 双语 + `karaoke` + 颜色覆盖 → 译文整行 `_dimmed` 单色
- [x] **E2** `_paint_block`：译文复用原文 `pair`（去掉 alpha 205）；两行各算自己的 `band`；译文传 `sweep=False`
- [x] **E3** `_draw_line` 增加 `band` / `sweep`；karaoke 分支 `sweep=False` 时整行铺完整渐变
- [x] **E4** `_flow(rect → band)`：vertical / diagonal 用本行上下边界，修「译文只能取到下半段」
- [x] **E5** `tests/test_widgets.py::TestLyricsColor` 补 2 项（译文同 pair + sweep=False / _flow band）
- [x] **E6** 视觉复核：`shots/lyrics_color_bilingual_after.png`、三种 direction、浅色+深色
- [ ] **E7** 全量回归 + ruff + 打包 smoke + `--check` 输出 v2.9.1

---

## v2.9.2 任务（译文行与主歌词同步扫光）

- [x] **F1** `_typed_split(..., sync=False)`：karaoke 走同步口径（两行各按自身长度 × p）
- [x] **F2** `_paint_block`：`sync=(effect=="karaoke")`；译文恢复参与扫光，保留 band；删 `sweep`
- [x] **F3** `_dimmed()` alpha 90 → 110（未唱段仍认得出色系）
- [x] **F4** 测试改写 + 新增：`test_bilingual_translation_shares_pair_and_scans_in_sync`、
      `test_karaoke_sync_typewriter_staggered`
- [x] **F5** 视觉复核：25% / 50% / 75% 三档，两行明暗分界按各自比例对齐
- [ ] **F6** 全量回归 + ruff + 打包 smoke + `--check` 输出 v2.9.2

---

## v3.0.0 任务（本地 AI 强制对齐：逐字时间轴）

> 依赖顺序严格自上而下。**Phase 0 不过关就停在 Phase 0，不改方案硬上。**

### P0. 可行性关卡（阻塞后续全部）

- [x] **P0-1** `pip install faster-whisper`（含 ctranslate2 4.8.4 / av / onnxruntime）装进 venv
- [x] **P0-2** 合成音频跑 `transcribe(word_timestamps=True)`，确认输出词级时间戳结构
- [x] **P0-3** PyInstaller 最小探针 exe：能 import ctranslate2 + 跑一次推理
      （**必须 ctranslate2==4.6.0 + setuptools<81**；4.8.4 在 frozen 环境加载模型必 segfault）
- [x] **P0-4** 实测体积增量，回填 DESIGN 40.7；确定分发策略（B：运行时内置 + 模型首下）
  - 验收：4 条全过；任一失败 → 停下来向用户报告并给替代方案
  - 结果：AI 增量 **164MB**、模型 **142MB**；onnxruntime(45.6MB) 与 hf_xet(9MB) 可排除

### A. 数据模型与解析

- [x] **A1** `app/lyrics.py`：新增 `WordSpan`，`LyricLine` 增 `words` 字段（默认空，零回归）
- [x] **A2** 增强 LRC 逐字标签解析：`[mm:ss.xx]<mm:ss.xx>字` → 填 `words`
  - 关键约束：段内文字不 strip（英文空格）；末尾空段=结尾戳补 `end_ms`；
    首标签前的残留文字并入第一段；多时间标签按 `t - times[0]` 平移；**`offset` 同步平移逐字**
- [x] **A3** `app/paths.py`：`lyrics_words_dir()`；`DATA_SUBDIRS` 增 `lyrics_words`
- [x] **A4** `app/lyrics_words.py`：sidecar 读写（键=行 time_ms），坏数据逐条跳过
  - 另含 `attach_words()`：贴回时校验「字元拼接 == 行文本」，不等则只丢该行
- [x] **A5** 单测：`tests/test_lyrics_words.py`（**22 例**：roundtrip / 坏 JSON / 键漂移防护 / 文本不匹配丢弃）
  - 验收：`test_lyrics_words` + `test_lyrics` + `test_lyrics_colors` + `test_lyrics_multi` 全绿 ✅

### B. 对齐引擎（依赖 P0）

- [x] **B1** `app/lyrics_asr.py`：L1 声道 mid 提取 + L2 faster-whisper 推理（延迟导入）
  - L1 用 miniaudio 立体声解码取 `(L+R)/2`；左右几乎一致（伪立体声）时不提取，免得白降信噪比
  - `ensure_model()` 首下（镜像 `hf-mirror.com`），`model_ready()` 要求 4 个文件齐全
  - 真机实测：`transcribe` 跑通，6 词 / 2 秒音频 9.7s（含模型加载）
- [x] **B2** L3 序列比对：difflib 把识别词映射回原文字级窗口（`_match_windows` + `_spread` + `_fill_gaps`）
- [x] **B3** L4 能量谷吸附：`snap_to_energy()` ±120ms 找 RMS 极小点，受 `MIN_CHAR_MS` 保护
  - 另加 `rms_fast()`：向量化 RMS，比纯 Python `rms_envelope` 快两个数量级（单测钉住两者同口径）
- [x] **B4** L5 置信度自检：匹配率 <0.55 或平均概率 <0.25 → `low_confidence`，**不写盘**
  - 真机验证：合成音（无人声）被 whisper 幻觉成「你认识了我吗」，p=0.02~0.48 → 正确拒绝
- [x] **B5** 单测：`tests/test_lyrics_asr.py` **26 例**，全部用构造的词时间戳，不加载模型
- [x] **B6**（临时新增）`retime_lines()`：用首字时刻重打行时间轴，为「行级 6.04s → <0.5s」备好手段

### C. 渲染接入

- [x] **C1** `ui/lyrics_panel.py`：`_typed_from_words()` 按字窗口求 `typed`；无 words 走原路径
  - 实测：`_draw_line` 只认整数 `typed`，所以画法一行没改，只换 `typed` 来源（零风险根）
- [x] **C2** 确保 karaoke 同步口径、颜色覆盖、band 逻辑在有 words 时仍正确
  - 译文无词元 → 按 `typed/len(text)` 比例推进，与 v2.9.2 同口径；颜色覆盖路径完全正交
- [x] **C3** 单测：有/无 words 两条路径各自断言，且无 words 时输出与 v2.9.2 完全一致
  - `tests/test_widgets.py` 新增 6 例全绿；视觉探针 `tools/probe_lyrics_words.py` 复核
    （2000ms：线性亮 4 字 / 逐字亮 7 字，与 stdout 一致）

### D. 界面与批量

- [x] **D1** 歌词右键「AI 对齐歌词（逐字）」+「清除本曲逐字数据」，无同步歌词时置灰
- [x] **D2** 设置→歌词页「AI 对齐」区：模型档位（tiny/base/small，默认 base）、批量入口、清空字级数据
- [x] **D3** 批量对齐对话框 `AiBatchAlignDialog`：逐首串行、可停止、失败不中断并有清单
  - 关闭保护：跑着时 `closeEvent` 忽略（避免带活线程析构）
- [x] **D4** 模型缺失时弹「需要下载 XX MB」确认；失败收敛成中文 toast，绝不静默

### E. 打包与验收

- [x] **E1** `build.py`：解禁 numpy + `--collect-binaries ctranslate2` + 排除 onnxruntime/hf_xet
  - `av`（68MB）**本轮保留**：stub 顶替只省体积，但会让风险挪到运行时，必须单独验证
- [x] **E2** 模型分发：运行时内置 + 首下到 `<数据根>/models/<档位>`（走 hf-mirror）
- [x] **E3** 全量回归：**34 模块 / 746 用例全绿**，12m28s
- [ ] **E4** `tools/eval_align.py` 量化对比：行级中位误差 6.04s → 目标 < 0.5s
  - **卡在素材**：夹具全是合成音（无唱词），拿不到真值；`retime_lines()` 已备好手段
- [x] **E5** 双产物 smoke + 真实平台；`--check` 输出 v3.0.0；onefile 122.8MB / onedir 11.4MB
- [x] **E6**（临时新增）`main.py --check-ai`：用**冻结产物**验证模型能加载并推理 ✅

---

## v3.0.1 修复：模型下载在真实环境必失败

用户实测反馈：设置页选好档位后点 AI 对齐 → 「AI 对齐失败：AI 模型下载失败（检查网络）」。
详见 DESIGN.md 40.17。

### F. 下载通道重写

- [x] **F1** 用 `urllib.request` 直连 `<endpoint>/<repo>/resolve/main/<file>` 替换 `snapshot_download`
  - 去掉 huggingface_hub / httpx2 / httpcore2 / anyio / fsspec / click / tqdm / filelock 八个三方包的关键路径依赖
- [x] **F2** 大文件可靠：`.part` 原子落盘、`Range` 续传、卡顿 30s 超时、3 次重试
  - `416` 丢坏片段重来；服务端忽略 Range 回 200 时从 0 重写（已单测）
- [x] **F3** 错误码分开：网络 `download_failed` / 本地写入 `disk_failed`
  - 4xx 除 408/429 立刻收手，不让用户白等三次超时
- [x] **F4** `ensure_model` 返回 `(目录, 错误码, 详情)`，真实原因一路带到 toast
  - v3.0.0 的「（检查网络）」是猜的；现在显示 `HTTP 503 ...` / `URLError: ...`
- [x] **F5** 单测 16 例：成功/续传/Range 被忽略/404 不重试/重试后成功/重试用尽/截断检测/磁盘错不重试/416 恢复
  - 期间抓出真 bug：416 被当普通 4xx 判死、坏片段删了却没重试 → 已修
- [x] **F6** `main.py --download-model [档位]` 诊断入口（下载 + `WhisperModel` 加载，报告写文件）

### G. 验收

- [x] **G1** ruff 干净；`tests.test_lyrics_asr` 43 例全绿
- [x] **G2** 全量回归：**34 模块 / 767 用例全绿**，16m52s
- [x] **G3** 重打包并在产物里验证：onefile 122.8MB / onedir 11.5MB，双 smoke + 真实平台 8s 通过
  - 冻结产物**全新数据目录**跑 `--download-model tiny`：从零下完 75MB，`WhisperModel` 加载 OK
  - 冻结产物跑 `--check-ai`（small 档 + 夹具音频）：import / 就绪 / 解码 / 推理全 OK
  - 真实数据目录里 `small`（461MB）3m35s 下完，四文件字节数与仓库一致

---

## v3.0.2 修复：批量对齐窗口关不掉

用户实测：批量对齐跑到「第 1 / 6 首」，点关闭没反应、「停止」是灰的、进度 0%。
详见 DESIGN.md 40.18。

### H. 中止链路

- [x] **H1** `transcribe(..., interrupted=)`：whisper `segments` 每段检查一次，段粒度几秒
- [x] **H2** `download_file(..., interrupted=)` / `ensure_model(..., interrupted=)`：分块检查，
      返回 `cancelled`，`.part` 留着下次续传
- [x] **H3** `LyricsAsrWorker` 把 `isInterruptionRequested` 作为谓词传下去（不是传布尔）
- [x] **H4** `align_track` 去掉 `detail or describe_error(...)` 兜底（会显示成「xxx（xxx）」）

### I. 对话框交互

- [x] **I1** 「停止」= 请求中止 + 留窗口看结果；按钮随即置灰防重复点
- [x] **I2** 「关闭」/窗口 X = 请求中止 + **完成后自动关闭**（永远有出路）
- [x] **I3** `_retire()` + `_retired` 列表：`wait(3000)` + `finished` 双保险，`closeEvent` 查所有活线程
- [x] **I4** 进度条改 `%v / %m 首`，不再用 0% 冒充推理进度
- [x] **I5** 主动中断不计入失败；行文案显示「已停止」

### J. 验收

- [x] **J1** ruff 干净；`TestInterruption` 4 例 + 对话框 6 例全绿（两模块 65 例）
- [x] **J2** 全量回归：**34 模块 / 780 用例全绿**，14m11s
- [x] **J3** 重打包：onefile 122.8MB / onedir 11.5MB，双 smoke + 真实平台 8s 通过
  - 真机验收 `tools/verify_abort_real.py`：4.5s 点关闭 → 10.2s 中止完成 → 自动关窗

---

## v3.0.3 提高逐字对齐准确率

用户要求减少逐字对齐误差、提高准确率。范围：全都要（信号处理 + 英文歌语言 + 大 beam/大模型）。
详见 DESIGN.md 40.19。

### K. 信号处理（onset 吸附）

- [x] **K1** `onset_envelope(rms, hop_ms, diff_ms)`：半波整流能量增量，抓音节起音上升沿
- [x] **K2** `snap_to_onset(...)`：字边界 ±120ms 吸 onset 峰，`best_val > 0` 守卫静音不挪
- [x] **K3** `align_lyrics(..., onset=)` + `align_track` 派生 onset 并透传；均分保底不退步

### L. 语言自动 + 手动指定

- [x] **L1** `guess_language(lines)`：汉字占比猜 zh/en，纯标点回退 zh
- [x] **L2** `LyricsAsrWorker` 默认 `language="auto"`，`run()` 解析成具体语种
- [x] **L3** 设置页「识别语言」下拉 + `Settings.lyrics_ai_language`
- [x] **L4** 右键「AI 对齐歌词（逐字）」改子菜单（自动/中文/英文），信号带语种

### M. 质量 / 大 beam

- [x] **M1** `transcribe`/`align_track` 增 `beam_size`；`AI_QUALITY_BEAM = {fast:1, balanced:5, quality:10}`
- [x] **M2** 设置页「识别质量」下拉 + `Settings.lyrics_ai_quality`

### N. 验收

- [x] **N1** ruff 干净；新增 `TestOnsetEnvelope`/`TestSnapToOnset`/`TestGuessLanguage`/
      `TestOnsetInAlign` + 语言信号共 13 例单测
- [x] **N2** 全量回归（本轮结果见交付说明）

---

## v3.0.4 收尾旧待办 + 歌词匹配评测集

两条从早期挂着的待办（#94 / #98）功能主体早已落地，本轮做收尾；另起歌词匹配评测集
作为「准确率 90%+」需求的第一步。详见 DESIGN.md 40.20。

### O. 崩溃日志收尾（#94）

- [x] **O1** 新增 `tests/test_crashlog.py`（10 例）：写入/追加/静默失败/轮转/钩子/install_qt
- [x] **O2** 修 `_rotate` 多留一份的 bug（`range(KEEP-1)` → `range(KEEP-2)`）
- [x] **O3** `run_tests.py` 注册 `tests.test_crashlog`

### P. 在线搜索多平台（#98）

- [x] **P1** `lyrics_multi.build_web_search_urls` / `web_search_url`（复用 LRCLIB 单源实现）
- [x] **P2** 右键「在线搜索歌词」改子菜单（LRCLIB/网易云/QQ音乐），信号带平台名
- [x] **P3** `main_window._open_lyrics_search(platform)` 按平台打开；未知平台给提示
- [x] **P4** 单测：`TestWebSearchUrls`（5 例）+ 菜单子项 emit（1 例）

### Q. 歌词匹配评测集（「准确率 90%+」第一步）

- [x] **Q1** `tools/eval_match.py`（precision / recall / 误配率）
- [x] **Q2** `tests/fixtures/lyrics_eval/cases.json`（14 条，中/英/日/韩 × 多场景）
- [x] **Q3** 跑出基线：precision 100% / recall 92% / 误配率 0%（唯一漏配=繁简）
- [ ] **Q4** 下一轮：繁简/NFKC 归一 → 权重重构 → 跨源投票+置信分档（每步用 eval 量化）

### R. 验收

- [x] **R1** ruff 干净；定向测试 crashlog+multi+menu 56 例全绿
- [x] **R2** 全量回归 35 模块全绿（10m25s）
