# 「轻音播放器」任务清单（TASK.md）

> 版本：v1.0 · 2026-10-24 · 状态：**待用户评审**
> 规则：按依赖顺序执行；每项完成即勾选并跑该项验证；修复循环 ≤3 轮。

## 阶段 0：脚手架（依赖：无）

- [x] **T0.1** 初始化项目结构（`main.py`、`app/`、`ui/`、`tests/`、`assets/`）+ `.gitignore`（.venv/dist/build/__pycache__/测试夹具）
  - 验收：`python main.py --check` 能打印版本信息并不报错
- [x] **T0.2** `requirements.txt`（PySide6、mutagen）+ `requirements-dev.txt`（pyinstaller、soundfile、lameenc、numpy）+ README 记录阿里云镜像与 `env -u PYTHONPATH` 注意事项
  - 验收：venv 内 `pip install -r requirements.txt` 成功

## 阶段 1：后端核心（依赖：T0）

- [x] **T1.1** `app/models.py`：Track/Playlist/Settings dataclass + `app/paths.py`（AppData 路径解析）
  - 验收：字段与 DESIGN §5 一致
- [x] **T1.2** `app/lyrics.py`：LRC 解析 + 索引 + 时间格式化（纯逻辑）
  - 验收：单测覆盖多时间标签/offset/元数据/畸形行/索引边界
- [x] **T1.3** `app/metadata.py`：mutagen 封装（元数据/封面/歌词提取，含中文标签容错）
  - 验收：对 mp3/flac/wav 夹具读取 title/artist/album/duration/封面/内嵌歌词
- [x] **T1.4** `app/store.py`：JSON 持久化 + 库/歌单 CRUD + 设置 + 最近播放
  - 验收：单测覆盖 CRUD/去重/round-trip（临时目录）
- [x] **T1.5** `app/covers.py`：封面懒提取 + 磁盘缓存 + 渐变占位图
  - 验收：有封面曲目出 QPixmap；无封面出占位图；二次读取命中缓存
- [x] **T1.6** `app/scanner.py`：QThread 递归扫描 + 进度信号 + 取消
  - 验收：扫描含中文名/多格式目录，信号进度正确，取消即停

## 阶段 2：播放核心（依赖：T1.1/T1.2）

- [x] **T2.1** `app/player.py`：PlaybackController（QMediaPlayer 封装：播放/暂停/切歌/seek/音量/静音 + 信号）
  - 验收：offscreen 下 setSource→LoadedMedia、seek 生效、音量生效、状态信号正确（沙箱无音频渲染，position 推进不验证）
- [x] **T2.2** 队列与播放模式（sequential/loop/single/shuffle + previous 语义 + 结束自动续播）
  - 验收：单测覆盖四种模式 next/previous/播完行为
- [x] **T2.3** 错误处理：文件丢失/不可播 → broken 标记 + 信号通知 UI + 自动跳过
  - 验收：删除文件后播放触发 error 信号，不崩溃

## 阶段 3：UI（依赖：T1/T2）

- [x] **T3.1** `ui/theme.py`：深色 QSS + 调色板 + 应用图标（Qt 生成 app.ico）
- [x] **T3.2** `ui/main_window.py` + `ui/sidebar.py`：主窗口骨架、侧边栏导航（资料库/最近播放/歌单列表/新建/导入按钮）
- [x] **T3.3** `ui/track_list.py`：曲目列表（封面+标题/艺人+时长）、右键菜单、拖拽排序、搜索过滤、排序
- [x] **T3.4** `ui/player_bar.py`：底部播放栏（封面/信息/控制/进度拖动/音量/模式/歌词开关）
- [x] **T3.5** `ui/lyrics_panel.py`：歌词面板（同步高亮/自动滚动/点击跳转/占位）
- [x] **T3.6** `ui/now_playing.py`：正在播放视图（大封面+信息+歌词）
- [x] **T3.7** 对话框：新建/重命名歌单、添加到歌单、绑定歌词、导入进度
- [x] **T3.8** 持久化恢复（音量/模式/上次曲目与位置/视图）+ 快捷键 + 空状态 + 状态栏提示

## 阶段 4：测试与修复（依赖：T3）

- [x] **T4.1** `tests/make_fixtures.py`：生成多格式合成音频（含中文文件名/ID3 标签/同名 LRC/内嵌歌词）
- [x] **T4.2** 单测全套绿（lyrics/store/player 队列）
- [x] **T4.3** E2E（offscreen）：导入→播放→seek/音量→切歌→歌单操作→歌词联动→重启恢复
- [x] **T4.4** 缺陷修复循环（≤3 轮，超限输出待人工确认项）

## 阶段 5：打包交付（依赖：T4）

- [x] **T5.1** `build.py`：PyInstaller onefile + onedir 双产物（中文名 exe、app.ico、windowed）
- [x] **T5.2** 打包 smoke test：offscreen 启动产物、加载库、正常退出
- [x] **T5.3** README（使用说明/快捷键/已知事项：m4a 🟡、声音需本机验证、杀软误报说明）
- [x] **T5.4** git 提交（Conventional Commits）+ 交付报告（变更摘要 + 验收对照 + 遗留项）

---

## 依赖关系

```
T0 → T1.1 → T1.2 → T2.1 → T2.2 → T3.x → T4.x → T5.x
        ↘ T1.3/T1.4/T1.5/T1.6（可与 T1.2 并行）
T2.3 依赖 T2.1；T3.5 依赖 T1.2；T3.6 依赖 T3.4/T3.5；T3.8 依赖 T3.2-T3.7
```

## 验证命令速查

```bash
cd music-player
env -u PYTHONPATH .venv/Scripts/python.exe -m unittest discover -s tests -v   # 单测+E2E
env -u PYTHONPATH QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe main.py  # offscreen 启动
```
