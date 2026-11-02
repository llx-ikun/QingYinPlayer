# v2.1.5 交付概览：浅色主题改浅蓝 + 移除前进/后退按钮

> 日期：2026-10-26 · 基线：v2.1.4 (`3826093`)

## 一、本次改动来自三条用户诉求

| # | 用户原话要点 | 结论 |
|---|---|---|
| 1 | 「主题浅色为浅蓝」（原为 QQ 绿） | 浅色整套换浅蓝，与深色主题蓝紫强调色、应用图标渐变统一色系 |
| 2 | 截图圈出标题栏「← 后退 / → 前进」→ **这个不要** | 两个按钮删除，`Alt+←` / `Alt+→` 快捷键保留（功能不丢） |
| 3 | 「可以导入 `…Blazing Heart (英文版).flac`」 | 已验证可解码并导入本机曲库 |

另外按用户 10-26 21:35 的长期要求，顺手把**反复污染测试夹具目录**这个根因修掉了。

## 二、改了什么

### 1. 浅蓝主题（`ui/theme.py`）

```python
LIGHT = Theme(
    name="light",
    BG="#f3f6fc", SURFACE="#ffffff", SURFACE_HOVER="#eef3fb", SURFACE_ACTIVE="#e3ecfb",
    BORDER="#dde5f3", TEXT="#1f2329", TEXT_DIM="#7f8b9e",
    ACCENT="#3b82f6", ACCENT_HOVER="#2f74ea", ACCENT_DIM="#2563eb",
    ACCENT_SOFT="#e7f0fe", DANGER="#e14a4a", HEART="#ec4141", ON_ACCENT="#ffffff",
)
```

底板、边框、悬浮态全部带蓝调，不再是中性灰 + 绿色强调。

### 2. 移除标题栏导航按钮（`ui/title_bar.py` / `ui/main_window.py`）

- 删：`back_btn` / `fwd_btn`、`back_clicked` / `forward_clicked` 信号、`set_nav_enabled()`、`_update_nav_buttons()` 及其 4 处调用。
- 留：刷新 ↻（tooltip 改为「刷新当前视图（Alt+← / Alt+→ 可切换视图）」）。
- 标题栏现在只剩 logo + 标题 + 刷新 + 搜索框。

### 3. 歌词颜色不再被冻结（`ui/lyrics_panel.py`）

`_NORMAL = QColor(TEXT_DIM)` 是**类属性**，在模块导入那一刻求值（当时是深色主题）。之后切到浅色主题，歌词仍是深灰，浅底上对比度不足。改为 `_normal_color()` 运行时取 `current_theme().TEXT_DIM`。

### 4. 测试夹具与用户目录隔离（`tests/make_fixtures.py` / `build.py`）

按用户要求，`tests/fixtures/我的音乐` 只能放他本人提供的音乐。此前 `ensure_fixtures()` 直接往该目录写 6 个合成文件，导致每次跑测试就被塞满，且应用导入过这些路径后、夹具被清理时库里留下失效条目。

```python
GENERATED = os.path.join(FIXTURES, "_generated")
MUSIC_DIR = os.path.join(GENERATED, "我的音乐")   # 中文路径覆盖保留
VIDEO_DIR = os.path.join(GENERATED, "我的视频")
```

`build.py` 相应改为 `os.path.join(ensure_fixtures(), "晴天 - 周杰伦.mp3")`，不再硬编码。

### 5. 写库脚本静默失败（`app/store.py`）

`LibraryStore()` 不传路径时 `_path = None`，`load()` / `save()` 全是空操作（`open(None)` 抛的 `TypeError` 被 `except Exception` 吞掉）。所以上一轮「删除失效条目」实际什么都没做。现在 `__init__` 明确写了「`path=None` = 纯内存 store」，`load()` 增加 `if not self._path: return` 前置守卫。

### 6. 图标测试不再改写仓库资产（`build.py` / `tests/test_icon.py`）

