# 「轻音播放器」任务清单（TASK.md）

> 当前版本：v2.1 本地视频导入与画面播放 · 2026-10-26 · 状态：**待用户评审**
> 规则：按依赖顺序执行；每项完成即勾选并跑该项验证；修复循环 ≤3 轮，超限输出待人工确认项。
> 基线：`main @ 7c4d5b1`（v2.0，122 项测试全绿，dist 双产物在手）。
> 迭代分支：`feat/video-v2_1`（用户确认设计后创建）。

## A. 后端（app/，无 UI 依赖，先行）

- [ ] **A1** `app/models.py`：新增 `PLAYLIST_FAVORITES = "__favorites__"`；`Settings` 增加 `theme: str = "dark"`、`nickname: str = "音乐爱好者"`（含 `to_dict/from_dict`，旧数据无损升级）
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
- [ ] **J2** `env -u PYTHONPATH .venv/Scripts/python.exe build.py` 重建双产物（smoke + 真实平台检查）
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

## v2.1 依赖关系

```
K1 → K2 → K3 → L1 → L2 → L3 → M1 → M2 → M3 → M4 → N1 → N2 → N3 → N4 → O1 → O2 → O3 → O4
```

## v2.1 验收命令

```bash
cd music-player
env -u PYTHONPATH .venv/Scripts/python.exe run_tests.py
env -u PYTHONPATH .venv/Scripts/python.exe -m ruff check .
env -u PYTHONPATH .venv/Scripts/python.exe build.py
```
