# 「轻音播放器」任务清单（TASK.md）

> 版本：v2.0 UI 改版 · 2026-10-25 · 状态：**待用户评审**
> 规则：按依赖顺序执行；每项完成即勾选并跑该项验证；修复循环 ≤3 轮，超限输出待人工确认项。
> 基线：`main @ 39d9251`（v1.1，91 项测试全绿，dist 双产物在手）。
> 迭代分支：`feat/ui-v2`。

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
