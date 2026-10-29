# v2.2 · 歌词联网补全 + 外观自定义（强调色 / 字号 / 背景）

## 起点：两条需求

1. **「可以识别歌曲歌词」** —— 现状是只有三种来源：手动绑定的 `.lrc`、同目录同名
   `.lrc`、音频内嵌歌词。三者都没有时，面板就一句「暂无歌词」。绝大多数从网上
   下载的歌都没有 `.lrc`，所以「识别歌词」实际等于**帮我把歌词找到**。
2. **「对于自定义背景更多内容可自定义」** —— 用户想要的不是一个开关，而是**能调**：
   背景本身（图片/纯色/渐变）、背景的观感（不透明度/模糊/暗化）、字体大小、
   强调色，并且能**按页面分别设置**。

## 决策（四项，逐项说明取舍）

### 1. 歌词来源：联网匹配（LRCLIB）

| 选项 | 说明 | 取舍 |
|---|---|---|
| A. 只认本地 | 现状 | 不联网、不依赖外部服务；但多数歌永远没歌词 |
| **B. 本地优先 + 联网兜底（采用）** | 本地找不到才按「歌名+艺人」检索 LRCLIB，命中缓存到本地 | 覆盖绝大多数歌；**代价是需要联网**，且首次匹配有 1~2 秒延迟 |
| C. 让用户手动搜 | 列表里选一条 | 最准；但每首歌都要人点，等于把活推回给用户 |

选 B，并且**联网可关闭**（设置 → 歌词与统计）。LRCLIB 是公开免费、无需 API key 的
歌词库，自带同步（LRC 时间戳）与纯文本两种歌词。

### 2. 匹配规则：宁可没有，也不能配错

给用户塞一首**别的歌**的歌词，比没有歌词更糟 —— 他会以为这歌的歌词就长这样。
所以 `pick_best()` 采用「身份信号」门槛：

- 歌名归一化（小写、去掉非字母数字）后互相包含 → +2，标记身份
- 艺人同上 → +1，标记身份
- 时长差 ≤3s → +3，标记身份；≤10s → +1
- 有同步歌词 → +0.5（同等条件下优先同步版）
- **没有任何身份信号的候选一律丢弃**

### 3. 外观：一个色值 + 一档字号

| 选项 | 说明 | 取舍 |
|---|---|---|
| A. 让用户分别调 ACCENT / HOVER / DIM / SOFT / ON_ACCENT | 自由度最大 | 四个色值很难配对，用户很容易调出「hover 比主色更暗、文字看不见」的组合 |
| **B. 只给一个色值，其余派生（采用）** | `derive_accent()` 按底色亮暗算 hover/dim/soft，按对比度选白/黑前景 | 一个色号就能换整套配色；代价是用户无法微调某个档位 |

字号同理：QSS 里有 20 多处 `font-size`，逐个控件的 font 会被 QSS 覆盖，所以
**在 QSS 文本层做乘法**（`build_stylesheet(font_scale=)`），一处生效、全局一致。
范围夹在 0.85~1.30 —— 行高 52、播放栏 84、侧栏 248 都是固定值，再大文字会被裁。

### 4. 背景：一条铺满窗口的底层 + 面板半透明

| 选项 | 说明 | 取舍 |
|---|---|---|
| A. 背景只铺内容区，侧栏/播放栏保持不透明 | 改动最小 | 自定义背景只在中间一块，像贴了张壁纸 |
| **B. 背景铺满整个窗口，面板转半透明（采用）** | 背景成为整个界面的底，chrome 浮在上面 | 观感统一；代价是 QSS 要把面板色全换成 rgba，并给浮层补不透明兜底 |

实现要点：
- `BackgroundLayer` 是最先创建的 `_root` 子控件 → 天然在最底层，鼠标穿透
- 图片用 `KeepAspectRatioByExpanding` + 居中裁切铺满（不留黑边、不变形）
- 模糊用「降采样 → 平滑升采样」近似高斯：`QGraphicsBlurEffect` 在 1280×800 上
  要上百毫秒且边缘发黑，而背景是低频内容，降采样的视觉效果等价、耗时几乎为零
- 有背景时 `build_stylesheet(scrim=0.78)` 把 SURFACE/BG 全局替换成 rgba，
  **再给窗口根 + 对话框/菜单/输入框补一段不透明覆盖**：
  - 窗口根必须不透明，否则把「背景不透明度」调低时透出的是**桌面**而不是主题底色
  - 对话框是独立顶层窗口，半透明会直接看到桌面内容
- 按页面分别设置：`bg_all / bg_library / bg_now` 三份配置，某页没单独设过就跟随
  「全部页面」；切页时 `_refresh_background()` 重新取一次

## 改动的文件