`test_icon` 原来直接调 `generate_icon()` 的默认路径，而回归是在 offscreen 下跑的 —— 字体库为空，`♫` 画不出来，于是把 `assets/app.ico` 从 **14885 B 覆盖成 11515 B 的空白图标**。如果这份文件被提交或打包，「窗口图标空白」那个老问题就复发了。

`generate_icon(out_path=None)` 支持指定输出路径后，测试一律写临时目录，并新增两条断言：仓库资产哈希不变、仓库图标能被 `QIcon` 加载出 7 个尺寸。提交前已用**真实平台**重新生成正式图标，并导出 256 尺寸目视确认（蓝紫渐变 + 白色音符）。

### 7. 构建自检污染用户曲库（`main.py` / `build.py`）

`build.py` 每个产物都会跑 `exe --smoke <音频>` 验证解码，而 smoke 分支走的是 `MainWindow → store.add_or_update()`，store 默认落在 `%APPDATA%\轻音播放器\data.json` —— **用户真实曲库**。结果就是：**每构建一次，曲库里就多一条合成夹具「晴天」**，退出时还会覆盖 `last_view` / `last_track_id`。

这才是「晴天删掉又出现」的最终真相 —— 前两次清理只清了表象，罪魁每次构建都会把它写回来。

现在 `--smoke` 在创建窗口**之前**把 `APPDATA` 指向 `tempfile.mkdtemp()`（`atexit` 清理），`build._real_platform_check()` 也注入隔离的 APPDATA。新增 `tests/test_smoke_isolation.py` 2 项：独立进程跑 `main.py --smoke`，APPDATA 预置一份哨兵 `data.json`，跑完断言**逐字节不变**且没有多出文件。反向验证：临时移除隔离后这 2 项立即失败。

## 三、验证证据

| 项目 | 结果 |
|---|---|
| 主题调色板 | `tests/test_theme.py` **10 项**：两主题强调色蓝通道主导、浅底带蓝调、正文对比度 ≥7:1、强调色 ≥3:1、`ACCENT_SOFT` 是淡底、旧 QQ 绿 5 个色值零残留 |
| 歌词色跟随主题 | `TestLyricsThemeColor` **4 项**。**反向验证**：把颜色重新冻结到深色值后，其中 3 项立即失败 |
| 导航按钮已移除 | `test_title_bar_has_no_back_forward_buttons` + `test_view_history_shortcuts_still_bound` |
| 夹具目录隔离 | `TestFixtureIsolation` **3 项**（生成物不在用户目录 / 再调一次仍为空 / 6 个合成文件齐全） |
| 全量回归 | **17 个独立进程 234 项全绿** |
| 静态检查 | `ruff check .` → `All checks passed!` |
| 双 EXE | `build_v215.log`：onefile + onedir，smoke + 真实平台 8s 存活检查通过 |

## 四、本机曲库处理（`%APPDATA%\轻音播放器\data.json`，改动前均备份 `.bak-<时间戳>`）

- **删除**指向已清空夹具的失效条目「晴天」（`tests/fixtures/我的音乐/晴天 - 周杰伦.mp3`），并清空指向它的 `last_track_id` / `last_position_ms`。
- **导入** `<音乐目录>\Chrissy Costanza _ HOYO-MiX - Blazing Heart (英文版).flac`：
  - 标题 `Blazing Heart (英文版)` · 艺人 `Chrissy Costanza/HOYO-MiX` · 专辑 `原神-灼火之心 Blazing Heart`
  - 时长 **177.98 s** · 格式 `flac` · 内嵌封面 83483 B · 文件大小 **38.2 MB**
  - `tools/check_media.py` 实测 `QMediaPlayer` → `LoadedMedia`、无错误
- 最终曲库 2 条：`35336355964-1-192.mp4` + `Blazing Heart (英文版).flac`。

## 五、需要你在本机确认的

- 浅蓝主题的实际观感（颜色已按色相/对比度断言，渲染效果建议自己看一眼）。
- 声音输出：沙箱无音频设备，FLAC 解码已验证，**实际出声需你双击 EXE 确认**。