| 文件 | 变化 |
|---|---|
| `app/lyrics_online.py` | **新增**：`build_search_url` / `parse_hits` / `pick_best` / `fetch_lyrics` / 缓存读写 / `LyricsFetchWorker` |
| `ui/background.py` | **新增**：`BackgroundLayer` 画布 + `prepare_pixmap`（裁切+模糊+缓存） |
| `app/models.py` | `Settings` 增加 `online_lyrics` / `accent_color` / `font_scale` / 三份 `BackgroundConfig`；新增 `BackgroundConfig` 与 `bg_config(page)` |
| `app/paths.py` | 增加 `lyrics_cache_dir()`、`bgs_dir()` |
| `app/library.py` | 增加 `import_background()`（背景图复制进数据目录，同名同内容复用） |
| `ui/theme.py` | `derive_accent` / `clamp_font_scale` / `_scale_font_sizes` / `set_appearance` / `build_stylesheet(scrim=)`；颜色工具 `mix` / `luminance` / `contrast` |
| `ui/main_window.py` | 歌词四级来源 + 异步第 5 级；`_apply_appearance` 统一入口；背景层装配与按页取配置 |
| `ui/settings_dialog.py` | 改为三页签（外观 / 背景 / 歌词与统计），新增色板、字号档位、背景全部控件 |
| `ui/lyrics_panel.py` | `set_empty(hint)` 之后能恢复默认文案（原来临时提示会永久留在面板上） |
| `tools/shot.py` | `--accent` / `--font-scale` / `--bg` / `--settings-tab` / `--tag`，并改为调用应用自己的 `_apply_appearance` |
| `run_tests.py` | 增加 `test_lyrics_online`、`test_background`、`TestE2ELyricsOnline`、`TestE2EAppearance` 四个进程 |

## 踩到的坑（真实问题，已修）

1. **`TestE2EV2` 涨到 26 项后 600s 超时** —— 卡在 `test_theme_switch_applies_and_persists`。
   这是已知的 QMediaPlayer 累积死锁（同进程 ~15-20 个实例），不是逻辑错误。按项目
   既定做法拆成独立进程：新增 `TestE2ELyricsOnline`（5 项）、`TestE2EAppearance`（14 项）。
2. **截图工具漏了 scrim** —— `tools/shot.py` 原来直接调 `set_appearance(...)`（不传
   scrim），把应用自己算好的半透明样式又覆盖回不透明 → 截图里背景被面板完全盖住，
   列头还是一条黑带子。改成调用 `window._apply_appearance(save=False)`（应用自身的入口）。
3. **列头黑带** —— 一开始页面底色（`#HeaderBar` / `#ColumnHeaderBar`）用了和面板同样的
   不透明度，而 `BG` 在深色主题里几乎全黑 → 变成一条压在图上的黑带。改为
   `alpha × 0.42`。
4. **`isVisibleTo()` 在非当前页签上误报** —— 页签内容本来就被 QTabWidget 隐藏，
   可见性断言必须用 `isHidden()`。
5. **`grab()` 验证不了透明度** —— grab 会先铺不透明白底，白色背景 × 任何透明度都是白的。
   改为 `QWidget.render(QImage)` 画到黑图上再采样。
6. **`Settings` 丢过 `@dataclass`** —— 插入 `BackgroundConfig` 时把装饰器挤掉了，
   `field(default_factory=...)` 变成裸 `Field` 对象，`bg_config()` 直接 AttributeError。
7. **写入真实 APPDATA** —— 验证 `import_background` 时没隔离 `APPDATA`，往用户真实
   数据目录塞了一张图（已清理）。教训复用既有铁律：任何构造 / 写数据的脚本先隔离。

## 验收

- 新增 `tests/test_lyrics_online.py`（25 项）：URL 编码、脏数据容忍、选曲打分与身份门槛、
  断网降级、缓存读写/失败不留残片、后台线程发信号（全程不联网，`fetch` 注入）
- 新增 `tests/test_background.py`（16 项）：图片导入/复用、铺满裁切不变形、模糊改像素但
  不改尺寸、缓存命中、四种类型都能画、不透明度可见差异、scrim 样式表（面板透明 /
  窗口根与对话框不透明）
- `tests/test_theme.py` +9 项：强调色派生（hover/dim 通道差 ≥12、任意色 ON_ACCENT ≥3:1、
  脏值回落）、字号缩放（乘数、下限 9px、夹取范围）
- `tests/test_store.py` +3 项：外观字段往返、老数据默认值、脏 `font_scale` 回落
- e2e：新增 `TestE2ELyricsOnline`（5 项）、`TestE2EAppearance`（14 项，含背景应用/持久化/
  按页覆盖/关闭还原/主题切换后仍生效、Toast 居中）
- 全量回归 **331 项 / 22 个进程**全绿；`ruff check .` 干净
- 视觉验收：`tools/shot.py` 出图（渐变背景、模糊图片背景、浅色纯色背景、设置背景页、
  强调色橙/绿、特大字号），逐张人工检查
- 交付物：`dist/QingYinPlayer.exe`（单文件 55.6MB）、
  `dist/QingYinPlayer-Portable/QingYinPlayer-Portable.exe`（目录版 2.4MB）；
  两者 smoke 与真实平台 8s 存活检查均通过，图标 14885B 未被污染
